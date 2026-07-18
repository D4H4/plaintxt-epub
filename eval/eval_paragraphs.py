#!/usr/bin/env python3
"""Fas 0.5 matskript stycken: precision/recall for clean_text mot PG-epub.

Facit = styckena (<p>) i PG-epuben i lasordning; prediktion = styckena ur
clean_text pa samma utgavas txt. Ett stycke raknas som traff nar dess
normaliserade innehall (casefold, enbart alfanumeriskt — typografi och
radbryt paverkar inte) finns pa andra sidan (multiset-matchning). Fel
styckegrans ger miss pa bada sidor: bade split och join straffas.
Kor: python eval/eval_paragraphs.py [-v]

Kant brus (accepterat, dokumenterat): rubrikrader ligger kvar som stycken
i predikterad text men ar exkluderade (h-taggar) ur facit; PG-boilerplate
skiljer sig nagot mellan txt och epub; vers utanfor <p> saknas i facit."""
import os
import re
import sys
import glob
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
from converter import TextProcessor
from epub_extract import extract, norm_para

GOLDEN = os.path.join(_HERE, "golden")


def facit_paragraphs(epub_path):
    _, paragraphs = extract(epub_path)
    return [n for n in (norm_para(p) for p in paragraphs) if n]


def predicted_paragraphs(txt_path):
    raw = TextProcessor.read_text_file(txt_path)
    cleaned = TextProcessor.clean_text(raw)
    paras = re.split(r"\n{2,}", cleaned)
    return [n for n in (norm_para(p) for p in paras) if n]


def prf(hits, npred, nfacit):
    p = hits / npred if npred else 0.0
    r = hits / nfacit if nfacit else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


def main():
    verbose = "-v" in sys.argv
    stems = sorted(
        os.path.basename(p)[: -len(".epub")]
        for p in glob.glob(os.path.join(GOLDEN, "*.epub"))
        if os.path.exists(os.path.join(
            GOLDEN, os.path.basename(p)[: -len(".epub")] + ".txt"))
    )
    print("=== STYCKEN: precision/recall mot PG-epub ===")
    header = "{:<24} {:>7} {:>7} {:>7} {:>7} {:>7} {:>7}"
    print(header.format("bok", "facit", "pred", "traff", "P", "R", "F1"))
    tot = [0, 0, 0]
    for stem in stems:
        facit = Counter(facit_paragraphs(os.path.join(GOLDEN, stem + ".epub")))
        pred = Counter(predicted_paragraphs(os.path.join(GOLDEN, stem + ".txt")))
        hits = sum((facit & pred).values())
        nfacit, npred = sum(facit.values()), sum(pred.values())
        p, r, f1 = prf(hits, npred, nfacit)
        print(header.format(stem, nfacit, npred, hits,
                            "%.3f" % p, "%.3f" % r, "%.3f" % f1))
        if verbose:
            missed = list((facit - pred).elements())
            false = list((pred - facit).elements())
            for label, items in (("MISSADE", missed), ("FALSKA", false)):
                print("  " + label + " (" + str(len(items)) + "), exempel:")
                for t in items[:5]:
                    print("    " + t[:100])
        tot[0] += hits
        tot[1] += npred
        tot[2] += nfacit
    p, r, f1 = prf(*tot)
    print(header.format("TOTALT (mikro)", tot[2], tot[1], tot[0],
                        "%.3f" % p, "%.3f" % r, "%.3f" % f1))


if __name__ == "__main__":
    main()
