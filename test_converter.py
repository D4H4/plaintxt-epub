#!/usr/bin/env python3
"""
test_converter.py — Run TextProcessor + EPUBBuilder on all sample .txt files
and report per-file results.

Usage:
    python test_converter.py
"""
import sys, os, re, tempfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure converter.py is importable from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from converter import TextProcessor, EPUBBuilder, HAS_EPUB

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Sample txt files")
EVAL_SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval", "samples")

# Soft expectations: (min_chapters, max_chapters)
EXPECTED = {
    "Starship Troopers.txt":          (12, 45),  # 12 chapters + preamble/metadata
    "Neuromancer.txt":                (5, 30),   # 5 parts + sub-chapter headings
    "Notes from the Underground.txt": (2, 60),
    "Stranger In A Strange Land.txt": (1, 80),
    "Double Star.txt":                (1, 80),
    "2010 Odissey Two.txt":           (1, 80),
    # Pjasregression (Fas 1 sprint 2): baseline var 1137 resp 772 talarnamn;
    # ratt struktur ar ~27 (akter+scener) resp ~1000 (37 pjaser + sonetter)
    "hamlet.txt":                     (20, 60),
    "shakespeare.txt":                (800, 1300),
}

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

def nonws(text):
    return sum(1 for c in text if not c.isspace())

def check(status, name, detail):
    icon = {PASS: "[OK]  ", WARN: "[WARN]", FAIL: "[FAIL]"}[status]
    print("    " + icon + " " + name + ": " + detail)
    return status

def worst(*statuses):
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return PASS


def test_file(path):
    fname = os.path.basename(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # Baseline ar texten efter boilerplate-strip: PG-header/licens tas bort
    # avsiktligt och ska inte raknas som teckenforlust
    stripped = TextProcessor.strip_boilerplate(raw)
    raw_cc = nonws(stripped)
    # Expected em-dash savings: each '--+' sequence loses (len-1) non-ws chars
    import re as _re
    dash_savings = sum(len(m) - 1 for m in _re.findall(r"--+", stripped))
    adjusted_raw_cc = raw_cc - dash_savings
    cleaned = TextProcessor.clean_text(raw)
    clean_cc = nonws(cleaned)
    chapters = TextProcessor.detect_chapters(cleaned)
    chapter_cc = sum(nonws(body) for _, body in chapters)
    n = len(chapters)

    results = []

    # 1. Character preservation through cleaning (adjusted for em-dash savings)
    ratio = clean_cc / adjusted_raw_cc if adjusted_raw_cc else 1.0
    detail = "{:.2f}% preserved (adj. for {} em-dash subs)".format(ratio * 100, dash_savings)
    if ratio >= 0.97:
        results.append(check(PASS, "char-preservation", detail))
    else:
        results.append(check(FAIL, "char-preservation",
                             detail + " (expected >= 97%)".format(ratio * 100)))

    # 2. Em dash replacement
    if "--" not in cleaned:
        results.append(check(PASS, "em-dash", "no bare '--' found"))
    else:
        count = cleaned.count("--")
        results.append(check(FAIL, "em-dash",
                             str(count) + " occurrences of '--' still present"))

    # 3. No quad+ newlines (\n\n\n is now intentional blank-line sentinel)
    if "\n\n\n\n" not in cleaned:
        results.append(check(PASS, "no-quad-newline", "ok"))
    else:
        results.append(check(WARN, "no-quad-newline", "quad+ newlines found"))

    # 4. At least one chapter detected
    if n >= 1:
        results.append(check(PASS, "chapter-count >= 1", str(n) + " chapter(s)"))
    else:
        results.append(check(FAIL, "chapter-count >= 1", "0 chapters detected"))

    # 5. No single-char-token false positives in headings.
    # Rubriker som matchar ett explicit monster (t.ex. ensam romersk siffra,
    # "II" -- legitima kapitel i Notes from the Underground) ar inte misstankta.
    bad = [
        t for t, _ in chapters
        if re.findall(r"[A-Za-z]+", t)
        and not any(len(w) >= 3 for w in re.findall(r"[A-Za-z]+", t))
        and not any(p.match(t) for p in TextProcessor.EXPLICIT_PATTERNS)
    ]
    if not bad:
        results.append(check(PASS, "no-false-pos-headings", "ok"))
    else:
        results.append(check(WARN, "no-false-pos-headings",
                             "suspicious headings: " + str(bad[:3])))

    # 6. Chapter body covers >= 95% of cleaned text
    cov = chapter_cc / clean_cc if clean_cc else 1.0
    if cov >= 0.95:
        results.append(check(PASS, "body-coverage",
                             "{:.1f}% of cleaned text in chapters".format(cov * 100)))
    else:
        results.append(check(WARN, "body-coverage",
                             "{:.1f}% (expected >= 95%)".format(cov * 100)))

    # 7. Expected chapter count (soft, WARN only)
    if fname in EXPECTED:
        lo, hi = EXPECTED[fname]
        if lo <= n <= hi:
            results.append(check(PASS, "expected-ch-count",
                                 "{} in expected range [{}, {}]".format(n, lo, hi)))
        else:
            results.append(check(WARN, "expected-ch-count",
                                 "{} not in expected range [{}, {}]".format(n, lo, hi)))

    # 8. EPUB build
    if HAS_EPUB:
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".epub")
            os.close(fd)
            EPUBBuilder.build("Test", "Test Author", "en", chapters, None, tmp_path)
            os.unlink(tmp_path)
            results.append(check(PASS, "epub-build", "ok"))
        except Exception as exc:
            results.append(check(FAIL, "epub-build", str(exc)[:80]))
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    else:
        results.append(check(WARN, "epub-build", "ebooklib not installed -- skipped"))

    return worst(*results), n, raw_cc, clean_cc, chapter_cc, chapters


