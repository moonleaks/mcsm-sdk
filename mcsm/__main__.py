# SPDX-License-Identifier: MIT
"""Command line: list, extract and repack .ttarch2 archives.

    python -m mcsm list         game.ttarch2
    python -m mcsm extract      game.ttarch2  out_dir
    python -m mcsm pack         out_dir       mods.ttarch2 --like game.ttarch2
"""

import argparse
import sys

from .ttarch import (
    DEFAULT_VERSION,
    MCSM_KEY,
    Archive,
    ArchiveError,
    pack_directory,
)


def _key(args):
    if args.key is not None:
        return args.key.encode("latin1")
    return MCSM_KEY


def _options(args):
    options = {
        "key": _key(args),
        "version": DEFAULT_VERSION,
        "compress": True,
        "encrypt": True,
    }
    if args.like:
        with Archive.open(args.like, key=options["key"]) as source:
            options.update(source.settings())
    if args.plain:
        options.update(compress=False, encrypt=False)
    return options


def cmd_list(args):
    with Archive.open(args.archive, key=_key(args)) as archive:
        for entry in archive.entries:
            print(f"{entry.size:>12}  {entry.name}")
        print(f"\n{len(archive.entries)} files, TTA{archive.version}, "
              f"{archive.container or 'raw'}"
              f"{', encrypted' if archive.encrypted else ''}")


def cmd_extract(args):
    with Archive.open(args.archive, key=_key(args)) as archive:
        archive.extract_all(args.output)
        print(f"extracted {len(archive.entries)} files to {args.output}")


def cmd_pack(args):
    archive = pack_directory(args.directory, args.archive, **_options(args))
    try:
        print(f"wrote {len(archive.entries)} files to {args.archive}")
    finally:
        archive.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mcsm", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--key", help="override the embedded Blowfish key")

    p = sub.add_parser("list", help="list entries")
    common(p)
    p.add_argument("archive")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("extract", help="extract every entry")
    common(p)
    p.add_argument("archive")
    p.add_argument("output")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("pack", help="build an archive from a directory")
    common(p)
    p.add_argument("directory")
    p.add_argument("archive")
    p.add_argument("--like", help="copy version/key/compression from this archive")
    p.add_argument("--plain", action="store_true", help="write an unencrypted TTCN")
    p.set_defaults(func=cmd_pack)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ArchiveError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
