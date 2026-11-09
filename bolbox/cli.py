"""Command line entry points.

    python -m bolbox check   data/compositions/theka-tintal.txt
    python -m bolbox render  data/compositions/theka-tintal.txt -o theka.mid
    python -m bolbox show    data/compositions/theka-tintal.txt
    python -m bolbox serve
    python -m bolbox label   [--import DIR]   # label recordings in the browser
    python -m bolbox dataset [--manifest OUT.jsonl]

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
        head = group[0]
        # `din` and `din@full` are different sounds -- same rule as
        # web/src/grid-labels.ts, so `show` does not lie about which was struck.
        bol = f"{head.source_bol}@{head.variant}" if head.variant else head.source_bol
        offset = f"+{within}" if within else ""
        print(f"{marker} {matra:>2}{offset:<6} {strokes:<12} {bol}")
    return 0


def _store():
    from .recordings import RecordingStore
    from .server import RECORDINGS_DIR

    return RecordingStore(RECORDINGS_DIR)


def cmd_label(args: argparse.Namespace) -> int:
    """Import recordings (optional), then serve the labeling page."""
    if args.import_dir:
        from .dataset import import_directory

        directory = Path(args.import_dir).expanduser()
        if not directory.is_dir():
            print(f"error: {directory} is not a directory", file=sys.stderr)
            return 1
        result = import_directory(directory, _store(), _load(), speaker=args.speaker)
        labelled = sum(1 for m in result.imported if m.labelled)
        print(
            f"imported {len(result.imported)} take(s) "
            f"({labelled} with a label from a matching .txt), "
            f"{len(result.duplicates)} already imported, {len(result.failed)} failed"
        )
        for name, why in result.failed:
            print(f"  failed: {name}: {why}", file=sys.stderr)
    if args.no_serve:
        return 0
    print(f"labeling page: http://127.0.0.1:{args.port}/label")
    from .server import main

    main(port=args.port)
    return 0


def cmd_dataset(args: argparse.Namespace) -> int:
    from .dataset import coverage, format_coverage, manifest_rows, write_manifest

    lexicon = _load()
    store = _store()
    print(format_coverage(coverage(store, lexicon), lexicon))
    if args.manifest:
        rows = manifest_rows(store, lexicon)
        write_manifest(rows, Path(args.manifest))
        print(f"\nwrote {len(rows)} row(s) to {args.manifest}")
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

    label = sub.add_parser("label", help="label recordings in the browser")
    label.add_argument("--import", dest="import_dir", metavar="DIR",
                       help="copy audio files from DIR into data/recordings first")
    label.add_argument("--speaker", default="self",
                       help="speaker tag for imported takes (default: self)")
    label.add_argument("--port", type=int, default=8000)
    label.add_argument("--no-serve", action="store_true",
                       help="import only, do not start the server")
    label.set_defaults(func=cmd_label)

    dataset = sub.add_parser("dataset", help="coverage report and training manifest")
    dataset.add_argument("--manifest", metavar="OUT",
                         help="write one JSON line per trainable take")
    dataset.set_defaults(func=cmd_dataset)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
