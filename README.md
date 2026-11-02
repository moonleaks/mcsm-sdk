# mcsm-sdk

A Python tool for reading, extracting, and rebuilding **Minecraft: Story Mode** `.ttarch2` archives.

Minecraft: Story Mode stores most of its game files, including textures, dialogue, and scripts, inside these archives. This makes them an important part of the modding process.

`mcsm-sdk` lets you open these archives, extract their contents, make changes, and pack everything back into a new archive. It only works with archive files and does not modify the game executable or interact with the game while it is running. No game files or assets are included.

## Quick start

```bash
python -m mcsm list MCSM_pc_Boot_data.ttarch2
python -m mcsm extract MCSM_pc_Boot_data.ttarch2 work/

# Make your changes inside the work/ folder

python -m mcsm pack work/ modded.ttarch2 --like MCSM_pc_Boot_data.ttarch2
```

The `--like` option uses the original archive's version, encryption key, and compression settings. This helps make sure the rebuilt archive uses the same format as the original.

Always keep a backup of the original archive before replacing it.

Once installed, you can also use `mcsm` directly instead of running it through Python.

## Installation

You'll need Python 3.10 or newer. There are no required third-party dependencies.

```bash
pip install .
```

For faster encryption and decryption, you can install the optional NumPy dependency:

```bash
pip install ".[fast]"
```

The NumPy implementation is roughly 25 times faster in testing, reaching around 15 MB/s compared to 0.6 MB/s without it. This is especially useful when working with larger archives.

For development, install the package in editable mode and run the test suite:

```bash
pip install -e .
python -m unittest discover -s tests
```

## Using the library

You can also use `mcsm-sdk` directly in your own Python projects.

```python
from mcsm import Archive

with Archive.open("MCSM_pc_Boot_data.ttarch2") as archive:
    print(archive.names())
    data = archive.read("boot.lua")
    archive.extract_all("work")

# Reuse the original archive's settings when rebuilding.
with Archive.open("MCSM_pc_Boot_data.ttarch2") as source:
    settings = source.settings()

Archive.create("modded.ttarch2", [("boot.lua", new_bytes)], **settings)
```

`Archive.create()` accepts a list of `(name, bytes_or_path)` pairs. You can also use `pack_directory()` to package an entire directory into an archive.

The method supports the following options:

```python
Archive.create(
    path,
    files,
    key=...,
    version=4,
    compress=True,
    encrypt=True
)
```

## Supported formats

The tool currently supports the following archive types:

| Container | Read | Write | Notes |
|---|---|---|---|
| TTCN | Yes | Yes | Uncompressed payload |
| TTCE | Yes | Yes | Blowfish v7 + DEFLATE |
| TTCZ | Yes | Yes | DEFLATE, no encryption |
| TTCe / TTCz | No | No | Lowercase tags use a codec field; Oodle is not supported |
| TTA3 / TTA4 | Yes | Yes | Supports both inner index layouts |

### Testing and compatibility

The tool has been tested against 174 retail archives from the current game build, containing a total of 194,419 entries.

A separate 1.2 MB archive was also tested through a complete extract, rebuild, and extraction cycle. All files matched byte for byte.

The archive key is included by default. The current game build uses a 55-byte binary Blowfish key rather than the ASCII `Mcsm` value listed in some profiles.

The default key comes from the public per-game key table in the Keyaku `ttarchext` fork. You can provide a different key using `key=` in Python or `--key` from the command line.

### Lua files

One important thing to know is that Lua files inside these archives are not ordinary text files.

They start with Telltale's `\x1bLEnX` header, which identifies them as compiled bytecode. You can extract them normally, but editing their contents requires disassembling and reassembling the bytecode rather than opening them in a regular text editor.

## Verification and limitations

Some additional details about how the tool works:

- All 174 `.ttarch2` archives in the installed game have been opened successfully.
- The Blowfish v7 cipher is implemented using the published algorithm. The standard variant is tested against PyCryptodome, and the v7 variant has a fixed known-answer test.
- Archive reading uses `mmap`, so even multi-gigabyte archives don't need to be loaded entirely into memory.
- Archive writing uses a temporary file to spool the payload.
- Entry names are ASCII.
- Extraction includes path checks to prevent files from being written outside the selected output directory.

### Not currently supported

- Oodle compression.
- TTA2 archives.
- Game runtime modifications.
- Scene loading, game hooks, or camera controls.

The project is focused on archive handling rather than modifying or interacting with the running game.

## License and legal

The Blowfish implementation is written independently in Python using the published algorithm and the modifications made by Telltale.

The P/S boxes use Bruce Schneier's public-domain constants, and the archive format implementation is based on publicly available community documentation. No C source code from the reference tools has been copied into this project.

A few things to keep in mind:

- This project is not affiliated with, endorsed by, or supported by Telltale Games, Mojang, or Microsoft.
- Minecraft and Minecraft: Story Mode are trademarks of their respective owners.
- No game code, assets, or archives are included. You must own your own copy of the game.
- You are responsible for how you use the tool and any files you create with it.
- Please do not redistribute extracted game assets or rebuilt archives containing those assets.
- The repository includes the archive key so the tool can access archives you already own. Rights holders can open an issue to request its removal.

## AI disclosure

This project was developed with help from **DeepSeek V4.1 Flash Free** through OpenCode.

The AI assistant helped produce the code, tests, and documentation under human direction. Research into the archive format, testing against retail game files, and final release decisions were handled and reviewed by the repository owner.

AI-generated code and documentation can contain mistakes, so users are encouraged to review the implementation and run the included tests.

## References

The project builds on publicly available research and community documentation:

- [ttarch-docs](https://github.com/Telltale-Modding-Group/ttarch-docs) - Archive container and name-table documentation.
- [slankka/ttarchext2](https://github.com/slankka/ttarchext2) - Rebuilding process, Blowfish v7, and chunk table research.
- [TelltaleToolKit](https://github.com/iMrShadow/TelltaleToolKit) - Archive reader, CRC64, and game profiles.
- [Keyaku/ttarchext](https://github.com/Keyaku/ttarchext) - Public per-game archive key table.
