#!/usr/bin/env python3
"""Fas 0.5: delad epub-extraktion for matskripten — laser spine-ordning ur OPF
och plockar rubriker (h1–h6) och stycken (<p>) ur varje dokument, stdlib only."""
import re
import zipfile
import posixpath
import unicodedata
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])


class _DocParser(HTMLParser):
    """Samlar (tag, text) for rubriker och 'p' for stycken i dokumentordning.
    Versblock (<div class="pgmonospaced">, PG:s poesimarkup med <br/>-radbryt)
    splittas pa blankrad — varje strof blir ett 'p'-item."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []  # lista av (tag, text) — tag ar 'h1'..'h6' eller 'p'
        self._stack = []  # (tag, textdelar) for oppna element vi samlar
        self._skip = 0  # djup inne i script/style
        self._pre_depth = 0  # div-djup inne i pgmonospaced-block
        self._pre_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif self._pre_depth:
            if tag == "div":
                self._pre_depth += 1
            elif tag == "br":
                self._pre_parts.append("\n")
        elif tag == "div" and "pgmonospaced" in dict(attrs).get("class", ""):
            self._pre_depth = 1
            self._pre_parts = []
        elif tag in HEADING_TAGS or tag == "p":
            self._stack.append((tag, []))
        elif tag == "br" and self._stack:
            self._stack[-1][1].append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif self._pre_depth:
            if tag == "div":
                self._pre_depth -= 1
                if not self._pre_depth:
                    self._flush_pre()
        elif self._stack and tag == self._stack[-1][0]:
            open_tag, parts = self._stack.pop()
            text = re.sub(r"\s+", " ", "".join(parts)).strip()
            if text:
                self.items.append((open_tag, text))

    def handle_data(self, data):
        if self._skip:
            return
        if self._pre_depth:
            self._pre_parts.append(data)
        elif self._stack:
            self._stack[-1][1].append(data)

    def _flush_pre(self):
        lines = [l.strip() for l in "".join(self._pre_parts).split("\n")]
        stanza = []
        for line in lines + [""]:
            if line:
                stanza.append(line)
            elif stanza:
                self.items.append(("p", " ".join(stanza)))
                stanza = []


def _spine_hrefs(z):
    """Dokument-hrefs i lasordning enligt OPF:ens spine."""
    container = z.read("META-INF/container.xml")
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    opf_path = ET.fromstring(container).find(".//c:rootfile", ns).get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = ET.fromstring(z.read(opf_path))
    ons = {"o": "http://www.idpf.org/2007/opf"}
    manifest = {
        item.get("id"): item.get("href")
        for item in opf.findall(".//o:manifest/o:item", ons)
    }
    hrefs = []
    for ref in opf.findall(".//o:spine/o:itemref", ons):
        href = manifest.get(ref.get("idref"))
        if href:
            hrefs.append(posixpath.normpath(posixpath.join(opf_dir, href)))
    return hrefs


def extract(epub_path):
    """Returnerar (headings, paragraphs) ur epuben i lasordning.
    headings: lista av (tag, text); paragraphs: lista av text."""
    headings, paragraphs = [], []
    with zipfile.ZipFile(epub_path) as z:
        for href in _spine_hrefs(z):
            if not href.lower().endswith((".html", ".xhtml", ".htm")):
                continue
            parser = _DocParser()
            parser.feed(z.read(href).decode("utf-8", errors="replace"))
            for tag, text in parser.items:
                if tag == "p":
                    paragraphs.append(text)
                else:
                    headings.append((tag, text))
    return headings, paragraphs


def norm_title(s):
    """Tolerant rubriknormalisering (larvdom RSR: interpunktion varierar i
    kallorna) — casefold + slopa allt utom bokstaver/siffror."""
    s = unicodedata.normalize("NFKC", s)
    return "".join(c for c in s.casefold() if c.isalnum())


def norm_para(s):
    """Styckenormalisering: typografi (citattecken, tankstreck, radbryt)
    ska inte paverka jamforelsen — behall bara bokstaver/siffror."""
    s = unicodedata.normalize("NFKC", s)
    return "".join(c for c in s.casefold() if c.isalnum())
