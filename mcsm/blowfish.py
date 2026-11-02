# SPDX-License-Identifier: GPL-2.0-or-later
"""Telltale's modified Blowfish (archive "version 7" variant).

Differs from standard Blowfish in three places, all of which are needed to
decrypt .ttarch2 data:
  * S[0][118] is byte-swapped before the key schedule.
  * The round-key order is permuted at rounds 1-4 (P3 P4 P1 P2 instead of P1..P4).
  * Decryption ends with P[3] instead of P[1].
The key schedule itself still uses the standard cipher.
"""

from ._bf_tables import BFP, KS0, KS1, KS2, KS3

MASK = 0xFFFFFFFF

# Round-key index used at round i (encryption).
_ENC_ORDER = (0, 3, 4, 1, 2) + tuple(range(5, 16))
# Round-key index used at round i (decryption, i runs 17..2).
_DEC_ORDER = {4: 2, 3: 1, 2: 4}


def _bswap32(x: int) -> int:
    return int.from_bytes(x.to_bytes(4, "little"), "big")


class Blowfish:
    """Blowfish in ECB mode, 8-byte blocks, Telltale variant by default."""

    def __init__(self, key: bytes, modified: bool = True):
        if not key:
            raise ValueError("Blowfish key must not be empty")
        self._modified = modified
        self._s = [[c for c in KS0], [c for c in KS1], [c for c in KS2], [c for c in KS3]]
        if modified:
            self._s[0][118] = _bswap32(self._s[0][118])
        self._p = list(BFP)

        p = self._p
        j = 0
        for i in range(18):
            word = 0
            for _ in range(4):
                word = (word << 8) | key[j]
                j = (j + 1) % len(key)
            p[i] ^= word

        # Key schedule uses the unmodified cipher, even for the v7 variant.
        left = right = 0
        for i in range(0, 18, 2):
            left, right = self._encipher(left, right, modified=False)
            p[i], p[i + 1] = left, right
        for box in self._s:
            for j in range(0, 256, 2):
                left, right = self._encipher(left, right, modified=False)
                box[j], box[j + 1] = left, right

    def _f(self, x: int) -> int:
        s0, s1, s2, s3 = self._s
        y = (s0[x >> 24] + s1[(x >> 16) & 0xFF]) & MASK
        return ((y ^ s2[(x >> 8) & 0xFF]) + s3[x & 0xFF]) & MASK

    def _encipher(self, left: int, right: int, modified: bool = True) -> tuple[int, int]:
        p = self._p
        for i in range(16):
            left ^= p[_ENC_ORDER[i] if modified else i]
            right ^= self._f(left)
            left, right = right, left
        left, right = right, left
        right ^= p[16]
        left ^= p[17]
        return left & MASK, right & MASK

    def _decipher(self, left: int, right: int, modified: bool = True) -> tuple[int, int]:
        p = self._p
        for i in range(17, 1, -1):
            left ^= p[_DEC_ORDER.get(i, i) if modified else i]
            right ^= self._f(left)
            left, right = right, left
        left, right = right, left
        if modified:
            right ^= p[3]
            left ^= p[0]
        else:
            right ^= p[1]
            left ^= p[0]
        return left & MASK, right & MASK

    # -- byte-oriented ECB ------------------------------------------------

    def _run(self, data: bytes, decrypt: bool) -> bytes:
        full = len(data) - len(data) % 8
        if full == 0:
            return bytes(data)
        body = self._bulk(data[:full], decrypt) if _HAS_NUMPY else self._scalar(data[:full], decrypt)
        return body + bytes(data[full:])

    def encrypt(self, data: bytes) -> bytes:
        return self._run(data, decrypt=False)

    def decrypt(self, data: bytes) -> bytes:
        return self._run(data, decrypt=True)

    def _scalar(self, data: bytes, decrypt: bool) -> bytes:
        out = bytearray(data)
        for off in range(0, len(data), 8):
            left = int.from_bytes(data[off:off + 4], "little")
            right = int.from_bytes(data[off + 4:off + 8], "little")
            left, right = (self._decipher if decrypt else self._encipher)(left, right, self._modified)
            out[off:off + 4] = left.to_bytes(4, "little")
            out[off + 4:off + 8] = right.to_bytes(4, "little")
        return bytes(out)

    def _bulk(self, data: bytes, decrypt: bool) -> bytes:
        # ECB over independent blocks vectorises cleanly; ~40x the scalar speed.
        import numpy as np

        blocks = len(data) // 8
        words = np.frombuffer(data, dtype="<u4", count=2 * blocks)
        left = words[0::2].astype(np.uint32)
        right = words[1::2].astype(np.uint32)
        s0, s1, s2, s3 = (np.asarray(box, dtype=np.uint32) for box in self._s)
        p = np.asarray(self._p, dtype=np.uint32)

        def f(x):
            return (((s0[x >> 24] + s1[(x >> 16) & 0xFF]) ^ s2[(x >> 8) & 0xFF]) + s3[x & 0xFF])

        if not decrypt:
            order = _ENC_ORDER if self._modified else range(16)
            for i in range(16):
                left ^= p[order[i]]
                right ^= f(left)
                left, right = right, left
            left, right = right, left
            right ^= p[16]
            left ^= p[17]
        else:
            for i in range(17, 1, -1):
                left ^= p[_DEC_ORDER.get(i, i) if self._modified else i]
                right ^= f(left)
                left, right = right, left
            left, right = right, left
            right ^= p[3] if self._modified else p[1]
            left ^= p[0]

        out = np.empty(2 * blocks, dtype="<u4")
        out[0::2] = left
        out[1::2] = right
        return out.tobytes()


try:  # optional fast path
    import numpy  # noqa: F401

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False
