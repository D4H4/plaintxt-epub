#!/usr/bin/env python3
"""Fas 0.5 korpusdiagnostik: kör clean_text + detect_chapters över hela
Drive-samlingen och skriv corpus_results.csv + aggregerad rapport på stdout."""
import sys, os, csv, time, statistics
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from converter import TextProcessor

ROOT = "G:\\Övriga datorer\\DELL\\Documents\\_E-books"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_results.csv")

def nonws(t):
    return sum(1 for c in t if not c.isspace())

rows = []
t_start = time.time()
files = []
for root, dirs, names in os.walk(ROOT):
    for n in names:
        if n.lower().endswith(".txt"):
            files.append(os.path.join(root, n))
files.sort()
print("Filer:", len(files), flush=True)

for i, path in enumerate(files):
    rel = os.path.relpath(path, ROOT)
    row = {"file": rel, "kb": 0, "chapters": "", "coverage": "", "sec": "", "error": ""}
    t0 = time.time()
    try:
        row["kb"] = os.path.getsize(path) // 1024
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        cleaned = TextProcessor.clean_text(raw)
        chapters = TextProcessor.detect_chapters(cleaned)
        cc = nonws(cleaned)
        ch_cc = sum(nonws(b) for _, b in chapters)
        row["chapters"] = len(chapters)
        row["coverage"] = round(ch_cc / cc, 4) if cc else 1.0
        row["sec"] = round(time.time() - t0, 2)
    except Exception as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)[:120]
    rows.append(row)
    if (i + 1) % 50 == 0:
        print("...", i + 1, "klara,", round(time.time() - t_start), "s", flush=True)

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["file", "kb", "chapters", "coverage", "sec", "error"])
    w.writeheader()
    w.writerows(rows)

ok = [r for r in rows if not r["error"]]
err = [r for r in rows if r["error"]]
ns = sorted(r["chapters"] for r in ok)
def pct(p):
    return ns[min(len(ns) - 1, int(len(ns) * p))]

print()
print("=== KORPUSRAPPORT ===")
print("Totalt:", len(rows), "| ok:", len(ok), "| fel:", len(err))
print("Total tid:", round(time.time() - t_start), "s")
if ok:
    print("Kapitelantal: min", ns[0], "| p25", pct(0.25), "| median", pct(0.5),
          "| p75", pct(0.75), "| p95", pct(0.95), "| max", ns[-1])
    one = [r for r in ok if r["chapters"] == 1]
    many = sorted(ok, key=lambda r: -r["chapters"])[:15]
    lowcov = [r for r in ok if r["coverage"] < 0.95]
    slow = sorted(ok, key=lambda r: -r["sec"])[:5]
    print()
    print("Bara 1 kapitel (ingen detektering):", len(one))
    for r in one[:10]:
        print("   ", r["file"], "(", r["kb"], "KB )")
    print()
    print("Topp 15 flest kapitel (misstänkt explosion):")
    for r in many:
        print("   ", r["chapters"], "st |", r["kb"], "KB |", r["file"])
    print()
    print("Coverage < 95 % (text hamnar utanfor kapitel):", len(lowcov))
    for r in sorted(lowcov, key=lambda r: r["coverage"])[:10]:
        print("   ", r["coverage"], "|", r["file"])
    print()
    print("Langsammast:")
    for r in slow:
        print("   ", r["sec"], "s |", r["kb"], "KB |", r["file"])
if err:
    print()
    print("FEL:")
    for r in err[:15]:
        print("   ", r["file"], "->", r["error"])
