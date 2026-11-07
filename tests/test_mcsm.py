# SPDX-License-Identifier: MIT
import contextlib
import io
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from mcsm.__main__ import main
from mcsm.blowfish import _HAS_NUMPY, Blowfish
from mcsm.crc64 import MASK64, crc64
from mcsm.ttarch import Archive, ArchiveError

try:
    from Crypto.Cipher import Blowfish as PyCryptoBlowfish
except ImportError:  # dev-only reference
    PyCryptoBlowfish = None


def _swap4(data: bytes) -> bytes:
    """Telltale reads cipher words little-endian; pycryptodome uses big-endian."""
    return b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))


def _bitwise_crc64(text: str) -> int:
    crc = 0
    for byte in text.lower().encode("ascii"):
        crc ^= byte << 56
        for _ in range(8):
            crc = ((crc << 1) ^ 0x42F0E1EBA9EA3693) if crc & (1 << 63) else crc << 1
            crc &= MASK64
    return crc


class BlowfishTests(unittest.TestCase):
    def test_standard_variant_matches_known_vector(self):
        # Canonical Blowfish vector, words read little-endian by Telltale's code.
        cipher = Blowfish(b"\x00" * 8, modified=False)
        self.assertEqual(cipher.encrypt(b"\x00" * 8).hex(), "4597f94e78dd9861")

    @unittest.skipIf(PyCryptoBlowfish is None, "pycryptodome not installed")
    def test_standard_variant_matches_pycryptodome(self):
        for key in (b"Mcsm", b"abcdefghijklmnopqrstuvwxyz", bytes(range(16))):
            plain = bytes(range(64)) * 3
            mine = Blowfish(key, modified=False).encrypt(plain)
            ref = _swap4(PyCryptoBlowfish.new(key, PyCryptoBlowfish.MODE_ECB).encrypt(_swap4(plain)))
            self.assertEqual(mine, ref)
            self.assertEqual(Blowfish(key, modified=False).decrypt(mine), plain)

    def test_modified_variant_roundtrip_and_kat(self):
        cipher = Blowfish(b"Mcsm")
        # Locked regression value from this implementation of the v7 cipher.
        self.assertEqual(cipher.encrypt(b"A" * 16).hex(), "3d6d2241fc47bfbc3d6d2241fc47bfbc")
        plain = bytes(range(256))
        self.assertEqual(cipher.decrypt(cipher.encrypt(plain)), plain)

    def test_trailing_partial_block_is_untouched(self):
        cipher = Blowfish(b"Mcsm")
        data = bytes(range(11))
        out = cipher.encrypt(data)
        self.assertEqual(out[8:], data[8:])
        self.assertNotEqual(out[:8], data[:8])

    @unittest.skipUnless(_HAS_NUMPY, "numpy not installed")
    def test_numpy_path_matches_scalar(self):
        cipher = Blowfish(b"Mcsm")
        data = bytes(range(256))
        self.assertEqual(cipher._bulk(data, False), cipher._scalar(data, False))
        encrypted = cipher._bulk(data, False)
        self.assertEqual(cipher._bulk(encrypted, True), cipher._scalar(encrypted, True))


