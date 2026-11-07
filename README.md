# mcsm-sdk

Read, extract and rebuild **Minecraft: Story Mode** `.ttarch2` archives.

Every texture, dialogue file and script the game loads lives in one of these
archives, so this is the layer any mod has to pass through. The tool only works
on archive files: it does not patch the executable or the running game, and it
ships no game data.

## Quick start

```
python -m mcsm list    MCSM_pc_Boot_data.ttarch2
python -m mcsm extract MCSM_pc_Boot_data.ttarch2 work/
# edit files in work/
python -m mcsm pack    work/ modded.ttarch2 --like MCSM_pc_Boot_data.ttarch2
```

`--like` copies the source archive's version, key and compression settings, so
the result matches what the game expects. Keep a copy of the original before you
replace anything. After `pip install`, `mcsm` works as a command too.

### Narrowing and batching

`--filter` takes a case-insensitive glob, repeatable, and works on both `list`
and `extract`:

```
# just the textures from one archive
mcsm extract MCSM_pc_Boot_txmesh.ttarch2 work/ --filter "*.d3dtx"

# which archives contain a given file? (no filter = one summary line each)
mcsm list "…/archives/" --filter "*.lua"

# pull the same subset out of every archive
mcsm extract "…/archives/" work/ --filter "*.d3dtx" --filter "*.d3dmesh"
```

Passing a **directory** to `list` prints a per-archive summary instead of every
entry, because a full install has ~194,000 files. Batch `extract` writes each
archive into its own subfolder (`work/<archive name>/…`), so identical names in
different episodes cannot collide. A filter that matches nothing exits with an
error instead of silently writing an empty tree.

## Install

Python 3.10 or newer. Nothing else is required:

```
pip install .
```

The cipher has an optional numpy path that is roughly 25x faster (measured
~15 MB/s vs ~0.6 MB/s). Use it for large archives:

```
pip install ".[fast]"
```

For development, use `pip install -e .` and run the tests with
`python -m unittest discover -s tests`.

## Library

```python
from mcsm import Archive

with Archive.open("MCSM_pc_Boot_data.ttarch2") as archive:
    print(archive.names())
    data = archive.read("boot.lua")
    archive.extract_all("work")

# Repack with exactly the source archive's settings.
with Archive.open("MCSM_pc_Boot_data.ttarch2") as source:
    settings = source.settings()
Archive.create("modded.ttarch2", [("boot.lua", new_bytes)], **settings)
```

`Archive.create(path, files, key=..., version=4, compress=True, encrypt=True)`
takes `(name, bytes_or_path)` pairs; `pack_directory()` archives a whole tree.

## What works

| Container | Read | Write | Notes |
|---|---|---|---|
| TTCN | yes | yes | uncompressed payload |
| TTCE | yes | yes | Blowfish v7 + DEFLATE |
| TTCZ | yes | yes | DEFLATE, no encryption |
| TTCe / TTCz | no | no | lowercase tags carry a codec field; Oodle is rejected |
| TTA3 / TTA4 | yes | yes | inner index, both layouts |

174 retail archives from the current build open (194,419 entries), and a 1.2 MB
archive survives extract → repack → extract byte for byte.

The key is also handled: this build uses a 55-byte binary Blowfish key, not the
ASCII `Mcsm` some profile lists show. It is embedded as the default, taken from
the public per-game table in the Keyaku `ttarchext` fork; pass `key=` or the CLI
`--key` to override it.

Lua entries start with Telltale's `\x1bLEnX` header, which means they are
compiled **bytecode**, not text. `extract` gives you a valid file, but editing
them means disassembling and reassembling bytecode, not opening a text editor.

## Verification and limits

- All 174 `.ttarch2` files in the installed game open without error, both
  individually and as one directory listing (194,419 entries).
- A filtered extract of a retail archive produced 21 files byte-identical to a
  full extraction of the same archive, and a two-archive batch extract matched
  `Archive.read()` for every file.
- The v7 cipher is implemented from the published algorithm; the standard
  variant is tested against pycryptodome and the v7 variant has a locked known
  answer test.
- Reading is lazy (`mmap`), so multi-GB archives do not load into RAM; writing
  spools the payload to a temp file.
- Entry names are ASCII, and extraction refuses names that would escape the
  output directory.
- Not supported: Oodle compression, TTA2 archives, and anything inside the game
  runtime (no scene loading, no hooks, no camera control).

## License and legal

MIT; see `LICENSE`.

The cipher is an independent Python implementation of the published Blowfish
algorithm and the functional changes Telltale applied. Its P/S boxes are Bruce
Schneier's public-domain constants, and the container layout comes from public
community documentation. No C source from the reference tools is copied here.

- Not affiliated with, endorsed by, or supported by Telltale Games, Mojang, or
  Microsoft. "Minecraft" and "Minecraft: Story Mode" are trademarks of their
  owners.
- No game code, assets or archives are included. You need your own copy of the
  game, and you are responsible for what you do with it.
- Do not redistribute extracted assets or repacked archives that contain them.
- The repository embeds the archive key so the tool can read files you already
  own. Rights holders: open an issue and it will be removed.

## AI disclosure

Written with an AI coding assistant: **DeepSeek V4.1 Flash Free** in OpenCode.
The assistant produced the code, tests and documentation under human direction;
format research, verification against retail files and release decisions were
directed and reviewed by the repository owner. AI output can be wrong — treat it
like any unreviewed contribution and run the tests.

## References

- [ttarch-docs](https://github.com/Telltale-Modding-Group/ttarch-docs) — container and name-table layout
- [slankka/ttarchext2](https://github.com/slankka/ttarchext2) — rebuild path, Blowfish v7, chunk table
- [TelltaleToolKit](https://github.com/iMrShadow/TelltaleToolKit) — reader, CRC64, game profiles
- [Keyaku/ttarchext](https://github.com/Keyaku/ttarchext) — per-game key table
