#!/usr/bin/env python3
"""Fas 0.5 matskript kapitel: precision/recall for detect_chapters mot facit.

Kor pipeline (clean_text + detect_chapters) pa varje `eval/golden/<bok>.txt`
som har ett `<bok>.chapters-facit.txt`, matchar detekterade rubriker mot
facit i lasordning (LCS pa tolerant-normaliserade titlar) och rapporterar
P/R/F1 per bok + mikroaggregat. Kor: python eval/eval_chapters.py [-v]

Traff = normaliserade titlar lika, ELLER prediktionens tokens ar ett prefix
av facit-tokens (epub-facit slar ihop rubrik + undertitel, t.ex. Dracula
"CHAPTER I JONATHAN HARKER'S JOURNAL" — att hitta brytpunkten "CHAPTER I"
racker; tokenniva sa "chapter i" inte matchar "chapter ii ...")."""
import os
import re
import sys
import glob
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
from converter import TextProcessor

GOLDEN = os.path.join(_HERE, "golden")
# Syntetiska titlar fran detect_chapters (inte detekterade rubriker) —
# raknas inte som prediktioner
SYNTHETIC = frozenset(["Introduction", "Content"])


def predicted_titles(txt_path):
    raw = TextProcessor.read_text_file(txt_path)
    cleaned = TextProcessor.clean_text(raw)
    chapters = TextProcessor.detect_chapters(cleaned)
    titles = [t for t, _ in chapters]
    if titles and titles[0] == "Introduction":
        titles = titles[1:]
    return [t for t in titles if t not in SYNTHETIC]


def title_tokens(s):
    """Tolerant normalisering (lardom RSR: interpunktion varierar i kallorna)
    — casefold, behall bara alfanumeriska tokens."""
    s = unicodedata.normalize("NFKC", s).casefold()
    return tuple(re.findall(r"[^\W_]+", s, re.UNICODE))


def title_match(facit_toks, pred_toks):
    if not pred_toks:
        return False
    return facit_toks[: len(pred_toks)] == pred_toks


def lcs_align(facit_n, pred_n):
    """In-order-alignment (LCS) med prefixtolerant likhet.
    Returnerar (traffar, traffade facit-index, traffade pred-index)."""
    nf, np_ = len(facit_n), len(pred_n)
    dp = [[0] * (np_ + 1) for _ in range(nf + 1)]
    for i in range(nf - 1, -1, -1):
        row, below = dp[i], dp[i + 1]
        for j in range(np_ - 1, -1, -1):
            if title_match(facit_n[i], pred_n[j]):
                row[j] = 1 + below[j + 1]
            else:
                row[j] = max(below[j], row[j + 1])
    hit_f, hit_p = set(), set()
    i = j = 0
    while i < nf and j < np_:
        if title_match(facit_n[i], pred_n[j]) and dp[i][j] == 1 + dp[i + 1][j + 1]:
            hit_f.add(i)
            hit_p.add(j)
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return len(hit_f), hit_f, hit_p


def evaluate(stem, verbose=False):
    with open(os.path.join(GOLDEN, stem + ".chapters-facit.txt"),
              encoding="utf-8") as f:
        facit = [l.strip() for l in f if l.strip()]
    pred = predicted_titles(os.path.join(GOLDEN, stem + ".txt"))
    facit_n = [title_tokens(t) for t in facit]
    pred_n = [title_tokens(t) for t in pred]
    hits, hit_f, hit_p = lcs_align(facit_n, pred_n)
    if verbose:
        missed = [facit[i] for i in range(len(facit)) if i not in hit_f]
        false = [pred[i] for i in range(len(pred)) if i not in hit_p]
        if missed:
            print("  MISSADE (" + str(len(missed)) + "):")
            for t in missed[:15]:
                print("    " + t)
        if false:
            print("  FALSKA (" + str(len(false)) + "):")
            for t in false[:15]:
                print("    " + t)
    return hits, len(pred), len(facit)


def prf(hits, npred, nfacit):
    p = hits / npred if npred else 0.0
    r = hits / nfacit if nfacit else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


def main():
    verbose = "-v" in sys.argv
    stems = sorted(
        os.path.basename(p)[: -len(".chapters-facit.txt")]
        for p in glob.glob(os.path.join(GOLDEN, "*.chapters-facit.txt"))
        if os.path.exists(os.path.join(
            GOLDEN, os.path.basename(p)[: -len(".chapters-facit.txt")] + ".txt"))
    )
    print("=== KAPITEL: precision/recall mot facit ===")
    header = "{:<24} {:>6} {:>6} {:>6} {:>7} {:>7} {:>7}"
    print(header.format("bok", "facit", "pred", "traff", "P", "R", "F1"))
    tot = [0, 0, 0]
    for stem in stems:
        if verbose:
            print(stem + ":")
        hits, npred, nfacit = evaluate(stem, verbose)
        p, r, f1 = prf(hits, npred, nfacit)
        print(header.format(stem, nfacit, npred, hits,
                            "%.3f" % p, "%.3f" % r, "%.3f" % f1))
        tot[0] += hits
        tot[1] += npred
        tot[2] += nfacit
    p, r, f1 = prf(*tot)
    print(header.format("TOTALT (mikro)", tot[2], tot[1], tot[0],
                        "%.3f" % p, "%.3f" % r, "%.3f" % f1))


if __name__ == "__main__":
    main()
