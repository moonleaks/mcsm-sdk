# SPDX-License-Identifier: GPL-2.0-or-later
"""Read and rebuild Telltale ``.ttarch2`` archives (TTA3/TTA4).

Layout (all little-endian), verified against the retail game files:

    container header
        "TTCN" <u64 payload size>                     nothing compressed
        "TTCE" <u32 window><u32 chunks>
               <u64 offsets[chunks+1]>                 encrypted + deflate
        "TTCZ"  same as TTCE, no encryption            deflate
        lowercase "TTCe"/"TTCz" prefix a u32 codec (1 = Oodle, unsupported)
        offsets are absolute file offsets
    inner archive
        "TTA3" <u32 reserved> <u32 names bytes> <u32 file count>
        "TTA4"               <u32 names bytes> <u32 file count>
        <u64 crc64><u64 offset><u32 size><u32 preload><u16 page><u16 page off>  x count
        names (NUL separated, zero padded to a 64 KiB multiple)
        file data (entry offsets are relative to the end of the names table)
"""

import mmap
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from .blowfish import Blowfish
from .crc64 import crc64

NAME_CHUNK = 0x10000
PAGE = NAME_CHUNK

# Minecraft: Story Mode retail key (TTARCH2 / v7). Binary, not a passphrase:
# this build's key is the 55-byte blob ttarchext's game table carries for MCSM.
MCSM_KEY = (
    b"\x8c\xd2\x9b\x99\x87\xde\x94\xa9\xe6\x9d\xa5\x94\x7f\xce\xc1\xbc"
    b"\xcc\x9c\x8e\xdd\xb1\xa6\x66\x9f\xb2\x8a\xdd\xba\x9c\xde\xc2\x9a"
    b"\xd3\x76\x62\x7f\xae\xcc\xa7\xd1\xd8\xe6\xd9\xd2\xab\x63\x82\x9f"
    b"\x92\xcc\x94\x98\xd3\xe4\xa0"
)
DEFAULT_VERSION = 4

_INNER = {"TTA2", "TTA3", "TTA4"}


class ArchiveError(Exception):
    """Malformed archive, unsupported feature, or bad input."""


@dataclass
class Entry:
    name: str
    crc: int
    offset: int
    size: int


def _tag(raw: bytes) -> str:
    return raw[::-1].decode("latin1")


def _round_up(n: int, m: int) -> int:
    return (n + m - 1) // m * m


class _Cursor:
    """Sequential reader over the decoded inner payload."""

    def __init__(self, archive):
        self._archive = archive
        self.pos = 0

    def read(self, n: int) -> bytes:
        data = self._archive._payload(self.pos, n)
        self.pos += n
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]


