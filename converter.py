#!/usr/bin/env python3
"""PlainTXT-EPUB Converter - Desktop application."""

import os
import re
import html as html_module
import io
from pathlib import Path
import threading
import types
import uuid

HAS_TK = False
HAS_DND = False
HAS_EPUB = False
HAS_PIL = False

# GUI-beroendet ar valfritt: cli.py importerar TextProcessor/EPUBBuilder
# headless (servrar, WSL, CI) — tkinter kravs forst nar GUI:t startas.
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_TK = True
except ImportError:
    tk = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    pass

try:
    from ebooklib import epub
    HAS_EPUB = True
except ImportError:
    pass

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    pass


class TextProcessor:
    EXPLICIT_PATTERNS = [
        re.compile(r"^chapter\s+[\dIVXLCDMivxlcdm]+(\s*[:\-\u2013\u2014.]\s*.{0,80})?$", re.IGNORECASE),
        re.compile(r"^part\s+[\dIVXLCDMivxlcdm]+(\s*[:\-\u2013\u2014.]\s*.{0,80})?$", re.IGNORECASE),
        re.compile(r"^book\s+[\dIVXLCDMivxlcdm]+(\s*[:\-\u2013\u2014.]\s*.{0,80})?$", re.IGNORECASE),
        re.compile(
            r"^(prologue|epilogue|introduction|preface|foreword|afterword|appendix|conclusion)"
            r"(\s*[:\-\u2013\u2014.]\s*.{0,80})?$", re.IGNORECASE),
        re.compile(r"^\d{1,3}\.\s+[A-Z\u00C0-\u024F].{0,80}$"),
        re.compile(r"^[IVXLCDMivxlcdm]{1,6}\.\s+[A-Z\u00C0-\u024F].{2,80}$"),
        re.compile(r"^(act|scene)\s+[\dIVXLCDMivxlcdm]+(\s*[:\-\u2013\u2014.]\s*.{0,80})?$", re.IGNORECASE),
        re.compile(r"^\d{1,3}\s*[-\u2013\u2014]\s+\S.{0,78}$"),  # "1 - The Slow Fuse"
        re.compile(r"^[IVXLCDM]{1,7}\.?$"),  # ensam romersk siffra (epilogkapitel)
    ]

    # Rubrikkandidat vars text aterkommer sa har manga ganger ar sannolikt
    # talarnamn i pjas (BERNARDO, HAMLET ...) \u2014 undertrycks om den inte
    # matchar ett explicit monster (skyddar "CHAPTER I" som repeteras
    # legitimt over delar i t.ex. Crime and Punishment)
    REPEAT_SUPPRESS_THRESHOLD = 3

    # Dominant monster-undertryckning: nar minst sa har manga kandidater OCH
    # en sa har stor andel matchar explicita monster ar de ovriga kandidaterna
    # (unika ALL-CAPS-scenmarkorer, ortsnamn, telegramrader) sannolikt inte
    # kapitel. Andelskravet skyddar bocker dar merparten rubriker ar legitimt
    # monsterlosa (diktsamlingar: Leaves of Grass ~25 % explicit).
    # 0.55: Dracula hamnar pa 0.587 nar forlagsreklamen i baksidesmaterialet
    # (15 ALL-CAPS boktitlar) raknas med — fortfarande langt over Leaves 25 %.
    DOMINANT_MIN_COUNT = 10
    DOMINANT_MIN_FRACTION = 0.55

    # Sa har manga brodtextlosa rubriker i rad tolkas som innehallsforteckning
    TOC_RUN = 3

    @classmethod
    def is_chapter_heading(cls, line, prev_blank, next_blank):
        line = line.strip()
        if not line or len(line) > 100:
            return False
        if not (prev_blank and next_blank):
            return False
        for pattern in cls.EXPLICIT_PATTERNS:
            if pattern.match(line):
                return True
        # Reject single-char token patterns like "O O O O" or "C A S E : :"
        alpha_words = re.findall(r'[A-Za-z]+', line)
        if alpha_words and not any(len(w) >= 3 for w in alpha_words):
            return False
        # Reject lines that are clearly dialogue or questions
        _OPEN_QUOTES = ('"', '\u201c', "'", '\u2018', '\u2019')
        if line[0] in _OPEN_QUOTES:
            return False
        # Reject stage directions / metadata in brackets: [Exit], (Continued)
        if line[0] in ('[', '('):
            return False
        if line[-1] in ('?', '!', ';', ':'):
            return False
        # Kolumnlayout (TOC-listor, illustrationsforteckningar med sidnummer):
        # inre whitespace-korning eller avslutande rent tal
        if re.search(r"\s{3,}", line):
            return False
        words = line.split()
        if words[-1].isdigit():
            return False
        # Scenanvisningar och talarrepliker i pjaser
        if re.match(r"(re-)?(enter|exit|exeunt)\b", line, re.IGNORECASE):
            return False
        first = words[0]
        if first.endswith('.') and len(first) > 2 and first[:-1].isupper():
            return False  # "CORNELIUS. Your Highness" — talarcue
        # Reject closing signatures: ALL-CAPS, ends with '.', <= 3 words (e.g. 'S. VERNON.')
        if line.isupper() and line.endswith('.') and len(words) <= 3:
            return False
        if line.isupper() and len(line) >= 3 and re.search(r"[A-Z]", line):
            # ...men inte med komma: talarkombos ("CORNELIUS, VOLTIMAND"),
            # ortsmarkorer ("SUNNYVALE, CALIFORNIA"), datumrader
            return "," not in line
        # Reject 'Speaker: Dialogue' patterns (e.g. 'Smith: Yes.' or 'Author: Name')
        if any(w.endswith(':') for w in words[:-1]):
            return False
        # Require at least 2 words for title-case heuristic (single-word headings
        # like Prologue/Epilogue are already matched by EXPLICIT_PATTERNS above).
        # Egen titelregel i stallet for str.istitle(): apostrofer/bindestreck
        # ("One's-Self I Sing") och gemena funktionsord ("As I Ponder'd in
        # Silence") ska inte falla en akta titel.
        if 2 <= len(words) <= 8 and ',' not in line and not line.endswith('.'):
            # Ledande siffra tillaten: "1 The Frozen Years" (nummer +
            # titel utan skiljetecken — 2061-klassen)
            if ((words[0][0].isupper() or words[0].isdigit())
                    and all(cls._title_word(w) for w in words)):
                return True
        return False

    _TITLE_FUNC_WORDS = frozenset(
        "a an the of in on at to for by with from and or nor as o'er".split())

    @classmethod
    def _title_word(cls, word):
        c = word[0]
        if c.isupper() or c.isdigit():
            return True
        return c.islower() and word.lower() in cls._TITLE_FUNC_WORDS

    @classmethod
    def _wrap_width(cls, text, lf):
        """Estimate page/column wrap width from the 90th-percentile line length."""
        lengths = sorted(len(l) for l in text.split(lf) if len(l.strip()) > 30)
        if not lengths:
            return None
        p90 = lengths[int(len(lengths) * 0.90)]
        return p90 if p90 >= 40 else None

    @classmethod
    def suggest_author(cls, text):
        """Scan the first ~80 non-empty lines for a "by Name" pattern."""
        lines = [l.strip() for l in text.split('\n')[:80] if l.strip()]
        for i, line in enumerate(lines[:25]):
            import re as _re
            m = _re.match(r'^by\s+(.{3,60})$', line, _re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()
                if len(candidate.split()) <= 6:
                    return candidate
            # Handle 'by' alone on a line, name on the next line
            if line.lower() == 'by' and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if 1 <= len(candidate.split()) <= 6 and len(candidate) >= 3:
                    return candidate
        # Fallback: "Author. Title" on the very first non-blank line
        # e.g. "William Gibson. Neuromancer" or "Robert A. Heinlein. Starship Troopers"
        if lines:
            import re as _re
            m = _re.match(
                r'^([A-Z][a-z]+(?:\s+[A-Z]\.|\s+[A-Z][a-z]+){1,3})\.\s+\S',
                lines[0]
            )
            if m:
                candidate = m.group(1).strip()
                if 2 <= len(candidate.split()) <= 5:
                    return candidate
        return ""

    @classmethod
    def dominant_pattern_index(cls, titles):
        """Return index of EXPLICIT_PATTERNS matching most titles (need >= 3)."""
        counts = [0] * len(cls.EXPLICIT_PATTERNS)
        for title in titles:
            for i, pat in enumerate(cls.EXPLICIT_PATTERNS):
                if pat.match(title.strip()):
                    counts[i] += 1
                    break
        best = max(range(len(counts)), key=lambda i: counts[i])
        return best if counts[best] >= 3 else None

    # Tva generationer PG-markorer: moderna "*** START/END OF THE PROJECT
    # GUTENBERG EBOOK ***" och 90-talets Etext-format ("*END*THE SMALL
    # PRINT!..." avslutar headern, "**End of The Project Gutenberg Etext...")
    _PG_START = re.compile(
        r"^\s*(\*{3}\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK\b.*"
        r"|\*END\*THE SMALL PRINT![^\n]*)$",
        re.IGNORECASE | re.MULTILINE)
    _PG_END = re.compile(
        r"^\s*(\*{3}\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK\b"
        r"|\*{0,5}\s*End of (the |this )?Project Gutenberg('s)?\s+(Etext|EBook)\b)",
        re.IGNORECASE | re.MULTILINE)

    @staticmethod
    def read_text_file(path):
        """Las en textfil med encoding-sniff: BOM forst, sedan strikt utf-8,
        sedan cp1252 (vanligast bland gamla e-bocker — maskerades tidigare
        till � av errors='replace'), sist utf-8 med ersattning."""
        with open(path, "rb") as f:
            data = f.read()
        if data[:3] == b"\xef\xbb\xbf":
            return data.decode("utf-8-sig")
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return data.decode("utf-16")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return data.decode("cp1252")
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="replace")

    # Strukturvarning (klass B): en stor bok som ger <= 1 kapitel ar nastan
    # alltid strukturlos input (en-radare, stycke-per-rad med inbakade
    # rubriker) — varna i stallet for att tyst leverera 1 kapitel.
    # Utfallsbaserad avsiktligt: stycke-per-rad MED blankrader fungerar fint
    # och ska inte flaggas. p90-radlangden anvands bara som forklaring
    # (radbruten text haller sig under ~80 tecken).
    STRUCTURE_MIN_SIZE = 50_000  # tecken; mindre kan legitimt sakna kapitel

    @classmethod
    def structure_warning(cls, text, n_chapters):
        """Returnerar varningsstrang nar en stor text gav <= 1 kapitel."""
        if n_chapters > 1 or len(text) < cls.STRUCTURE_MIN_SIZE:
            return None
        lengths = sorted(len(l) for l in text.split("\n") if l.strip())
        if not lengths:
            return None
        p90 = lengths[min(len(lengths) - 1, int(len(lengths) * 0.90))]
        if p90 > 150:
            reason = ("The file looks like a one-line or paragraph-per-line "
                      "export (90th-percentile line length " + str(p90)
                      + " chars; hard-wrapped text stays under ~80).")
        else:
            reason = "No line matched any known chapter-heading pattern."
        return ("No chapter structure found in this large file. " + reason
                + " The EPUB will be one single continuous chapter.")

    @classmethod
    def strip_boilerplate(cls, text):
        """Strip Project Gutenberg header/footer via *** START/END markers.
        Positional guards (start marker in first half, end marker in second)
        so a book merely quoting the markers is left alone."""
        m = cls._PG_START.search(text)
        if m and m.start() < len(text) // 2:
            text = text[m.end():]
        matches = list(cls._PG_END.finditer(text))
        if matches and matches[-1].start() > len(text) // 2:
            text = text[:matches[-1].start()]
        return text

    @classmethod
    def clean_text(cls, text):
        text = cls.strip_boilerplate(text)
        cr, lf = chr(13), chr(10)
        text = text.replace(cr + cr + lf, lf)  # handle \r\r\n artifact
        text = text.replace(cr + lf, lf).replace(cr, lf)
        # Strip NULL bytes and non-printable control chars (keep \t and \n)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # Rader med bara whitespace ar avsedda blankrader — normalisera,
        # annars uteblir blockdelningen ("\n  \n" splittar inte "\n\n"):
        # Ender's Game-klassen av filer blev ETT jatteblock och kollapsade.
        text = re.sub(r"(?m)^[ \t]+$", "", text)
        # Replace double/triple hyphens with em dash
        text = re.sub(r"--+", "\u2014", text)
        # Detect page/column wrap width to distinguish soft wraps from
        # intentional breaks (dialogue, verse, end of paragraph).
        wrap = cls._wrap_width(text, lf)
        # Illustrationsmarkorer ("[Illustration]", "[Illustration: bildtext]",
        # aven spannande flera stycken) pekar pa bilder som inte foljer med
        # txt:n — brus for lasaren. Kapitelrubriker som PG bakat in i markoren
        # ("[Illustration: ... Chapter I.]") maste overleva.
        def _illustration_repl(m):
            keep = [l.strip(" \t]") for l in m.group(0).split(lf)
                    if re.match(r"\s*chapter\b", l, re.IGNORECASE)]
            return (lf + lf).join(keep)
        text = re.sub(r"\[Illustration[^\[\]]*\]", _illustration_repl, text)
        blocks = text.split(lf + lf)
        # Dokumentlage: ar blankradsblocken STYCKEN (PG-stil, median ~5
        # rader) eller SIDOR (sidformaterade filer: blankrad per sidbrytning,
        # median ~50 — Sherlock Holmes-klassen)? Sidblock far inte joinas
        # till jattestycken som svaljer rubrikerna — dar galler den gamla
        # radjoin-heuristiken i stallet.
        sizes = sorted(
            sum(1 for l in b.split(lf) if l.strip())
            for b in blocks if b.strip())
        page_mode = bool(sizes) and sizes[len(sizes) // 2] > 25
        result_blocks = []
        for block in blocks:
            orig_lines = [l for l in block.split(lf) if l.strip()]
            if not orig_lines:
                continue
            stripped = [l.strip() for l in orig_lines]
            if len(orig_lines) == 1:
                # Behall vansterindraget — detect_chapters anvander det for
                # att skilja centrerade dekorationer fran rubriker.
                # Strippas vid HTML-rendering.
                result_blocks.append([orig_lines[0].rstrip()])
                continue
            # Versblock: indenterade rader (PG satter vers med 2+ mellanslags
            # indrag; prosa och pjasrepliker ar vansterstallda) som inte
            # fyller radbrytningsbredden. Radbrytningarna ar avsiktliga —
            # bevara dem (renderas som <br/> i EPUB:en).
            # Storleksgrans: en "strof" pa hundratals rader ar ingen strof
            # utan en indenterad fil utan blockstruktur — prosavagen. Och
            # ett TVAradersblock ar nastan aldrig en strof men nastan
            # alltid rubrik + undertitel ("CHAPTER I. / THE SCIENCE OF
            # DEDUCTION.", "1 / The Frozen Years") — prosajoin.
            # Radlangdsgrans: versrader ar korta (~<= 75 tecken aven hos
            # Whitman); tab-indenterad stycke-per-rad (90-talsexporter,
            # median 150+) ar prosa.
            indented = sum(1 for l in orig_lines
                           if l.startswith("  ") or l.startswith("\t"))
            linelens = sorted(len(l) for l in stripped)
            median_len = linelens[len(linelens) // 2]
            # Tvaradersblock: rubrik + undertitel om forsta raden ar kort
            # ("1" / "CHAPTER I."), verspar (couplet) annars.
            two_line_heading = (len(stripped) == 2 and len(stripped[0]) <= 12)
            if (len(orig_lines) <= 200 and median_len <= 85
                    and not two_line_heading
                    and indented * 3 >= len(orig_lines) * 2):
                # Indenterad PROSA (brev, blockcitat) skiljs fran vers pa
                # att den ar jamn: uniform indentering och alla rader utom
                # den sista wrap-fyllda. Vers ar ojamn i bade radlangd och
                # indrag (Whitmans strofförster/wrappade fortsattningar).
                indents = {len(l) - len(l.lstrip()) for l in orig_lines}
                nf = [len(l) for l in stripped[:-1]]
                uniform_fill = (
                    wrap is not None and len(indents) == 1 and len(nf) >= 2
                    and max(nf) - min(nf) <= 8
                    and min(nf) >= wrap - 20)
                if not uniform_fill:
                    result_blocks.append([lf.join(stripped)])
                    continue
            # Prosablock: blankradsavgransade block AR stycken — joina helt.
            # Radjoin-heuristik pa blockniva var nettonegativ pa alla
            # golden set-bocker (C&P 0.914 vs 0.998 for ren blockjoin).
            # Undantag: jattelika block (ingen blankradsstruktur) far ga
            # genom den gamla heuristiken i stallet for att bli ett
            # monsterstycke.
            # Avstavade radslut ("ques-/tionable") avslojar hart radbruten
            # skanna-prosa (Adventures-klassen): dar ar stora block SIDOR,
            # inte stycken, aven om filens median ar lag.
            hyphen_wrapped = sum(
                1 for l in stripped[:-1] if l.endswith("-")) >= 3
            if page_mode or len(stripped) > 60 or (
                    len(stripped) > 25 and hyphen_wrapped):
                result_blocks.append(cls._split_wrapped_block(stripped, wrap))
            else:
                result_blocks.append([chr(32).join(stripped)])
        return (lf + lf + lf).join((lf + lf).join(b) for b in result_blocks)

    @classmethod
    def _split_wrapped_block(cls, raw_lines, wrap):
        """Gamla hybrid-radjoinen: styckegissning inom ett block via
        wrap-bredd + interpunktionssignaler. Anvands numera bara som
        fallback for block utan blankradsstruktur (> 60 rader)."""
        # Sentence-terminal chars (by ordinal): . ! ? “ ‘
        SENT_END = frozenset([46, 33, 63, 8221, 8217])
        # Function words that signal mid-sentence continuation when at line end
        CONT_WORDS = frozenset(
            "a an the of in on at to for by with from and but or nor as into "
            "that which than about over under after before".split()
        )
        paras = []
        current = [raw_lines[0]]
        for i in range(1, len(raw_lines)):
            prev = current[-1].rstrip()
            prev_len = len(prev)
            next_line = raw_lines[i]
            # Primary: line hit the page wrap -> definitely join
            if wrap is not None and prev_len >= wrap - 3:
                current.append(next_line)
                continue
            # Secondary: layered continuation signals
            last_ch = ord(prev[-1]) if prev else 0
            if last_ch in SENT_END:
                # Sentence-terminal punctuation -> paragraph break
                paras.append(chr(32).join(current))
                current = [next_line]
            elif next_line and (next_line[0].islower() or next_line[0].isdigit()):
                # Next starts lowercase or digit (e.g. “1880’s”) -> join
                current.append(next_line)
            elif (prev.lower().rstrip(".,;:" + chr(39) + chr(34)).rsplit(None, 1) or [""])[-1] in CONT_WORDS:
                # Line ends with preposition/article/conjunction -> join
                current.append(next_line)
            elif wrap is not None and prev_len >= wrap - 12:
                # Line within 12 chars of wrap width, no sent-punct -> join
                current.append(next_line)
            else:
                # Conservative break
                paras.append(chr(32).join(current))
                current = [next_line]
        paras.append(chr(32).join(current))
        return paras

    @classmethod
    def _suppress_repeated(cls, chapter_starts):
        """Filtrera rubrikkandidater som upprepas >= troskeln utan att matcha
        nagot explicit monster — talarnamn i pjaser, scenmarkorer o.d.
        Undertryckta rader lamnas kvar i brodtexten."""
        counts = {}
        for _, title in chapter_starts:
            key = " ".join(title.split()).casefold()
            counts[key] = counts.get(key, 0) + 1
        kept = []
        for i, title in chapter_starts:
            key = " ".join(title.split()).casefold()
            if counts[key] >= cls.REPEAT_SUPPRESS_THRESHOLD and not any(
                    p.match(title) for p in cls.EXPLICIT_PATTERNS):
                continue
            kept.append((i, title))
        return kept

    @classmethod
    def _suppress_nondominant(cls, chapter_starts, is_decor=None):
        """Filtrera icke-explicita kandidater nar de explicita monstren
        dominerar (se DOMINANT_MIN_*). Alla explicita monster overlever —
        blandade strukturer (PART + CHAPTER, ACT + SCENE) rors inte.

        is_decor(line_idx): dekorationsmisstankta kandidater (centrerade
        ALL-CAPS-rader — titelsidor, forlagsreklam) far inte ROSTA i
        andelsberakningen (annars spader skrapet ut de explicita och
        stanger av just den mekanism som skulle ta bort det — Dracula),
        men stryks som alla andra icke-explicita nar dominans rader.
        Bocker vars AKTA rubriker ar centrerade CAPS (2061, Street Lawyer)
        saknar explicit struktur -> ingen dominans -> rubrikerna overlever."""
        if not chapter_starts:
            return chapter_starts
        explicit = [
            any(p.match(title) for p in cls.EXPLICIT_PATTERNS)
            for _, title in chapter_starts
        ]
        voters = [
            is_exp for (idx, _), is_exp in zip(chapter_starts, explicit)
            if is_exp or is_decor is None or not is_decor(idx)
        ]
        n_explicit = sum(explicit)
        if (n_explicit >= cls.DOMINANT_MIN_COUNT and voters
                and n_explicit / len(voters) >= cls.DOMINANT_MIN_FRACTION):
            return [cs for cs, is_exp in zip(chapter_starts, explicit) if is_exp]
        return chapter_starts

    @classmethod
    def detect_chapters(cls, text):
        lines = text.split("\n")
        n = len(lines)
        chapter_starts = []
        for i, line in enumerate(lines):
            prev_blank = (i == 0) or (not lines[i - 1].strip())
            next_blank = (i == n - 1) or (not lines[i + 1].strip())
            if cls.is_chapter_heading(line, prev_blank, next_blank):
                chapter_starts.append((i, line.strip()))
        chapter_starts = cls._suppress_repeated(chapter_starts)

        def _is_decor(idx):
            l = lines[idx]
            return (len(l) - len(l.lstrip())) >= 6 and l.strip().isupper()
        chapter_starts = cls._suppress_nondominant(chapter_starts, _is_decor)
        if not chapter_starts:
            return [("Content", text.strip())]
        # Brodtextlosa rubriker: en ensam ar en avdelarsida (PART I fore
        # CHAPTER I, ACT I fore SCENE I) och behalls om den ar explicit;
        # en svit om >= TOC_RUN i rad ar en innehallsforteckning -> slang.
        n_starts = len(chapter_starts)
        empty = []
        for idx, (line_idx, _) in enumerate(chapter_starts):
            end_idx = chapter_starts[idx + 1][0] if idx + 1 < n_starts else n
            empty.append(not "\n".join(lines[line_idx + 1:end_idx]).strip())
        keep = [True] * n_starts
        idx = 0
        while idx < n_starts:
            if empty[idx]:
                run_end = idx
                while run_end < n_starts and empty[run_end]:
                    run_end += 1
                is_toc = run_end - idx >= cls.TOC_RUN
                for k in range(idx, run_end):
                    keep[k] = not is_toc and any(
                        p.match(chapter_starts[k][1]) for p in cls.EXPLICIT_PATTERNS)
                idx = run_end
            else:
                idx += 1
        chapter_starts = [cs for cs, kp in zip(chapter_starts, keep) if kp]
        if not chapter_starts:
            return [("Content", text.strip())]
        chapters = []
        pre = "\n".join(lines[:chapter_starts[0][0]]).strip()
        if pre:
            chapters.append(("Introduction", pre))
        for idx, (line_idx, title) in enumerate(chapter_starts):
            end_idx = chapter_starts[idx + 1][0] if idx + 1 < len(chapter_starts) else n
            body = "\n".join(lines[line_idx + 1:end_idx]).strip()
            chapters.append((title, body))
        if not chapters:
            return [("Content", text.strip())]
        return chapters

    @staticmethod
    def text_to_html(text):
        # Normalize 4+ newlines down to triple (triple = intentional blank line)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        # Split preserving separators to distinguish blank-line from para-break
        tokens = re.split(r'(\n{2,})', text)
        parts = []
        for tok in tokens:
            if tok.startswith('\n'):
                if len(tok) >= 3:
                    parts.append('<p>\u00a0</p>')  # intentional blank line
                # len == 2 → normal paragraph break, no extra output
            else:
                tok = tok.strip()
                if tok:
                    escaped = html_module.escape(tok).replace('\n', '<br/>')
                    parts.append('<p>' + escaped + '</p>')
        return '\n'.join(parts)


class EPUBBuilder:
    CSS = "\n".join([
        "body {",
        "    font-family: Georgia, serif;",
        "    font-size: 1em;",
        "    line-height: 1.7;",
        "    margin: 0 5%;",
        "    color: #1a1a1a;",
        "}",
        "h1 {",
        "    font-size: 1.4em;",
        "    font-weight: bold;",
        "    margin-top: 2em;",
        "    margin-bottom: 1.2em;",
        "    text-align: center;",
        "    page-break-before: always;",
        "    color: #222;",
        "}",
        "p {",
        "    margin: 0.4em 0;",
        "    text-indent: 1.5em;",
        "    text-align: justify;",
        "}",
        "p:first-of-type {",
        "    text-indent: 0;",
        "}",
    ])

    @classmethod
    def build(cls, title, author, language, chapters, cover_path, output_path):
        book = epub.EpubBook()
        book.set_identifier(str(uuid.uuid4()))
        book.set_title(title)
        book.set_language(language)
        book.add_author(author)

        if cover_path and os.path.exists(cover_path):
            ext = Path(cover_path).suffix.lower()
            with open(cover_path, "rb") as f:
                cover_data = f.read()
            if HAS_PIL:
                img = Image.open(cover_path).convert("RGB")
                img.thumbnail((1400, 2100), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                cover_data = buf.getvalue()
                cover_filename = "cover.jpg"
            else:
                cover_filename = "cover" + ext
            book.set_cover(cover_filename, cover_data)

        css_item = epub.EpubItem(
            uid="css_default",
            file_name="style/default.css",
            media_type="text/css",
            content=cls.CSS,
        )
        book.add_item(css_item)

        epub_chapters = []
        toc_links = []
        for i, (ch_title, ch_body) in enumerate(chapters):
            ch_id = "chap_" + str(i + 1).zfill(3)
            file_name = ch_id + ".xhtml"
            safe_title = html_module.escape(ch_title)
            safe_lang = html_module.escape(language)
            body_html = TextProcessor.text_to_html(ch_body)
            q = chr(34)
            xhtml = (
                "<?xml version=" + q + "1.0" + q + " encoding=" + q + "utf-8" + q + "?>\n"
                "<!DOCTYPE html>\n"
                "<html xmlns=" + q + "http://www.w3.org/1999/xhtml" + q
                + " xml:lang=" + q + safe_lang + q + " lang=" + q + safe_lang + q + ">\n"
                "<head>\n"
                "  <title>" + safe_title + "</title>\n"
                "  <link rel=" + q + "stylesheet" + q + " type=" + q + "text/css" + q
                + " href=" + q + "style/default.css" + q + "/>\n"
                "</head>\n"
                "<body>\n"
                "  <h1>" + safe_title + "</h1>\n"
                "  " + body_html + "\n"
                "</body>\n"
                "</html>"
            )
            ch_item = epub.EpubHtml(title=ch_title, file_name=file_name, lang=language)
            ch_item.set_content(xhtml.encode("utf-8"))
            ch_item.add_item(css_item)
            book.add_item(ch_item)
            epub_chapters.append(ch_item)
            toc_links.append(epub.Link(file_name, ch_title, ch_id))

        book.toc = toc_links
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav"] + epub_chapters
        epub.write_epub(output_path, book, {})
        return output_path


class ChapterVerifyDialog:
    def __init__(self, parent, chapters, book_title=None, book_index=None,
                 total_books=None, cover_path=None):
        self.result = None  # None = cancelled; list = confirmed chapters
        dlg = tk.Toplevel(parent)
        if book_index is not None and total_books is not None:
            dlg.title("Verify Chapters — Book " + str(book_index) + " of " + str(total_books))
        else:
            dlg.title("Verify Detected Chapters")
        dlg.resizable(True, True)
        dlg.minsize(540, 460)
        dlg.transient(parent)
        dlg.grab_set()
        dlg.configure(bg=BG)

        ttk.Label(dlg, text="Chapters Detected",
                  font=("Segoe UI", 13, "bold"),
                  background=BG, foreground=TEXT_COL).pack(anchor="w", padx=16, pady=(14, 2))
        if book_index is not None and total_books is not None:
            ctx_frame = tk.Frame(dlg, bg=BG)
            ctx_frame.pack(fill="x", padx=16, pady=(0, 4))
            # Thumbnail / placeholder (left side)
            thumb_slot = tk.Frame(ctx_frame, bg=BG, width=36, height=50)
            thumb_slot.pack(side="left", padx=(0, 8))
            thumb_slot.pack_propagate(False)
            if HAS_PIL and cover_path:
                try:
                    img = Image.open(cover_path)
                    img.thumbnail((34, 48), Image.LANCZOS)
                    _ph = ImageTk.PhotoImage(img)
                    dlg._cover_tk = _ph  # prevent GC
                    tk.Label(thumb_slot, image=_ph, bg=BG).pack()
                except Exception:
                    _cover_placeholder(thumb_slot).pack()
            else:
                _cover_placeholder(thumb_slot).pack()
            # Text labels (right side)
            txt_side = tk.Frame(ctx_frame, bg=BG)
            txt_side.pack(side="left", fill="x", expand=True)
            context_text = "Book " + str(book_index) + " of " + str(total_books)
            if book_title:
                context_text += ":  " + book_title
            ttk.Label(txt_side, text=context_text,
                      font=("Segoe UI", 10, "bold"),
                      background=BG, foreground=ACCENT).pack(anchor="w")
        ttk.Label(dlg,
                  text="Real chapters are pre-selected. Uncheck false positives or re-check missed chapters, then click Confirm.",
                  background=BG, foreground=MUTED,
                  font=("Segoe UI", 9), wraplength=500).pack(anchor="w", padx=16, pady=(0, 10))

        list_frame = tk.Frame(dlg, bg="white", relief="solid", bd=1)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        canvas = tk.Canvas(list_frame, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg="white")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._vars = []
        self._chapters = chapters
        dom = TextProcessor.dominant_pattern_index([t for t, _ in chapters])
        for ch_title, ch_body in chapters:
            wc = len(ch_body.split())
            if dom is not None:
                default = bool(TextProcessor.EXPLICIT_PATTERNS[dom].match(ch_title.strip()))
            else:
                default = True
            var = tk.BooleanVar(value=default)
            self._vars.append(var)
            row = tk.Frame(inner, bg="white")
            row.pack(fill="x", pady=1, padx=4)
            tk.Checkbutton(row, variable=var, text=ch_title,
                           bg="white", activebackground="white",
                           font=("Segoe UI", 10), anchor="w").pack(side="left")
            tk.Label(row, text="(" + str(wc) + " words)",
                     font=("Segoe UI", 8), fg=MUTED, bg="white").pack(side="left", padx=(6, 0))

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(fill="x", padx=16, pady=(0, 4))
        ttk.Button(btn_row, text="Select all",
                   command=lambda: [v.set(True) for v in self._vars]).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Deselect all",
                   command=lambda: [v.set(False) for v in self._vars]).pack(side="left")

        ok_row = tk.Frame(dlg, bg=BG)
        ok_row.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(ok_row, text="Cancel",
                   command=dlg.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(ok_row, text="Confirm",
                   command=lambda: self._confirm(dlg)).pack(side="right")

        dlg.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        dw, dh = 560, 540
        dlg.geometry(str(dw) + "x" + str(dh) + "+"
                     + str(px + (pw - dw) // 2) + "+" + str(py + (ph - dh) // 2))
        parent.wait_window(dlg)

    def _confirm(self, dlg):
        kept = []
        orphan = []  # deselected content before any kept chapter
        for (ch_title, ch_body), var in zip(self._chapters, self._vars):
            content = "\n\n".join(filter(None, [ch_title, ch_body]))
            if var.get():
                if orphan:
                    ch_body = "\n\n".join(filter(None, orphan + [ch_body]))
                    orphan = []
                kept.append((ch_title, ch_body))
            else:
                if kept:
                    # Append to previous chapter to preserve reading order
                    prev_title, prev_body = kept[-1]
                    kept[-1] = (prev_title, "\n\n".join(filter(None, [prev_body, content])))
                else:
                    orphan.append(content)
        if orphan:
            if kept:
                first_title, first_body = kept[0]
                kept[0] = (first_title, "\n\n".join(filter(None, orphan + [first_body])))
            else:
                kept = [("Content", "\n\n".join(orphan))]
        self.result = kept
        dlg.destroy()


ACCENT   = "#4a7fcb"
ACCENT_H = "#3566a8"
BG       = "#f4f4f6"
TEXT_COL = "#1e1e1e"
MUTED    = "#666677"
DROP_BG  = "#eaf1fb"
DROP_ACT = "#cfdff5"


def _add_tooltip(widget, text):
    """Attach a simple hover tooltip to *widget*."""
    tip = [None]
    def _show(e):
        tip[0] = tk.Toplevel(widget)
        tip[0].wm_overrideredirect(True)
        tip[0].wm_geometry(f"+{e.x_root + 12}+{e.y_root + 16}")
        tk.Label(tip[0], text=text, bg="#ffffcc", relief="solid", bd=1,
                 font=("Segoe UI", 8), wraplength=260, justify="left").pack(ipadx=4, ipady=2)
    def _hide(e):
        if tip[0]:
            tip[0].destroy()
            tip[0] = None
    widget.bind("<Enter>", _show, add="+")
    widget.bind("<Leave>", _hide, add="+")


def find_cover(txt_path):
    """Leta upp en omslagsbild med samma filnamnsstam som txt-filen
    (skiftlagesokansligt). Delas av GUI (singel + batch) och CLI."""
    stem = Path(txt_path).stem
    directory = Path(txt_path).parent
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        for candidate in (directory / (stem + ext),
                          directory / (stem + ext.upper())):
            if candidate.exists():
                return str(candidate)
        matches = [m for m in directory.glob("*" + ext)
                   if m.stem.lower() == stem.lower()]
        if matches:
            return str(matches[0])
    return ""


def _cover_placeholder(parent):
    """Return a Canvas widget that draws a small gray book-icon."""
    c = tk.Canvas(parent, width=32, height=42, bg="white", highlightthickness=0)
    c.create_rectangle(5, 1, 31, 41, fill="#d0d0d0", outline="#aaaaaa")
    c.create_line(10, 1, 10, 41, fill="#aaaaaa", width=2)
    c.create_text(20, 22, text="\U0001f4d6", fill="#aaaaaa",
                  font=("Segoe UI", 10))
    return c


class ConverterApp:
    def __init__(self):
        RootClass = TkinterDnD.Tk if HAS_DND else tk.Tk
        self.root = RootClass()
        self.root.title("PlainTXT-EPUB Converter")
        self.root.resizable(True, True)
        self.root.minsize(580, 660)
        self.root.configure(bg=BG)

        self.txt_path      = tk.StringVar()
        self.cover_path    = tk.StringVar()
        self.book_title    = tk.StringVar()
        self.book_author   = tk.StringVar()
        self.book_lang     = tk.StringVar(value="en")
        self.status_msg    = tk.StringVar(value="Drop a .txt file here, or click the box to browse.")
        self.auto_chapters = tk.BooleanVar(value=True)
        self.clean_lines   = tk.BooleanVar(value=True)
        self._cover_tk     = None

        # Batch mode state
        self._mode             = "single"
        self._queue            = []          # list of types.SimpleNamespace items
        self._batch_running    = False       # worker-trad aktiv — las kon
        self._batch_out_dir    = tk.StringVar()
        self._queue_canvas     = None        # set by _build_batch_ui
        self._queue_inner      = None        # inner frame for queue rows
        self._single_content_frame = None    # set by _build_ui
        self._batch_content_frame  = None    # set by _build_ui

        self._build_styles()
        self._build_ui()
        self._center(630, 720)

    def _build_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",        background=BG)
        s.configure("TLabel",        background=BG,      font=("Segoe UI", 10), foreground=TEXT_COL)
        s.configure("H1.TLabel",     background=BG,      font=("Segoe UI", 20, "bold"), foreground=TEXT_COL)
        s.configure("Sub.TLabel",    background=BG,      font=("Segoe UI", 10), foreground=MUTED)
        s.configure("Card.TLabel",   background="white", font=("Segoe UI", 10), foreground=TEXT_COL)
        s.configure("CMuted.TLabel", background="white", font=("Segoe UI", 9),  foreground=MUTED)
        s.configure("TLabelframe",   background="white")
        s.configure("TLabelframe.Label", background="white",
                    font=("Segoe UI", 10, "bold"), foreground=TEXT_COL)
        s.configure("TCheckbutton",  background="white", font=("Segoe UI", 10), foreground=TEXT_COL)
        s.configure("TEntry",        font=("Segoe UI", 10))
        s.configure("TButton",       font=("Segoe UI", 9), padding=(6, 3))
        s.configure("Big.TButton",
                    font=("Segoe UI", 13, "bold"),
                    background=ACCENT,
                    foreground="white",
                    padding=(28, 10))
        s.map("Big.TButton",
              background=[("active", ACCENT_H), ("disabled", "#aaaaaa")],
              foreground=[("disabled", "#dddddd")])

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        _app_hdr = ttk.Frame(outer)
        _app_hdr.pack(fill="x")
        ttk.Label(_app_hdr, text="PlainTXT-EPUB Converter",
                  style="H1.TLabel").pack(side="left", anchor="w")
        ttk.Button(_app_hdr, text="?", width=2,
                   command=self._show_global_help).pack(side="right", anchor="n", pady=(6, 0))
        ttk.Label(outer,
                  text="Convert plain-text ebooks to EPUB with automatic chapter detection and a table of contents.",
                  style="Sub.TLabel", wraplength=560).pack(anchor="w", pady=(2, 14))
        self._build_drop_zone(outer)

        # Clear button for single mode — shown only after a file is loaded
        self._single_clear_btn = ttk.Button(outer, text="Clear", command=self._clear_single)
        # (not packed initially)

        # Mode container — holds either single-file content or batch queue
        self._single_content_frame = ttk.Frame(outer)
        self._single_content_frame.pack(fill="x")
        self._build_metadata_card(self._single_content_frame)
        self._build_cover_card(self._single_content_frame)

        self._batch_content_frame = ttk.Frame(outer)
        self._build_batch_ui(self._batch_content_frame)
        # (not packed initially — shown only in batch mode)

        self._build_options_card(outer)
        self.convert_btn = ttk.Button(
            outer, text="Convert to EPUB",
            style="Big.TButton",
            command=self._start_convert,
        )
        self.convert_btn.pack(pady=(10, 6))
        ttk.Label(outer, textvariable=self.status_msg,
                  style="Sub.TLabel", wraplength=560).pack()
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 0))
        self.progress.pack_forget()

    def _build_drop_zone(self, parent):
        self.drop_frame = tk.Frame(parent, bg=DROP_BG, relief="solid", bd=1,
                                   cursor="hand2", height=110)
        self.drop_frame.pack(fill="x", pady=(0, 10))
        self.drop_frame.pack_propagate(False)
        self.drop_icon = tk.Label(self.drop_frame, text="[ TXT ]", bg=DROP_BG,
                                  font=("Segoe UI", 16), fg=ACCENT)
        self.drop_icon.pack(pady=(12, 0))
        hint = ("Drop one or more .txt files here   or   click to browse"
                if HAS_DND else "Click to browse for a .txt file")
        self.drop_main = tk.Label(self.drop_frame, text=hint, bg=DROP_BG,
                                  fg=ACCENT, font=("Segoe UI", 11, "bold"), cursor="hand2")
        self.drop_main.pack()
        sub_hint = ("Drop multiple files to start a batch conversion"
                    if HAS_DND else "Install tkinterdnd2 to enable drag-and-drop")
        self.drop_sub = tk.Label(self.drop_frame, text=sub_hint,
                                 bg=DROP_BG, fg=MUTED, font=("Segoe UI", 8))
        self.drop_sub.pack(pady=(1, 0))
        for w in (self.drop_frame, self.drop_icon, self.drop_main, self.drop_sub):
            w.bind("<Button-1>", lambda e: self._browse_txt())
            w.bind("<Enter>",   lambda e: self._drop_color(DROP_ACT))
            w.bind("<Leave>",   lambda e: self._drop_color(DROP_BG))
        if HAS_DND:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>",      self._on_drop)
            self.drop_frame.dnd_bind("<<DragEnter>>", lambda e: self._drop_color(DROP_ACT))
            self.drop_frame.dnd_bind("<<DragLeave>>", lambda e: self._drop_color(DROP_BG))

    def _build_metadata_card(self, parent):
        card = ttk.LabelFrame(parent, text=" Book Information ", padding=(12, 8))
        card.pack(fill="x", pady=(0, 8))
        card.columnconfigure(1, weight=1)
        for r, (lbl, var, hint) in enumerate([
            ("Title",    self.book_title,  "e.g. Pride and Prejudice"),
            ("Author",   self.book_author, "e.g. Jane Austen"),
            ("Language", self.book_lang,   "BCP-47 code: en  fr  de  es"),
        ]):
            ttk.Label(card, text=lbl + ":", style="Card.TLabel").grid(
                row=r, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(card, textvariable=var).grid(row=r, column=1, sticky="ew", pady=3)
            ttk.Label(card, text=hint, style="CMuted.TLabel").grid(
                row=r, column=2, sticky="w", padx=(8, 0))

    def _build_cover_card(self, parent):
        card = ttk.LabelFrame(parent, text=" Cover Image (optional) ", padding=(12, 8))
        card.pack(fill="x", pady=(0, 8))
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text="Image:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(card, textvariable=self.cover_path, state="readonly").grid(
            row=0, column=1, sticky="ew")
        ttk.Button(card, text="Browse...", command=self._browse_cover).grid(
            row=0, column=2, padx=(6, 0))
        ttk.Button(card, text="Clear", command=self._clear_cover).grid(
            row=0, column=3, padx=(4, 0))
        self.cover_preview = ttk.Label(card, text="No cover selected", style="CMuted.TLabel")
        self.cover_preview.grid(row=1, column=0, columnspan=4, pady=(6, 0), sticky="w")

    def _build_options_card(self, parent):
        card = ttk.LabelFrame(parent, text=" Options ", padding=(12, 8))
        card.pack(fill="x", pady=(0, 8))
        self._options_card_widget = card
        ttk.Checkbutton(
            card,
            text="Auto-detect chapters and apply headings  (generates Table of Contents)",
            variable=self.auto_chapters,
        ).pack(anchor="w")
        ttk.Checkbutton(
            card,
            text="Clean up line breaks and normalize spacing",
            variable=self.clean_lines,
        ).pack(anchor="w", pady=(4, 0))

    # Fixed pixel widths for non-expanding table columns.
    # Both header and data rows use these constants, which is what guarantees alignment.
    _COL_W = {"cover": 40, "file": 130, "lang": 44, "auto": 32, "status": 72, "remove": 34}

    def _build_batch_ui(self, parent):
        # ── Title row ──────────────────────────────────────────────────────
        hdr = ttk.Frame(parent)
        hdr.pack(fill="x", pady=(0, 4))
        ttk.Label(hdr, text="Queued files",
                  font=("Segoe UI", 10, "bold"), background=BG).pack(side="left")
        ttk.Button(hdr, text="Clear all", command=self._clear_queue).pack(side="right")
        ttk.Button(hdr, text="?", width=2,
                   command=self._show_batch_help).pack(side="right", padx=(0, 4))

        # ── Table container: tbl_frame (canvases) + scrollbar side-by-side ─
        # The scrollbar sits OUTSIDE tbl_frame so both canvases share the
        # same width, which is what makes header and data columns align.
        tbl_container = tk.Frame(parent, bg=BG)
        tbl_container.pack(fill="both", expand=True, pady=(0, 6))

        tbl_frame = tk.Frame(tbl_container, bg="white", relief="solid", bd=1)
        tbl_frame.pack(side="left", fill="both", expand=True)

        qsb = ttk.Scrollbar(tbl_container, orient="vertical")
        qsb.pack(side="right", fill="y")

        # Header canvas (fixed height, not scrollable)
        hdr_canvas = tk.Canvas(tbl_frame, bg="white", highlightthickness=0, height=26)
        hdr_canvas.pack(fill="x")
        hdr_inner = tk.Frame(hdr_canvas, bg="#f0f0f0")
        _hdr_wid = hdr_canvas.create_window((0, 0), window=hdr_inner, anchor="nw")
        hdr_canvas.bind("<Configure>",
                        lambda e, wid=_hdr_wid: hdr_canvas.itemconfig(wid, width=e.width))
        # Build header labels using same widths as data rows
        cw = self._COL_W
        _HL = {"font": ("Segoe UI", 8, "bold"), "bg": "#f0f0f0", "fg": MUTED, "anchor": "w"}
        _hdr_cov = tk.Frame(hdr_inner, width=cw["cover"], height=24, bg="#f0f0f0")
        _hdr_cov.pack(side="left")
        _hdr_cov.pack_propagate(False)

        _f_file = tk.Frame(hdr_inner, width=cw["file"], height=24, bg="#f0f0f0")
        _f_file.pack(side="left")
        _f_file.pack_propagate(False)
        _lbl_file = tk.Label(_f_file, text="File", **_HL)
        _lbl_file.pack(anchor="w")
        _add_tooltip(_lbl_file, "Source .txt filename")
        _lbl_title = tk.Label(hdr_inner, text="Title", **_HL)
        _lbl_title.pack(side="left", expand=True, fill="x")
        _add_tooltip(_lbl_title, "Book title written to EPUB metadata and table of contents")
        _lbl_author = tk.Label(hdr_inner, text="Author", **_HL)
        _lbl_author.pack(side="left", expand=True, fill="x")
        _add_tooltip(_lbl_author, "Author name written to EPUB metadata")
        _f_lang = tk.Frame(hdr_inner, width=cw["lang"], height=24, bg="#f0f0f0")
        _f_lang.pack(side="left")
        _f_lang.pack_propagate(False)
        _lbl_lang = tk.Label(_f_lang, text="Lang", **_HL)
        _lbl_lang.pack(anchor="w")
        _add_tooltip(_lbl_lang, "BCP-47 language code (en, fr, de, es, \u2026)")
        _f_auto = tk.Frame(hdr_inner, width=cw["auto"], height=24, bg="#f0f0f0")
        _f_auto.pack(side="left")
        _f_auto.pack_propagate(False)
        _lbl_auto = tk.Label(_f_auto, text="Skip", **_HL)
        _lbl_auto.pack(anchor="w")
        _add_tooltip(_lbl_auto, "Skip the chapter-review dialog for this book \u2014 all detected chapters are used automatically")
        _f_status = tk.Frame(hdr_inner, width=cw["status"], height=24, bg="#f0f0f0")
        _f_status.pack(side="left")
        _f_status.pack_propagate(False)
        _lbl_status = tk.Label(_f_status, text="Status", **_HL)
        _lbl_status.pack(anchor="w")
        _add_tooltip(_lbl_status, "Current conversion status")

        tk.Frame(hdr_inner, width=cw["remove"], height=24, bg="#f0f0f0").pack(side="left")

        # Data canvas (scrollable)
        self._queue_canvas = tk.Canvas(tbl_frame, bg="white", highlightthickness=0, height=160)
        self._queue_inner = tk.Frame(self._queue_canvas, bg="white")
        self._queue_inner.bind(
            "<Configure>",
            lambda e: self._queue_canvas.configure(scrollregion=self._queue_canvas.bbox("all")),
        )
        _inner_wid = self._queue_canvas.create_window((0, 0), window=self._queue_inner, anchor="nw")
        self._queue_canvas.bind(
            "<Configure>",
            lambda e, wid=_inner_wid: self._queue_canvas.itemconfig(wid, width=e.width),
        )
        self._queue_canvas.configure(yscrollcommand=qsb.set)
        qsb.configure(command=self._queue_canvas.yview)
        self._queue_canvas.pack(fill="both", expand=True)
        self._queue_canvas.bind(
            "<MouseWheel>",
            lambda e: self._queue_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # ── Below-table controls ────────────────────────────────────────────
        ttk.Button(parent, text="+ Add more files",
                   command=self._browse_txt).pack(anchor="w", pady=(0, 6))

        out_row = ttk.LabelFrame(parent, text=" Output Folder ", padding=(12, 8))
        out_row.pack(fill="x", pady=(0, 8))
        out_row.columnconfigure(1, weight=1)
        ttk.Label(out_row, text="Folder:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(out_row, textvariable=self._batch_out_dir, state="readonly").grid(
            row=0, column=1, sticky="ew")
        ttk.Button(out_row, text="Browse...",
                   command=self._browse_output_dir).grid(row=0, column=2, padx=(6, 0))

    # ── Mode switching ──────────────────────────────────────────────────────

    def _set_mode(self, mode):
        if self._mode == mode:
            return
        self._mode = mode
        if mode == "single":
            self._batch_content_frame.pack_forget()
            self._single_content_frame.pack(fill="x",
                                             before=self._options_card_widget)
            self.convert_btn.config(text="Convert to EPUB",
                                    command=self._start_convert)
            self.root.minsize(580, 660)
            self.status_msg.set("Drop a .txt file here, or click the box to browse.")
        else:
            self._single_content_frame.pack_forget()
            self._single_clear_btn.pack_forget()
            self._batch_content_frame.pack(fill="both", expand=True,
                                            before=self._options_card_widget)
            self.convert_btn.config(
                text="Convert All  (" + str(len(self._queue)) + " books)",
                command=self._start_batch_convert,
            )
            self.root.minsize(580, 780)
            self.status_msg.set("")

    def _update_batch_btn(self):
        if self._mode == "batch":
            self.convert_btn.config(
                text="Convert All  (" + str(len(self._queue)) + " books)")

    def _clear_single(self):
        """Reset single-mode state: unload the current file."""
        self.txt_path.set("")
        self.book_title.set("")
        self.book_author.set("")
        self.book_lang.set("en")
        self._clear_cover()
        self.drop_icon.config(text="[ TXT ]", fg=ACCENT)
        hint = ("Drop one or more .txt files here   or   click to browse"
                if HAS_DND else "Click to browse for a .txt file")
        self.drop_main.config(text=hint, fg=ACCENT, font=("Segoe UI", 11, "bold"))
        sub_hint = ("Drop multiple files to start a batch conversion"
                    if HAS_DND else "Install tkinterdnd2 to enable drag-and-drop")
        self.drop_sub.config(text=sub_hint)
        self.status_msg.set("Drop a .txt file here, or click the box to browse.")
        self._single_clear_btn.pack_forget()

    def _clear_queue(self):
        if self._batch_running:
            return
        for item in list(self._queue):
            if item.row_frame:
                item.row_frame.destroy()
        self._queue.clear()
        self._set_mode("single")
        self.status_msg.set("Drop a .txt file here, or click the box to browse.")

    # ── Batch queue management ──────────────────────────────────────────────

    def _browse_output_dir(self):
        folder = filedialog.askdirectory(title="Select output folder for EPUBs")
        if folder:
            self._batch_out_dir.set(folder)

    def _enqueue_path(self, path):
        path = path.strip('"').strip()
        if not path.lower().endswith(".txt"):
            messagebox.showwarning("Wrong file type",
                                   "Please select .txt files only:\n" + path)
            return
        if not os.path.exists(path):
            messagebox.showerror("File not found", "Cannot find:\n" + path)
            return
        if any(item.path == path for item in self._queue):
            return  # already queued

        guess_title = re.sub(r"[_\-]+", " ", Path(path).stem).strip().title()
        guess_author = ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                header = f.read(4000)
            guess_author = TextProcessor.suggest_author(header)
        except Exception:
            pass

        cover_path = find_cover(path)

        item = types.SimpleNamespace(
            path=path,
            title_var=tk.StringVar(value=guess_title),
            author_var=tk.StringVar(value=guess_author),
            lang_var=tk.StringVar(value=self.book_lang.get() or "en"),
            auto_accept=tk.BooleanVar(value=False),
            status_var=tk.StringVar(value="Pending"),
            status_label=None,
            cover_path=cover_path,
            cover_tk=None,   # PhotoImage ref — kept to prevent GC
            row_frame=None,
        )
        self._queue.append(item)
        self._add_queue_row(item)
        self._update_batch_btn()

    def _add_queue_row(self, item):
        cw = self._COL_W
        row = tk.Frame(self._queue_inner, bg="white")
        row.pack(fill="x", pady=1)

        # Cover thumbnail (fixed-width container keeps column aligned)
        cover_slot = tk.Frame(row, width=cw["cover"], height=46, bg="white")
        cover_slot.pack(side="left")
        cover_slot.pack_propagate(False)
        if HAS_PIL and item.cover_path:
            try:
                img = Image.open(item.cover_path)
                img.thumbnail((32, 44), Image.LANCZOS)
                item.cover_tk = ImageTk.PhotoImage(img)
                tk.Label(cover_slot, image=item.cover_tk, bg="white").pack(pady=1)
            except Exception:
                _cover_placeholder(cover_slot).pack(pady=1)
        else:
            _cover_placeholder(cover_slot).pack(pady=1)

        # File name (fixed-width frame container matches header pixel width)
        fname = Path(item.path).name
        if len(fname) > 20:
            fname = fname[:17] + "..."
        _f_file = tk.Frame(row, width=cw["file"], height=46, bg="white")
        _f_file.pack(side="left")
        _f_file.pack_propagate(False)
        tk.Label(_f_file, text=fname, font=("Segoe UI", 9), bg="white",
                 fg=TEXT_COL, anchor="w").pack(fill="x")

        # Title + Author entries (expand equally, matching header)
        ttk.Entry(row, textvariable=item.title_var, width=1).pack(
            side="left", expand=True, fill="x")
        ttk.Entry(row, textvariable=item.author_var, width=1).pack(
            side="left", expand=True, fill="x")

        # Lang (fixed-width frame container matches header pixel width)
        _f_lang = tk.Frame(row, width=cw["lang"], height=46, bg="white")
        _f_lang.pack(side="left")
        _f_lang.pack_propagate(False)
        ttk.Entry(_f_lang, textvariable=item.lang_var).pack(fill="x", pady=12)

        # Skip checkbox (fixed-width frame container matches header pixel width)
        _f_auto = tk.Frame(row, width=cw["auto"], height=46, bg="white")
        _f_auto.pack(side="left")
        _f_auto.pack_propagate(False)
        ttk.Checkbutton(_f_auto, variable=item.auto_accept, text="").pack()

        # Status label (fixed-width frame container matches header pixel width)
        _f_status = tk.Frame(row, width=cw["status"], height=46, bg="white")
        _f_status.pack(side="left")
        _f_status.pack_propagate(False)
        status_lbl = tk.Label(_f_status, textvariable=item.status_var,
                               font=("Segoe UI", 8), bg="white", fg=MUTED, anchor="w")
        status_lbl.pack(fill="x")
        item.status_label = status_lbl

        # Remove button (fixed-width frame container matches header pixel width)
        _f_remove = tk.Frame(row, width=cw["remove"], height=46, bg="white")
        _f_remove.pack(side="left")
        _f_remove.pack_propagate(False)
        def _remove(i=item):
            self._remove_queue_item(i)
        ttk.Button(_f_remove, text="\u2715", command=_remove).pack(fill="both")

        item.row_frame = row
        self._queue_canvas.update_idletasks()
        self._queue_canvas.configure(scrollregion=self._queue_canvas.bbox("all"))

    def _remove_queue_item(self, item):
        if self._batch_running or item not in self._queue:
            return
        self._queue.remove(item)
        if item.row_frame:
            item.row_frame.destroy()
        self._queue_canvas.configure(scrollregion=self._queue_canvas.bbox("all"))
        self._update_batch_btn()
        if not self._queue:
            self._clear_queue()

    def _set_item_status(self, item, text, color):
        item.status_var.set(text)
        if item.status_label:
            item.status_label.config(fg=color)

    # ── Batch conversion ────────────────────────────────────────────────────

    def _start_batch_convert(self):
        if not HAS_EPUB:
            messagebox.showerror(
                "Missing dependency",
                "ebooklib is not installed.\n\nRun:\n  pip install ebooklib",
            )
            return
        out_dir = self._batch_out_dir.get().strip()
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showwarning("No output folder",
                                   "Please choose an output folder first.")
            return
        if not self._queue:
            return

        self.convert_btn.config(state="disabled")
        self._batch_running = True

        # Tk-variabler far bara roras fran main-traden — snapshot per bok innan
        # workern startar (inline-redigeringar under korning ignoreras medvetet)
        jobs = [types.SimpleNamespace(
                    item=item,
                    path=item.path,
                    title=item.title_var.get(),
                    author=item.author_var.get(),
                    lang=item.lang_var.get(),
                    cover_path=item.cover_path,
                    auto_accept=item.auto_accept.get(),
                ) for item in self._queue]
        threading.Thread(
            target=self._run_batch,
            args=(jobs, out_dir, self.clean_lines.get(), self.auto_chapters.get()),
            daemon=True,
        ).start()

    def _run_batch(self, jobs, out_dir, clean, auto_ch):
        total = len(jobs)
        for idx, job in enumerate(jobs):
            item = job.item
            self._set_item_status_async(item, "Reading…", MUTED)
            self._set_status(
                "Book " + str(idx + 1) + "/" + str(total) + ": " + job.title)

            try:
                if os.path.getsize(job.path) < 5 * 1024:
                    # Skrapfiler (torrent-reklam, "read me" o.d.) — hoppa over
                    self._set_item_status_async(
                        item, "Skipped - tiny file (< 5 KB)", MUTED)
                    continue
                raw = TextProcessor.read_text_file(job.path)
                struct_warn = None
                text = TextProcessor.clean_text(raw) if clean else raw

                if auto_ch:
                    chapters = TextProcessor.detect_chapters(text)
                    struct_warn = TextProcessor.structure_warning(raw, len(chapters))
                    if not job.auto_accept:
                        self._set_item_status_async(item, "Verifying…", MUTED)
                        result = self._verify_on_main(chapters, job, idx, total)
                        if result is None:
                            self._set_item_status_async(item, "Skipped", MUTED)
                            continue
                        chapters = result or [("Content", text.strip())]
                else:
                    chapters = [("Content", text.strip())]

                safe = (re.sub(r"[^\w\s\-]", "", job.title).strip()
                        .replace(" ", "_") or "book")
                out_path = _unique_path(out_dir, safe + ".epub")

                self._set_item_status_async(item, "Building…", MUTED)
                EPUBBuilder.build(
                    title=job.title or Path(job.path).stem,
                    author=job.author or "Unknown Author",
                    language=job.lang or "en",
                    chapters=chapters,
                    cover_path=job.cover_path or None,
                    output_path=out_path,
                )
                if struct_warn:
                    self._set_item_status_async(
                        item, "⚠ Done - poor text structure", "#c77700")
                else:
                    self._set_item_status_async(item, "✓ Done", "#2a9d2a")

            except Exception as exc:
                self._set_item_status_async(item, "✗ " + str(exc)[:30], "#cc2222")

        self.root.after(0, self._batch_finished, out_dir, total)

    def _verify_on_main(self, chapters, job, idx, total):
        """Oppna ChapterVerifyDialog pa main-traden och blockera workern tills
        den stangts. Returnerar dlg.result (None = hoppa over boken)."""
        done = threading.Event()
        holder = {"result": None}

        def show():
            try:
                dlg = ChapterVerifyDialog(self.root, chapters,
                                          book_title=job.title,
                                          book_index=idx + 1,
                                          total_books=total,
                                          cover_path=job.cover_path)
                holder["result"] = dlg.result
            finally:
                done.set()

        self.root.after(0, show)
        done.wait()
        return holder["result"]

    def _set_item_status_async(self, item, text, color):
        self.root.after(0, self._set_item_status, item, text, color)

    def _batch_finished(self, out_dir, total):
        self._batch_running = False
        self.convert_btn.config(state="normal")
        done = sum(1 for i in self._queue
                   if i.status_var.get().startswith(("✓", "⚠ Done")))
        self.status_msg.set(
            "Batch complete: " + str(done) + "/" + str(total)
            + " converted.  Output: " + out_dir
        )
        if total > 0:
            self._show_batch_summary(done, total, out_dir)

    def _show_global_help(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Help \u2014 PlainTXT-EPUB Converter")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.configure(bg=BG)
        sections = [
            ("Converting a single book",
             "Drop one .txt file onto the drop zone, or click the zone to browse.\n"
             "Fill in Title, Author, and Language (optional \u2014 auto-detected where possible).\n"
             "Optionally add a cover image (.jpg/.png).\n"
             "Click \u2018Convert to EPUB\u2019. If chapter detection is on, a review dialog appears first."),
            ("Converting multiple books (batch)",
             "Drop two or more .txt files at once, or drop files one-by-one.\n"
             "The table shows each queued book. Edit titles/authors inline.\n"
             "Choose an output folder, then click \u2018Convert All\u2019.\n"
             "A chapter-review dialog appears for each book unless \u2018Skip\u2019 is checked."),
            ("Options",
             "Detect chapters \u2014 Scans the text for chapter headings and builds a\n"
             "  Table of Contents in the EPUB. When off, the whole book is one section.\n\n"
             "Clean up line breaks \u2014 Joins soft-wrapped lines (common in plain-text\n"
             "  files) and normalises paragraph spacing."),
            ("Table columns (batch mode)",
             "Skip \u2014 Check to bypass the chapter-review dialog for that book;\n"
             "  all detected chapters are used automatically.\n\n"
             "Cover \u2014 Auto-detected if a .jpg/.png with the same filename exists\n"
             "  in the same folder as the .txt file.\n\n"
             "Lang \u2014 BCP-47 language code written to the EPUB (en, fr, de, es, \u2026)."),
        ]
        body = tk.Frame(dlg, bg=BG)
        body.pack(fill="x", padx=20, pady=(14, 6))
        for heading, text in sections:
            tk.Label(body, text=heading,
                     font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT_COL,
                     anchor="w").pack(fill="x", pady=(8, 2))
            tk.Label(body, text=text,
                     font=("Segoe UI", 9), bg=BG, fg=MUTED,
                     anchor="w", justify="left", wraplength=400).pack(fill="x", padx=(12, 0))
        ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=(6, 14))
        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry(f"+{px + (pw - dw)//2}+{py + (ph - dh)//2}")

    def _show_batch_help(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Column Guide")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.configure(bg=BG)
        ttk.Label(dlg, text="Batch Queue \u2014 Column Guide",
                  font=("Segoe UI", 11, "bold"),
                  background=BG, foreground=TEXT_COL).pack(anchor="w", padx=16, pady=(14, 6))
        col_rows = [
            ("Cover",  "Book cover image. Auto-detected if a .jpg/.png with the\nsame filename exists in the source folder."),
            ("File",   "Source .txt filename."),
            ("Title",  "Book title written to EPUB metadata and table of contents."),
            ("Author", "Author name written to EPUB metadata."),
            ("Lang",   "BCP-47 language code used in the EPUB (en, fr, de, es, \u2026)."),
            ("Skip",   "When checked, skips the chapter-review dialog for this\nbook. All detected chapters are used automatically."),
            ("Status", "Current conversion status: Pending, Verifying,\nConverting, Done, or Skipped."),
        ]
        body = tk.Frame(dlg, bg=BG)
        body.pack(fill="x", padx=16, pady=(0, 10))
        for col, desc in col_rows:
            r = tk.Frame(body, bg=BG)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=col, width=8, anchor="w",
                     font=("Segoe UI", 9, "bold"), bg=BG, fg=TEXT_COL).pack(side="left")
            tk.Label(r, text=desc, anchor="w", justify="left",
                     font=("Segoe UI", 9), bg=BG, fg=MUTED,
                     wraplength=340).pack(side="left", padx=(6, 0))
        ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=(0, 14))
        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry(f"+{px + (pw - dw)//2}+{py + (ph - dh)//2}")

    def _show_batch_summary(self, done, total, out_dir):
        skipped = total - done
        dlg = tk.Toplevel(self.root)
        dlg.title("Batch Complete")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.configure(bg=BG)

        ttk.Label(dlg, text="Batch Complete",
                  font=("Segoe UI", 13, "bold"),
                  background=BG, foreground=TEXT_COL).pack(anchor="w", padx=20, pady=(14, 8))

        card = tk.Frame(dlg, bg="white", relief="solid", bd=1)
        card.pack(fill="x", padx=20, pady=(0, 10))
        card.columnconfigure(1, weight=1)

        def stat_row(r, lbl, val, color=TEXT_COL):
            tk.Label(card, text=lbl, font=("Segoe UI", 9), bg="white",
                     fg=MUTED, anchor="w").grid(row=r, column=0, sticky="w", padx=12, pady=3)
            tk.Label(card, text=val, font=("Segoe UI", 9, "bold"), bg="white",
                     fg=color, anchor="w").grid(row=r, column=1, sticky="w", padx=6, pady=3)

        stat_row(0, "Books converted:", str(done) + " of " + str(total),
                 "#2a9d2a" if done == total else "#c07a00")
        if skipped:
            stat_row(1, "Errors / skipped:", str(skipped), "#cc2222")
        stat_row(2 if skipped else 1, "Output folder:", out_dir)

        br = tk.Frame(dlg, bg=BG)
        br.pack(fill="x", padx=20, pady=(0, 14))
        ttk.Button(br, text="Open folder",
                   command=lambda: os.startfile(out_dir)).pack(side="left")
        ttk.Button(br, text="Close",
                   command=dlg.destroy).pack(side="right")

        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        dw, dh = 460, 220 + (30 if skipped else 0)
        dlg.geometry(str(dw) + "x" + str(dh) + "+"
                     + str(px + (pw - dw) // 2) + "+" + str(py + (ph - dh) // 2))

    def _drop_color(self, color):
        for w in (self.drop_frame, self.drop_icon, self.drop_main, self.drop_sub):
            w.config(bg=color)

    def _on_drop(self, event):
        self._drop_color(DROP_BG)
        paths = _expand_paths(_parse_drop_paths(event.data))
        if not paths:
            return
        if len(paths) == 1 and self._mode == "single":
            self._load_txt(paths[0])
        else:
            # Carry any existing single-file into the queue first
            if self._mode == "single" and self.txt_path.get():
                self._enqueue_path(self.txt_path.get())
            for p in paths:
                self._enqueue_path(p)
            self._set_mode("batch")

    def _browse_txt(self):
        paths = filedialog.askopenfilenames(
            title="Select .txt ebook(s)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not paths:
            return
        paths = list(paths)
        if len(paths) == 1 and self._mode == "single":
            self._load_txt(paths[0])
        else:
            if self._mode == "single" and self.txt_path.get():
                self._enqueue_path(self.txt_path.get())
            for p in paths:
                self._enqueue_path(p)
            self._set_mode("batch")

    def _load_txt(self, path):
        path = path.strip('"')
        if not path.lower().endswith(".txt"):
            messagebox.showwarning("Wrong file type", "Please select a .txt file.")
            return
        if not os.path.exists(path):
            messagebox.showerror("File not found", "Cannot find:\n" + path)
            return
        self.txt_path.set(path)
        name = Path(path).name
        size_kb = os.path.getsize(path) // 1024
        self.drop_icon.config(text="[OK]", fg="#2a9d2a")
        self.drop_main.config(text=name, fg=TEXT_COL, font=("Segoe UI", 10, "bold"))
        self.drop_sub.config(text="Click to change file")
        # Reset all book-specific fields for the new file
        self.book_author.set("")
        self._clear_cover()
        guess = re.sub(r"[_\-]+", " ", Path(path).stem).strip().title()
        self.book_title.set(guess)
        # Try to auto-detect author from file header
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as _f:
                _header = _f.read(4000)
            _author = TextProcessor.suggest_author(_header)
            if _author:
                self.book_author.set(_author)
        except Exception:
            pass
        self.status_msg.set("Ready  |  " + name + "  (" + str(size_kb) + " KB)")
        # Show clear button (pack_forget first to avoid duplicate placement on reload)
        self._single_clear_btn.pack_forget()
        self._single_clear_btn.pack(anchor="e", pady=(0, 4),
                                    before=self._single_content_frame)
        # Auto-detect a cover image with the same stem in the same directory
        if not self.cover_path.get():
            _cover = find_cover(path)
            if _cover:
                self._load_cover(_cover)

    def _browse_cover(self):
        path = filedialog.askopenfilename(
            title="Select a cover image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.gif *.webp"), ("All files", "*.*")],
        )
        if path:
            self._load_cover(path)

    def _load_cover(self, path):
        self.cover_path.set(path)
        if HAS_PIL:
            try:
                img = Image.open(path)
                img.thumbnail((60, 90), Image.LANCZOS)
                self._cover_tk = ImageTk.PhotoImage(img)
                self.cover_preview.config(image=self._cover_tk,
                                          text="  " + Path(path).name,
                                          compound="left")
                return
            except Exception:
                pass
        self.cover_preview.config(image="", text=Path(path).name)

    def _clear_cover(self):
        self.cover_path.set("")
        self._cover_tk = None
        self.cover_preview.config(image="", text="No cover selected")

    def _start_convert(self):
        if not HAS_EPUB:
            messagebox.showerror(
                "Missing dependency",
                "ebooklib is not installed.\n\nRun:\n  pip install ebooklib",
            )
            return
        txt = self.txt_path.get()
        if not txt:
            messagebox.showwarning("No file selected",
                                   "Please select or drop a .txt file first.")
            return
        title  = self.book_title.get().strip()  or Path(txt).stem
        author = self.book_author.get().strip()  or "Unknown Author"
        lang   = self.book_lang.get().strip()    or "en"
        cover  = self.cover_path.get().strip()   or None

        # Read, clean, detect on main thread so dialog can run synchronously
        self.status_msg.set("Reading file...")
        self.root.update()
        raw_text = TextProcessor.read_text_file(txt)
        raw_cc = sum(1 for c in raw_text if not c.isspace())
        text = raw_text
        if self.clean_lines.get():
            self.status_msg.set("Cleaning text...")
            self.root.update()
            text = TextProcessor.clean_text(text)
        if self.auto_chapters.get():
            self.status_msg.set("Detecting chapters...")
            self.root.update()
            chapters = TextProcessor.detect_chapters(text)
            warning = TextProcessor.structure_warning(raw_text, len(chapters))
            if warning:
                messagebox.showwarning("No chapter structure", warning)
            dlg = ChapterVerifyDialog(self.root, chapters)
            if dlg.result is None:
                self.status_msg.set("Cancelled.")
                return
            chapters = dlg.result
            if not chapters:
                messagebox.showwarning(
                    "No chapters selected",
                    "All chapters were deselected. Please keep at least one.",
                )
                self.status_msg.set("Cancelled.")
                return
        else:
            chapters = [("Content", text.strip())]

        chapter_cc = sum(
            sum(1 for c in body if not c.isspace()) for _, body in chapters
        )
        safe = re.sub(r"[^\w\s\-]", "", title).strip().replace(" ", "_")
        out = filedialog.asksaveasfilename(
            title="Save EPUB as...",
            defaultextension=".epub",
            initialfile=safe + ".epub",
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
        )
        if not out:
            self.status_msg.set("Cancelled.")
            return
        self.convert_btn.config(state="disabled")
        self.progress.pack(fill="x", pady=(6, 0))
        self.progress.start(12)
        self.status_msg.set("Building EPUB...")
        threading.Thread(
            target=self._run_build,
            args=(title, author, lang, cover, chapters, out, raw_cc, chapter_cc),
            daemon=True,
        ).start()

    def _run_build(self, title, author, lang, cover, chapters, out, raw_cc, chapter_cc):
        try:
            EPUBBuilder.build(
                title=title, author=author, language=lang,
                chapters=chapters, cover_path=cover, output_path=out,
            )
            self.root.after(0, self._on_done, out, len(chapters), raw_cc, chapter_cc)
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc))

    def _set_status(self, msg):
        self.root.after(0, lambda: self.status_msg.set(msg))

    def _on_done(self, out, n, raw_cc, chapter_cc):
        self.progress.stop()
        self.progress.pack_forget()
        self.convert_btn.config(state="normal")
        self.status_msg.set("Done!  Saved to: " + out)
        self._show_summary(out, n, raw_cc, chapter_cc)

    def _show_summary(self, out, n, raw_cc, chapter_cc):
        pct = (chapter_cc / raw_cc * 100) if raw_cc else 100.0
        if pct >= 98:
            status_text = "Conversion looks complete."
            status_color = "#2a9d2a"
            status_label = "OK"
        elif pct >= 90:
            status_text = "Some text may have been omitted — check chapter selection."
            status_color = "#c07a00"
            status_label = "Warning"
        else:
            status_text = "Significant text loss — consider reconverting."
            status_color = "#cc2222"
            status_label = "Warning"

        dlg = tk.Toplevel(self.root)
        dlg.title("Conversion Summary")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg=BG)

        ttk.Label(dlg, text="Conversion Summary",
                  font=("Segoe UI", 13, "bold"),
                  background=BG, foreground=TEXT_COL).pack(anchor="w", padx=20, pady=(14, 8))

        card = tk.Frame(dlg, bg="white", relief="solid", bd=1)
        card.pack(fill="x", padx=20, pady=(0, 10))
        card.columnconfigure(1, weight=1)

        def stat_row(r, lbl, val):
            tk.Label(card, text=lbl, font=("Segoe UI", 9), bg="white",
                     fg=MUTED, anchor="w").grid(row=r, column=0, sticky="w", padx=12, pady=3)
            tk.Label(card, text=val, font=("Segoe UI", 9, "bold"), bg="white",
                     fg=TEXT_COL, anchor="w").grid(row=r, column=1, sticky="w", padx=6, pady=3)

        plural = "s" if n != 1 else ""
        stat_row(0, "Input text:", "{:,} chars (non-whitespace)".format(raw_cc))
        stat_row(1, "Chapters built:", str(n) + " chapter" + plural)
        stat_row(2, "EPUB body text:", "{:,} chars".format(chapter_cc))
        stat_row(3, "Total text kept:", "{:.1f}%".format(pct))

        sr = tk.Frame(dlg, bg=BG)
        sr.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(sr, text=status_label + ":  " + status_text,
                 font=("Segoe UI", 9), bg=BG, fg=status_color,
                 wraplength=380, anchor="w").pack(side="left")

        br = tk.Frame(dlg, bg=BG)
        br.pack(fill="x", padx=20, pady=(0, 14))
        ttk.Button(br, text="Open folder",
                   command=lambda: os.startfile(os.path.dirname(out))).pack(side="left")
        ttk.Button(br, text="Close",
                   command=dlg.destroy).pack(side="right")

        dlg.update_idletasks()
        pw, ph = self.root.winfo_width(), self.root.winfo_height()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        dw, dh = 460, 280
        dlg.geometry(str(dw) + "x" + str(dh) + "+"
                     + str(px + (pw - dw) // 2) + "+" + str(py + (ph - dh) // 2))

    def _on_error(self, msg):
        self.progress.stop()
        self.progress.pack_forget()
        self.convert_btn.config(state="normal")
        self.status_msg.set("Error: " + msg)
        messagebox.showerror("Conversion failed", "An error occurred:\n\n" + msg)

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(
            str(w) + "x" + str(h) + "+" + str((sw - w) // 2) + "+" + str((sh - h) // 2))

    def run(self):
        self.root.mainloop()


def _unique_path(folder, filename):
    """Return folder/filename, appending _2, _3 … if the path already exists."""
    base = Path(folder) / filename
    if not base.exists():
        return str(base)
    stem = base.stem
    suffix = base.suffix
    n = 2
    while True:
        candidate = Path(folder) / (stem + "_" + str(n) + suffix)
        if not candidate.exists():
            return str(candidate)
        n += 1


def _parse_drop_paths(data):
    """Parse tkinterdnd2 drop data into a list of file paths.

    Multiple files are space-separated; paths with spaces are brace-quoted:
      {C:\\path with space\\a.txt} C:\\simple.txt
    """
    paths = []
    data = data.strip()
    i = 0
    while i < len(data):
        if data[i] == "{":
            j = data.find("}", i)
            if j == -1:
                paths.append(data[i + 1:])
                break
            paths.append(data[i + 1:j])
            i = j + 1
        else:
            j = data.find(" ", i)
            if j == -1:
                paths.append(data[i:])
                break
            paths.append(data[i:j])
            i = j
        while i < len(data) and data[i] == " ":
            i += 1
    return [p for p in paths if p]


def _expand_paths(paths):
    """Expand directories RECURSIVELY to contained .txt files; silently
    drop non-.txt files. Dedupe preserves first-seen order."""
    result = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                for name in sorted(names):
                    if name.lower().endswith(".txt"):
                        result.append(os.path.join(root, name))
        elif p.lower().endswith(".txt"):
            result.append(p)
    return list(dict.fromkeys(result))


def _check_deps():
    ok = True
    if not HAS_TK:
        print("ERROR: tkinter is required for the GUI. "
              "Use cli.py for headless conversion.")
        ok = False
    if not HAS_EPUB:
        print("ERROR: ebooklib is required.  Run: pip install ebooklib")
        ok = False
    if not HAS_PIL:
        print("Note: Pillow not installed (cover image resizing disabled). Run: pip install Pillow")
    if not HAS_DND:
        print("Note: tkinterdnd2 not installed (drag-and-drop disabled). Run: pip install tkinterdnd2")
    return ok


if __name__ == "__main__":
    if _check_deps():
        ConverterApp().run()
