#!/usr/bin/env python3
"""PlainTXT-EPUB CLI — headless konvertering utan GUI-beroenden (Fas 2).

Ateranvander TextProcessor/EPUBBuilder ur converter.py. Singel:

    python cli.py bok.txt --title "Titeln" --author "Namn" -o ut/

Batch (filer och/eller mappar, mappar soks rekursivt efter .txt):

    python cli.py "C:\\E-books" -o ut/

Batchregler speglar GUI:t: skrapfiler < 5 KB hoppas over, titel gissas
fran filnamnet, forfattare fran filhuvudet, omslag med samma filnamnsstam
hittas automatiskt. Strukturvarningar (stor fil utan kapitelstruktur)
skrivs till stderr. Exitkod 0 = allt konverterat, 1 = minst ett fel."""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from converter import (  # noqa: E402
    HAS_EPUB, TextProcessor, EPUBBuilder, find_cover, _unique_path)

JUNK_LIMIT = 5 * 1024  # samma grans som GUI-batchens skrapfilter


def expand_inputs(paths):
    """Filer + mappar (rekursivt) -> sorterad lista .txt-filer."""
    result = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for name in names:
                    if name.lower().endswith(".txt"):
                        result.append(os.path.join(root, name))
        elif p.lower().endswith(".txt"):
            result.append(p)
        else:
            print("hoppar over (inte .txt):", p, file=sys.stderr)
    return sorted(dict.fromkeys(result))


def guess_title(path):
    return re.sub(r"[_\-]+", " ", Path(path).stem).strip().title()


def safe_filename(title):
    return (re.sub(r"[^\w\s\-]", "", title).strip().replace(" ", "_")
            or "book")


def convert_one(path, out_dir, args, batch):
    """Konvertera en fil. Returnerar (status, meddelande)."""
    if batch and os.path.getsize(path) < JUNK_LIMIT:
        return "skipped", "skrapfil (< 5 KB)"

    raw = TextProcessor.read_text_file(path)
    text = raw if args.no_clean else TextProcessor.clean_text(raw)
    if args.no_chapters:
        chapters = [("Content", text.strip())]
        warning = None
    else:
        chapters = TextProcessor.detect_chapters(text)
        warning = TextProcessor.structure_warning(raw, len(chapters))

    title = (args.title if not batch and args.title else guess_title(path))
    author = args.author if not batch and args.author else ""
    if not author:
        author = TextProcessor.suggest_author(raw[:4000]) or "Unknown Author"
    cover = (args.cover if not batch and args.cover else find_cover(path))

    out_path = _unique_path(out_dir, safe_filename(title) + ".epub")
    EPUBBuilder.build(
        title=title,
        author=author,
        language=args.language,
        chapters=chapters,
        cover_path=cover or None,
        output_path=out_path,
    )
    msg = "{} kapitel -> {}".format(len(chapters), out_path)
    if warning:
        return "warned", msg + "\n  VARNING: " + warning
    return "done", msg


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="plaintxt-epub",
        description="Konvertera .txt till EPUB (headless).")
    ap.add_argument("paths", nargs="+",
                    help=".txt-filer och/eller mappar (mappar soks rekursivt)")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="utmapp for epub-filerna (standard: kallfilens mapp)")
    ap.add_argument("--title", help="boktitel (bara vid enstaka fil)")
    ap.add_argument("--author", help="forfattare (bara vid enstaka fil)")
    ap.add_argument("--language", default="en", help="sprakkod (standard: en)")
    ap.add_argument("--cover", help="sokvag till omslagsbild (enstaka fil)")
    ap.add_argument("--no-clean", action="store_true",
                    help="hoppa over textstadningen (radjoin, boilerplate)")
    ap.add_argument("--no-chapters", action="store_true",
                    help="ingen kapiteldetektering — allt i ett kapitel")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="skriv bara varningar och fel")
    args = ap.parse_args(argv)

    if not HAS_EPUB:
        print("FEL: ebooklib saknas. Installera: pip install ebooklib",
              file=sys.stderr)
        return 2

    files = expand_inputs(args.paths)
    if not files:
        print("FEL: inga .txt-filer hittades.", file=sys.stderr)
        return 2
    batch = len(files) > 1
    if batch and (args.title or args.author or args.cover):
        print("FEL: --title/--author/--cover galler bara enstaka fil.",
              file=sys.stderr)
        return 2
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    counts = {"done": 0, "warned": 0, "skipped": 0, "failed": 0}
    for i, path in enumerate(files, 1):
        prefix = "[{}/{}] {}".format(i, len(files), Path(path).name)
        out_dir = args.output_dir or str(Path(path).parent)
        try:
            status, msg = convert_one(path, out_dir, args, batch)
        except Exception as exc:
            status, msg = "failed", type(exc).__name__ + ": " + str(exc)
        counts[status] += 1
        line = prefix + ": " + msg
        if status in ("warned", "failed"):
            print(line, file=sys.stderr)
        elif not args.quiet:
            print(line)

    if batch and not args.quiet:
        print("Klart: {done} ok, {warned} med varning, {skipped} overhoppade, "
              "{failed} fel".format(**counts))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