class Archive:
    """A parsed .ttarch2. File data is decoded lazily from the mapped file."""

    def __init__(self, path, key: bytes):
        self.path = Path(path)
        self.key = key
        self._file = open(self.path, "rb")
        try:
            self._mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            self._file.close()
            raise
        self._chunk_cache: dict[int, bytes] = {}
        self._payload_length = None
        try:
            self._parse()
        except Exception:
            self.close()
            raise

    # -- container / header ------------------------------------------------

    def _parse(self):
        if len(self._mm) < 4:
            raise ArchiveError("file is too small to be an archive")
        tag = _tag(self._mm[:4])
        self.encrypted = False
        self.compressed = False
        self.window = 0
        self._chunk_sizes: list[int] = []
        self._offsets: list[int] = []

        if tag in ("TTA2", "TTA3", "TTA4"):
            self.container = None
            self._payload_start = 0
        elif tag == "TTCN":
            self.container = tag
            self._payload_start = 12
        elif tag in ("TTCE", "TTCZ", "TTCe", "TTCz"):
            self.container = tag
            self.encrypted = tag in ("TTCE", "TTCe")
            self.compressed = True
            pos = 4
            # Only the lowercase tags carry a codec field; uppercase means DEFLATE.
            if tag in ("TTCe", "TTCz"):
                kind = struct.unpack_from("<I", self._mm, pos)[0]
                if kind != 0:
                    raise ArchiveError(
                        "archive uses Oodle compression (codec 1); "
                        "only DEFLATE archives are supported"
                    )
                pos += 4
            self.window = struct.unpack_from("<I", self._mm, pos)[0]
            chunks = struct.unpack_from("<I", self._mm, pos + 4)[0]
            if chunks == 0 or self.window == 0:
                raise ArchiveError("archive declares no chunks")
            self._offsets = list(
                struct.unpack_from(f"<{chunks + 1}Q", self._mm, pos + 8)
            )
            self._payload_start = pos + 8 + 8 * (chunks + 1)
            self._chunk_sizes = [
                self._offsets[i + 1] - self._offsets[i] for i in range(chunks)
            ]
            if self.encrypted and not self.key:
                raise ArchiveError("archive is encrypted but no key was given")
            self._blowfish = Blowfish(self.key) if self.encrypted else None
        else:
            raise ArchiveError(
                f"unsupported container/version {tag!r} "
                "(expected a .ttarch2: TTCN/TTCE/TTCZ or TTA3/TTA4)"
            )

        cur = _Cursor(self)
        version = _tag(cur.read(4))
        if version not in _INNER:
            raise ArchiveError(f"unsupported inner archive version {version!r}")
        if version == "TTA2":
            raise ArchiveError("TTA2 archives are not supported (no name table layout)")
        self.version = int(version[-1])
        if version == "TTA3":
            cur.u32()  # reserved; Telltale writes 2

        names_size = cur.u32()
        count = cur.u32()
        if count > 0x100000:
            raise ArchiveError(f"implausible file count {count}")

        entries = []
        for _ in range(count):
            crc = cur.u64()
            offset = cur.u64()
            size = cur.u32()
            cur.u32()  # preload size, unused
            page = cur.u16()
            page_off = cur.u16()
            entries.append((crc, offset, size, page, page_off))

        self._names_start = cur.pos
        self._data_start = cur.pos + names_size
        names = self._payload(cur.pos, names_size)

        self.entries = []
        for crc, offset, size, page, page_off in entries:
            start = page * PAGE + page_off
            end = names.find(b"\0", start)
            if start >= len(names) or end < 0:
                raise ArchiveError(f"entry {len(self.entries)} has an invalid name offset")
            name = names[start:end].decode("ascii", "replace")
            self.entries.append(Entry(name, crc, offset, size))
        self._by_name = {e.name.lower(): e for e in self.entries}

    # -- payload access ----------------------------------------------------

    def _chunk(self, index: int) -> bytes:
        cached = self._chunk_cache.get(index)
        if cached is not None:
            return cached
        # Retail archives store absolute offsets; older tools wrote relative ones.
        begin = (
            self._offsets[index]
            if self._offsets[0]
            else self._payload_start + self._offsets[index]
        )
        size = self._chunk_sizes[index]
        end = begin + size
        if end > len(self._mm):
            raise ArchiveError(f"chunk {index} runs past end of file")
        raw = self._mm[begin:end]
        if self._blowfish is not None:
            raw = self._blowfish.decrypt(raw)
        if size == self.window:  # stored uncompressed (reference tool convention)
            data = raw
        else:
            try:
                data = zlib.decompress(raw, -15)
            except zlib.error:
                try:
                    data = zlib.decompress(raw)  # some builds use zlib framing
                except zlib.error:
                    raise ArchiveError(
                        f"could not decode chunk {index}: wrong Blowfish key "
                        "or corrupt archive"
                    ) from None
        if len(self._chunk_cache) >= 8:
            self._chunk_cache.pop(next(iter(self._chunk_cache)))
        self._chunk_cache[index] = data
        return data

    def _payload(self, offset: int, size: int) -> bytes:
        if size < 0 or offset < 0:
            raise ArchiveError("negative read requested")
        if not self.compressed:
            begin = self._payload_start + offset
            end = begin + size
            if end > len(self._mm):
                raise ArchiveError("read runs past end of file")
            return self._mm[begin:end]
        if self._payload_length is None:
            last = self.window * (len(self._chunk_sizes) - 1) + len(
                self._chunk(len(self._chunk_sizes) - 1)
            )
            self._payload_length = last
        if offset + size > self._payload_length:
            raise ArchiveError("read runs past end of decoded payload")
        out = bytearray()
        while size:
            index, within = divmod(offset, self.window)
            chunk = self._chunk(index)
            take = min(size, len(chunk) - within)
            if take <= 0:
                raise ArchiveError("truncated chunk while reading")
            out += chunk[within:within + take]
            offset += take
            size -= take
        return bytes(out)

    def read(self, name: str) -> bytes:
        entry = self._by_name.get(name.lower())
        if entry is None:
            raise KeyError(name)
        return self._payload(self._data_start + entry.offset, entry.size)

    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def extract_all(self, destination, names=None):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        written = 0
        for entry in self.entries:
            if names is not None and entry.name not in names:
                continue
            target = _safe_join(destination, entry.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.read(entry.name))
            written += 1
        return written

    def settings(self) -> dict:
        return {
            "key": self.key,
            "version": self.version,
            "compress": self.compressed,
            "encrypt": self.encrypted,
        }

    def close(self):
        self._chunk_cache.clear()
        mm = getattr(self, "_mm", None)
        if mm is not None:
            self._mm = None
            mm.close()
        if getattr(self, "_file", None) is not None:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # -- writing -----------------------------------------------------------

    @classmethod
    def open(cls, path, key: bytes | str | None = None) -> "Archive":
        if key is None:
            key = MCSM_KEY
        if isinstance(key, str):
            key = key.encode("latin1")
        return cls(path, key)

    @classmethod
    def create(
        cls,
        path,
        files,
        key: bytes | str | None = None,
        version: int | None = None,
        compress: bool = True,
        encrypt: bool = True,
    ):
        """Build an archive from ``(name, bytes or path)`` pairs.

        Defaults match Minecraft: Story Mode: TTA4, encrypted, DEFLATE.
        Set ``encrypt=False`` and ``compress=False`` to write a plain TTCN.
        """
        if key is None:
            key = MCSM_KEY
        if version is None:
            version = DEFAULT_VERSION
        if isinstance(key, str):
            key = key.encode("latin1")
        if version not in (3, 4):
            raise ValueError("version must be 3 or 4")
        if encrypt and not compress:
            raise ValueError("Telltale encrypted containers always use DEFLATE")
        items = []
        for name, source in files:
            _check_name(name)
            if isinstance(source, (bytes, bytearray, memoryview)):
                data, size = bytes(source), len(source)
            else:
                source = Path(source)
                data, size = None, source.stat().st_size
            items.append((name, data, source if data is None else None, size))

        names_blob = b"".join(n.encode("ascii") + b"\0" for n, *_ in items)
        names_size = max(_round_up(len(names_blob), NAME_CHUNK), NAME_CHUNK)
        table = bytearray()
        offset = 0
        cursor = 0
        for name, _, _, size in items:
            page, page_off = divmod(cursor, PAGE)
            table += struct.pack(
                "<QQIIHH", crc64(name), offset, size, 0, page, page_off
            )
            cursor += len(name.encode("ascii")) + 1
            offset += size

        header = bytearray()
        header += (f"TTA{version}"[::-1]).encode("ascii")
        if version == 3:
            header += struct.pack("<I", 2)  # reserved, as written by ttarchext
        header += struct.pack("<II", names_size, len(items))

        with tempfile.TemporaryFile() as payload:
            payload.write(header)
            payload.write(table)
            payload.write(names_blob.ljust(names_size, b"\0"))
            for _, data, source, _ in items:
                if data is not None:
                    payload.write(data)
                else:
                    with open(source, "rb") as fh:
                        while chunk := fh.read(1 << 20):
                            payload.write(chunk)
            length = payload.tell()
            payload.seek(0)
            with open(path, "wb") as out:
                if not compress and not encrypt:
                    out.write(b"TTCN"[::-1])
                    out.write(struct.pack("<Q", length))
                    while chunk := payload.read(1 << 20):
                        out.write(chunk)
                else:
                    _write_deflate(out, payload, length, key if encrypt else None)
        return cls(path, key)