def main():
    if not os.path.isdir(SAMPLE_DIR):
        print("ERROR: sample directory not found:", SAMPLE_DIR)
        sys.exit(1)

    search_dirs = [SAMPLE_DIR]
    if os.path.isdir(EVAL_SAMPLES_DIR):
        search_dirs.append(EVAL_SAMPLES_DIR)
    txt_files = sorted(
        os.path.join(root, f)
        for d in search_dirs
        for root, dirs, files in os.walk(d)
        for f in files if f.lower().endswith(".txt")
    )
    if not txt_files:
        print("No .txt files found in", SAMPLE_DIR)
        sys.exit(1)

    overall = PASS
    file_results = []

    for path in txt_files:
        rel = os.path.basename(path)
        print()
        print("=" * 64)
        print(rel)
        print("-" * 64)
        try:
            status, n, raw_cc, clean_cc, chapter_cc, chapters = test_file(path)
        except Exception as exc:
            print("    [FAIL] EXCEPTION: " + str(exc))
            status = FAIL
            n, raw_cc, clean_cc, chapter_cc, chapters = 0, 0, 0, 0, []

        pct_kept = (chapter_cc / raw_cc * 100) if raw_cc else 0.0
        print()
        print("    Summary: {:,} raw chars | {:,} cleaned | {} chapter(s) | {:.1f}% kept".format(
            raw_cc, clean_cc, n, pct_kept))
        if chapters:
            titles = [t for t, _ in chapters[:6]]
            print("    Chapters: " + " | ".join(t[:25] for t in titles)
                  + (" ..." if n > 6 else ""))
        print("    Result: [" + status + "]")
        file_results.append((rel, status))
        overall = worst(overall, status)

    print()
    print("=" * 64)
    print("OVERALL: [" + overall + "]")
    print()
    for rel, status in file_results:
        print("  [" + status + "]  " + rel)
    print()

    sys.exit(0 if overall != FAIL else 1)


if __name__ == "__main__":
    main()
