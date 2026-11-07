# SPDX-License-Identifier: MIT
"""Command line: list, extract and repack .ttarch2 archives.

    python -m mcsm list         game.ttarch2
    python -m mcsm extract      game.ttarch2  out_dir
    python -m mcsm pack         out_dir       mods.ttarch2 --like game.ttarch2

``list`` and ``extract`` also take a directory of archives, and ``--filter``
restricts entries to fnmatch globs (repeatable, case-insensitive).
"""

import argparse
import fnmatch
import sys
from pathlib import Path

from .ttarch import (
    DEFAULT_VERSION,
    MCSM_KEY,
    Archive,
    ArchiveError,
    pack_directory,
)

ARCHIVE_SUFFIXES = (".ttarch", ".ttarch2")


def _key(args):
    if args.key is not None:
        return args.key.encode("latin1")
    return MCSM_KEY


def _archives(path):
    path = Path(path)
    if not path.is_dir():
        return [path]
    found = sorted(p for p in path.iterdir()
                   if p.is_file() and p.suffix.lower() in ARCHIVE_SUFFIXES)
    if not found:
        raise ArchiveError(f"no .ttarch/.ttarch2 files in {path}")
    return found


def _matched(archive, patterns):
    if not patterns:
        return list(archive.entries)
    return [e for e in archive.entries
            if any(fnmatch.fnmatchcase(e.name.lower(), p.lower()) for p in patterns)]


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
    archives = _archives(args.archive)
    batch = Path(args.archive).is_dir()
    found = total = 0
    for path in archives:
        with Archive.open(path, key=_key(args)) as archive:
            matched = _matched(archive, args.filter)
            found += len(matched)
            total += len(archive.entries)
            if not batch:
                for entry in matched:
                    print(f"{entry.size:>12}  {entry.name}")
                count = (f"{len(matched)} of {len(archive.entries)}"
                         if args.filter else f"{len(archive.entries)}")
                print(f"\n{count} files, TTA{archive.version}, "
                      f"{archive.container or 'raw'}"
                      f"{', encrypted' if archive.encrypted else ''}")
            elif matched:
                print(f"{len(matched):>8} of {len(archive.entries):<8} files  "
                      f"{path.stat().st_size:>12,}  {path.name}")
    if batch:
        if args.filter:
            print(f"\n{found} of {total} files matched in {len(archives)} archives")
        else:
            print(f"\n{total} files in {len(archives)} archives")


def cmd_extract(args):
    archives = _archives(args.archive)
    batch = Path(args.archive).is_dir()
    output = Path(args.output)
    total = 0
    for path in archives:
        with Archive.open(path, key=_key(args)) as archive:
            names = {e.name for e in _matched(archive, args.filter)}
            destination = output / path.stem if batch else output
            # An empty set must stay empty: passing None would extract everything.
            written = archive.extract_all(destination, names) if names else 0
            total += written
            if written or not batch:
                print(f"{written:>8} files -> {destination}")
    if args.filter and not total:
        raise ArchiveError(f"no entries matched {', '.join(args.filter)}")


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

    p = sub.add_parser("list", help="list entries (a directory gives a summary)")
    common(p)
    p.add_argument("archive", help="archive file, or a directory of archives")
    p.add_argument("--filter", action="append", metavar="GLOB",
                   help="only matching entry names; repeatable")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("extract", help="extract entries (a directory of archives works too)")
    common(p)
    p.add_argument("archive", help="archive file, or a directory of archives")
    p.add_argument("output")
    p.add_argument("--filter", action="append", metavar="GLOB",
                   help="only matching entry names; repeatable")
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