class Crc64Tests(unittest.TestCase):
    def test_matches_bitwise_reference(self):
        for name in ("telltale.ttarch", "A/B/c.D3DTX", "x", "Minecraft: Story Mode"):
            self.assertEqual(crc64(name), _bitwise_crc64(name))

    def test_case_insensitive(self):
        self.assertEqual(crc64("MixedCase.d3dtx"), crc64("mixedcase.d3dtx"))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _files(self):
        rng = bytes((i * 37 + 11) & 0xFF for i in range(300_000))
        return [
            ("episode.d3dtx", b"texture" * 100),
            ("empty.bin", b""),
            ("one.bin", b"\x00"),
            ("big.dat", rng),  # forces several 64 KiB chunks
            ("nested/dir/thing.lua", b"print('hi')\n"),
        ]

    def _roundtrip(self, **options):
        files = self._files()
        path = self.tmp / "out.ttarch2"
        Archive.create(path, files, **options)
        with Archive.open(path, key=options.get("key")) as archive:
            self.assertEqual(sorted(archive.names()), sorted(n for n, _ in files))
            for name, data in files:
                self.assertEqual(archive.read(name), data, name)
        return path

    def test_encrypted_deflate_roundtrip(self):
        path = self._roundtrip()
        self.assertEqual(path.read_bytes()[:4], b"ECTT")  # "TTCE" stored reversed

    def test_plain_roundtrip(self):
        self._roundtrip(compress=False, encrypt=False)

    def test_compressed_unencrypted_roundtrip(self):
        self._roundtrip(encrypt=False)

    def test_header_layout(self):
        path = self._roundtrip(encrypt=False)
        raw = path.read_bytes()
        self.assertEqual(raw[:4], b"ZCTT")  # "TTCZ" stored reversed
        window, chunks = struct.unpack_from("<II", raw, 4)  # no codec field (uppercase)
        self.assertEqual(window, 0x10000)
        offsets = struct.unpack_from(f"<{chunks + 1}Q", raw, 12)
        self.assertEqual(offsets[0], 12 + 8 * (chunks + 1))  # absolute, like real archives
        self.assertEqual(list(offsets), sorted(offsets))
        self.assertEqual(offsets[-1], len(raw))

        # Decode the inner payload independently of the library.
        payload = b"".join(
            zlib.decompress(raw[offsets[i]:offsets[i + 1]], -15)
            for i in range(chunks)
        )
        self.assertEqual(payload[:4], b"4ATT")
        self.assertEqual(struct.unpack_from("<I", payload, 4)[0] % 0x10000, 0)
        # First entry: crc64 of the lowercased name, offset 0.
        crc, offset = struct.unpack_from("<QQ", payload, 12)
        self.assertEqual(offset, 0)
        self.assertEqual(crc, crc64("episode.d3dtx"))

    def test_names_survive_multiple_name_pages(self):
        files = [(f"dir{i:04d}/file{i:04d}.d3dtx", b"x") for i in range(4000)]
        path = self.tmp / "many.ttarch2"
        Archive.create(path, files)
        with Archive.open(path) as archive:
            self.assertEqual(sorted(archive.names()), sorted(n for n, _ in files))
            self.assertEqual(archive.read("dir3999/file3999.d3dtx"), b"x")

    def test_extract_rejects_path_traversal(self):
        path = self.tmp / "evil.ttarch2"
        Archive.create(path, [("../escape.txt", b"no")])
        with Archive.open(path) as archive:
            with self.assertRaises(ArchiveError):
                archive.extract_all(self.tmp / "out")

    def test_extract_writes_tree(self):
        path = self._roundtrip()
        with Archive.open(path) as archive:
            archive.extract_all(self.tmp / "x")
        self.assertEqual((self.tmp / "x" / "nested" / "dir" / "thing.lua").read_bytes(),
                         b"print('hi')\n")

    def test_unknown_container_is_rejected(self):
        path = self.tmp / "junk.bin"
        path.write_bytes(b"not an archive at all")
        with self.assertRaises(ArchiveError):
            Archive.open(path)

    def test_oodle_is_rejected_with_clear_error(self):
        path = self.tmp / "oodle.ttarch2"
        path.write_bytes(b"zCTT" + struct.pack("<III", 1, 0x10000, 1) + b"\0" * 16)
        with self.assertRaisesRegex(ArchiveError, "Oodle"):
            Archive.open(path)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.files = [("a.d3dtx", b"TEX"), ("b.lua", b"print(1)"),
                      ("sub/c.d3dtx", b"T")]
        self.archive = self.tmp / "ep.ttarch2"
        Archive.create(self.archive, self.files)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_filter_keeps_only_matches(self):
        code, out, _ = self._run(["list", str(self.archive), "--filter", "*.D3DTX"])
        self.assertEqual(code, 0)
        self.assertIn("a.d3dtx", out)
        self.assertIn("sub/c.d3dtx", out)
        self.assertNotIn("b.lua", out)
        self.assertIn("2 of 3 files", out)

    def test_extract_filter_writes_only_matches(self):
        target = self.tmp / "out"
        code, _, _ = self._run(["extract", str(self.archive), str(target),
                                "--filter", "*.d3dtx"])
        self.assertEqual(code, 0)
        self.assertEqual((target / "a.d3dtx").read_bytes(), b"TEX")
        self.assertEqual((target / "sub" / "c.d3dtx").read_bytes(), b"T")
        self.assertFalse((target / "b.lua").exists())

    def test_directory_batch_summarises_every_archive(self):
        archives = self.tmp / "archives"
        archives.mkdir()
        Archive.create(archives / "one.ttarch2", self.files)
        Archive.create(archives / "two.ttarch2", [("only.lua", b"x")])
        code, out, _ = self._run(["list", str(archives), "--filter", "*.lua"])
        self.assertEqual(code, 0)
        self.assertIn("one.ttarch2", out)
        self.assertIn("two.ttarch2", out)
        self.assertIn("2 of 4 files matched in 2 archives", out)

    def test_directory_batch_extracts_into_per_archive_folders(self):
        archives = self.tmp / "archives"
        archives.mkdir()
        Archive.create(archives / "one.ttarch2", self.files)
        Archive.create(archives / "two.ttarch2", [("only.lua", b"x")])
        target = self.tmp / "out"
        code, _, _ = self._run(["extract", str(archives), str(target),
                                "--filter", "*.lua"])
        self.assertEqual(code, 0)
        self.assertEqual((target / "one" / "b.lua").read_bytes(), b"print(1)")
        self.assertEqual((target / "two" / "only.lua").read_bytes(), b"x")
        self.assertFalse((target / "one" / "a.d3dtx").exists())

    def test_filter_matching_nothing_is_an_error(self):
        code, _, err = self._run(["extract", str(self.archive), str(self.tmp / "out"),
                                  "--filter", "*.nomatch"])
        self.assertEqual(code, 1)
        self.assertIn("no entries matched", err)


if __name__ == "__main__":
    unittest.main()
