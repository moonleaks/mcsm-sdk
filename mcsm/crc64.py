# SPDX-License-Identifier: GPL-2.0-or-later
"""CRC64 (ECMA-182 polynomial, init 0, no final xor) as used for ttarch names."""

MASK64 = (1 << 64) - 1
_POLY = 0x42F0E1EBA9EA3693


def _table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        crc = i << 56
        for _ in range(8):
            crc = ((crc << 1) ^ _POLY) if crc & (1 << 63) else (crc << 1)
        table.append(crc & MASK64)
    return tuple(table)


_TABLE = _table()


def crc64(name: str) -> int:
    """Hash of the lowercased name; this is what archive entries store."""
    crc = 0
    for byte in name.lower().encode("ascii"):
        crc = ((crc << 8) & MASK64) ^ _TABLE[((crc >> 56) ^ byte) & 0xFF]
    return crc
