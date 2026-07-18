#!/usr/bin/env python3
"""Fas 0.5: skriv kapitelfacit-UTKAST fran epubarnas rubriker (h1–h6) —
`<bok>.chapters-draft.txt` i eval/golden/, en rubrik per rad med taggprefix.
Utkastet kurateras manuellt till `<bok>.chapters-facit.txt` (taggprefixen
tas bort, fram-/baksidesmatter stryks). Kor: python eval/make_chapter_facit.py"""
import os
import glob
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from epub_extract import extract

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")

for epub_path in sorted(glob.glob(os.path.join(GOLDEN, "*.epub"))):
    stem = os.path.splitext(os.path.basename(epub_path))[0]
    headings, _ = extract(epub_path)
    out = os.path.join(GOLDEN, stem + ".chapters-draft.txt")
    with open(out, "w", encoding="utf-8") as f:
        for tag, text in headings:
            f.write(tag + "\t" + text + "\n")
    print(stem + ":", len(headings), "rubriker ->", os.path.basename(out))
