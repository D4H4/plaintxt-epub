#!/usr/bin/env python3
"""Undersök rubrikformat i korpusens detekteringsmissar + Red Storm Rising."""
import sys, os, re
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from converter import TextProcessor

ROOT = "G:\\Övriga datorer\\DELL\\Documents\\_E-books\\ebook.-.700.Science.Fiction.and.Fantasy.and.Classic.books"
FILES = [
    "Orwell, George\\1984.txt",
    "Asimov, Isaac\\Foundation and Empire.txt",
    "McCaffrey, Anne\\DragonRider.txt",
    "Clancy, Tom\\Red Storm Rising.txt",
]

for rel in FILES:
    path = os.path.join(ROOT, rel)
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    cleaned = TextProcessor.clean_text(raw)
    lines = raw.split("\n")
    print("=" * 60)
    print(rel, "| rader:", len(lines))
    print("--- Forsta 15 icke-tomma raderna (repr) ---")
    shown = 0
    for l in lines:
        if l.strip():
            print("   ", repr(l[:70]))
            shown += 1
            if shown >= 15:
                break
    # Kandidatrubriker i RAA texten: korta rader omgivna av blankrad
    print("--- Kapitel/part-liknande rader i raa texten (max 12) ---")
    hits = 0
    n = len(lines)
    for i, l in enumerate(lines):
        s = l.strip()
        if not s or len(s) > 60:
            continue
        if re.match(r"(?i)^(chapter|part|book)\b|^[\dIVXLC]+\s*$|^\d+\s", s):
            pb = i == 0 or not lines[i-1].strip()
            nb = i == n-1 or not lines[i+1].strip()
            print("    rad", i, "| blank fore:", pb, "| blank efter:", nb, "|", repr(l[:60]))
            hits += 1
            if hits >= 12:
                break
    if hits == 0:
        print("    (inga)")
    # Vad detekteringen ger pa cleaned
    ch = TextProcessor.detect_chapters(cleaned)
    print("--- detect_chapters pa cleaned:", len(ch), "kapitel ---")
    titles = [t for t, _ in ch]
    for t in titles[:10]:
        print("   ", repr(t[:60]))
    if len(titles) > 20:
        c = Counter(titles)
        print("    Mest upprepade titlar:", c.most_common(5))
    print()
