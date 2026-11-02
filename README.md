# mcsm-sdk

Read, extract and rebuild **Minecraft: Story Mode** `.ttarch2` archives.

This is the foundation layer for modding: any texture, dialogue or script mod
ultimately has to go back into one of these archives. Nothing here modifies the
game's memory or executable, and no game files are included.

```
python -m mcsm list    episode.ttarch2
python -m mcsm extract episode.ttarch2 work/
# ...edit files in work/...
python -m mcsm pack    work/ modded.ttarch2 --like episode.ttarch2
```

Then point the game at `modded.ttarch2` in place of the original (keep a
backup; see *Caveats*).

## Install

Python 3.10+. No required third-party packages:

```
pip install -e .
```

`numpy` is optional and makes the cipher much faster on large archives
(measured here: ~15 MB/s vs ~0.6 MB/s in pure Python):

```
pip install -e ".[fast]"
```

## Library

```python
from mcsm import Archive

with Archive.open("episode.ttarch2") as archive:      # key defaults to the MCSM key
    print(archive.names()[:5])
    data = archive.read("textures/block.d3dtx")
    archive.extract_all("work")

# Rebuild, copying the source archive's version/key/encryption settings:
with Archive.open("episode.ttarch2") as source:
    settings = source.settings()
Archive.create("modded.ttarch2", [("textures/block.d3dtx", new_bytes)], **settings)
```

`Archive.create(path, files, key=..., version=4, compress=True, encrypt=True)`
takes `(name, bytes_or_path)` pairs. `pack_directory()` archives a folder tree.

## What is supported

| | Read | Write |
|---|---|---|
| TTA3 | yes | yes |
| TTA4 (this game build) | yes | yes |
| TTCN plain | yes | yes |
| TTCE encrypted + DEFLATE | yes | yes |
| TTCZ DEFLATE | yes | yes |
| Oodle (lowercase TTCe / TTCz, codec 1) | **no** — clear error | no |
| TTA2 | no | no |

Archives store no key; the default is the retail Minecraft: Story Mode key, a
55-byte binary blob (not the ASCII `Mcsm` some profile lists show), taken from
the public per-game key table in the Keyaku `ttarchext` fork. Pass `key=` or the
CLI `--key` for anything else.

## Caveats

- **Verified against the retail game.** All 174 `.ttarch2` archives in the
  installed game open (194,419 entries total), and a real 1.2 MB archive was
  extracted, repacked and re-extracted with every file byte-identical. The
  modified ("version 7") Blowfish is implemented from the published algorithm;
  the standard variant is checked against pycryptodome.
- Lua entries in this build are **bytecode**, not source: they start with
  Telltale's `\x1bLEnX` header. Extracting them gives a valid file, but editing
  means disassembling the bytecode, not editing text.
- File data is decoded lazily from a memory map, so extracting a multi-GB
  archive does not load it all into RAM. `create()` spools the inner payload to
  a temp file for the same reason.
- Entry names are ASCII. Extraction refuses names that would escape the output
  directory.
- The writer matches the observed retail layout: uppercase `TTCE`/`TTCZ` with no
  codec word, absolute chunk offsets, TTA4 entries, zero-padded final chunk.

## License and legal

Licensed under the **MIT** license; see `LICENSE`. The cipher is an independent
Python implementation of the published Blowfish algorithm and the functional
changes Telltale applied. Its P/S boxes are Bruce Schneier's public-domain
constants, and the container layout comes from public community documentation.
No C source from the reference tools is copied into this repository.

- Not affiliated with, endorsed by, or supported by Telltale Games, Mojang, or
  Microsoft. "Minecraft" and "Minecraft: Story Mode" are trademarks of their
  owners.
- No game code, assets, or archives are included or downloaded. You need your
  own copy of the game, and you are responsible for what you do with it.
- Do not redistribute extracted assets or repacked archives that contain them.
- The repository contains the archive decryption key so the tool can read files
  you already own. Rights holders: open an issue and the key will be removed.

## AI disclosure

This project was written with an AI coding assistant: **DeepSeek V4.1 Flash
Free**, running in OpenCode. The assistant produced the code, tests and
documentation under human direction. Format research, real-archive verification,
and all release decisions were directed and reviewed by the repository owner.
AI output can be wrong; treat the code as you would any unreviewed contribution
and run the tests before relying on it.

## Format references

- [Telltale-Modding-Group/ttarch-docs](https://github.com/Telltale-Modding-Group/ttarch-docs) — container/name-table layout
- [slankka/ttarchext2](https://github.com/slankka/ttarchext2) — rebuild path, Blowfish v7, chunk table
- [iMrShadow/TelltaleToolKit](https://github.com/iMrShadow/TelltaleToolKit) — reader and CRC64 definition, game profiles
- [Keyaku/ttarchext](https://github.com/Keyaku/ttarchext) fork — per-game binary key table (source of the MCSM key)
