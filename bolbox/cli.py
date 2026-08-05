"""Command line entry points.

    python -m bolbox check   data/compositions/theka-tintal.txt
    python -m bolbox render  data/compositions/theka-tintal.txt -o theka.mid
    python -m bolbox show    data/compositions/theka-tintal.txt
    python -m bolbox serve

`check` exists so a composition can be validated without producing anything --
useful while typing a corpus, and the obvious thing to run in CI over
data/compositions/ once there are files worth guarding.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import BolboxError, ParseError
from .format import parse_file
from .grid import grid
from .lexicon import Lexicon
from .midi import write
from .vocab import Vocabulary


def _load() -> Lexicon:
    return Lexicon.load(vocab=Vocabulary.load())


def _report(exc: BolboxError) -> int:
    if isinstance(exc, ParseError):
        print(f"error: {exc}", file=sys.stderr)
    else:
        print(f"error: {exc}", file=sys.stderr)
    return 1


def cmd_check(args: argparse.Namespace) -> int:
    lexicon = _load()
    failures = 0
    for path in args.paths:
        try:
            composition = parse_file(path, lexicon=lexicon)
            pattern = grid(composition, lexicon=lexicon)
        except BolboxError as exc:
            print(f"{path}: FAIL", file=sys.stderr)
            _report(exc)
            failures += 1
            continue
        print(
            f"{path}: ok -- {composition.tal.name}, "
            f"{len(composition.avartans)} avartan(s), "
            f"{len(pattern.events)} strokes, lay {pattern.lay:g}"
        )
    return 1 if failures else 0


def cmd_render(args: argparse.Namespace) -> int:
    lexicon = _load()
    try:
        composition = parse_file(args.path, lexicon=lexicon)
        pattern = grid(composition, lexicon=lexicon, lay=args.lay)
    except BolboxError as exc:
        return _report(exc)

    out = Path(args.output or Path(args.path).with_suffix(".mid"))
    write(pattern, out)
    print(f"wrote {out} -- {len(pattern.events)} strokes, {pattern.duration_seconds:.2f}s")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Print the grid as text. The fastest way to see what a file actually does."""
    lexicon = _load()
    try:
        composition = parse_file(args.path, lexicon=lexicon)
        pattern = grid(composition, lexicon=lexicon, lay=args.lay)
    except BolboxError as exc:
        return _report(exc)

    print(f"{composition.title or Path(args.path).stem}")
    print(f"{pattern.tal}, {pattern.cycle_matras} matras, lay {pattern.lay:g}")
    print()
    for pos, group in pattern.simultaneous_groups():
        matra = int(pos) % pattern.cycle_matras
        within = pos - int(pos)
        marker = "|" if within == 0 else " "
        strokes = "+".join(e.stroke for e in group)
        bol = group[0].source_bol
        offset = f"+{within}" if within else ""
        print(f"{marker} {matra:>2}{offset:<6} {strokes:<12} {bol}")
    return 0


def cmd_serve(_args: argparse.Namespace) -> int:
    from .server import main

    main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bolbox", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate composition files")
    check.add_argument("paths", nargs="+")
    check.set_defaults(func=cmd_check)

    render = sub.add_parser("render", help="write a .mid file")
    render.add_argument("path")
    render.add_argument("-o", "--output")
    render.add_argument("--lay", type=float, default=None)
    render.set_defaults(func=cmd_render)

    show = sub.add_parser("show", help="print the grid as text")
    show.add_argument("path")
    show.add_argument("--lay", type=float, default=None)
    show.set_defaults(func=cmd_show)

    serve = sub.add_parser("serve", help="run the local server")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