def _write_deflate(out, payload, length: int, key: bytes | None):
    window = NAME_CHUNK
    chunks = max(1, -(-length // window))
    magic = "TTCE" if key else "TTCZ"
    out.write(magic[::-1].encode("ascii"))
    out.write(struct.pack("<II", window, chunks))
    table_pos = out.tell()
    out.write(b"\0" * (8 * (chunks + 1)))

    cipher = Blowfish(key) if key else None
    # Real archives store absolute file offsets (first = end of the chunk table).
    offsets = [table_pos + 8 * (chunks + 1)]
    written = offsets[0]
    for _ in range(chunks):
        block = payload.read(window)
        if len(block) < window:
            block = block.ljust(window, b"\0")
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        raw = compressor.compress(block) + compressor.flush()
        if len(raw) >= window:  # convention: a window-sized chunk is stored as-is
            raw = block
        if cipher is not None:
            raw = cipher.encrypt(raw)
        out.write(raw)
        written += len(raw)
        offsets.append(written)

    end = out.tell()
    out.seek(table_pos)
    out.write(struct.pack(f"<{chunks + 1}Q", *offsets))
    out.seek(end)


def _check_name(name: str):
    if not name or "\0" in name:
        raise ArchiveError(f"invalid archive entry name {name!r}")
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        raise ArchiveError(f"entry names must be ASCII: {name!r}") from None


def _safe_join(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ArchiveError(f"entry {name!r} escapes the output directory")
    return target


def pack_directory(directory, path, **options):
    """Convenience: archive every file under ``directory`` (POSIX-style names)."""
    directory = Path(directory)
    files = []
    for file in sorted(directory.rglob("*")):
        if file.is_file():
            files.append((file.relative_to(directory).as_posix(), file))
    return Archive.create(path, files, **options)
