# Utvärderingsramverk (Fas 0.5)

Mäter konverteringskvalitet mot golden set i `eval/golden/` (gitignorad —
innehåller upphovsrättsskyddat material; PG-paren går att tanka om från
Project Gutenberg, samma utgåva som txt:n).

## Skript

| Skript | Vad |
|---|---|
| `eval_chapters.py` | Kapitel-P/R/F1: `detect_chapters` mot `*.chapters-facit.txt`. Flagga `-v` listar missade/falska rubriker. |
| `eval_paragraphs.py` | Stycke-P/R/F1: `clean_text`-stycken mot PG-epubens `<p>` (+ strofer ur `pgmonospaced`-versblock). Multiset-matchning på normaliserat innehåll — fel styckegräns straffar både split och join. `-v` visar exempel. |
| `make_chapter_facit.py` | Skriver facit-UTKAST (`*.chapters-draft.txt`) från epub-rubriker (h1–h6) för manuell kuratering till `*.chapters-facit.txt`. |
| `epub_extract.py` | Delad epub-extraktion (spine-ordning ur OPF, rubriker, stycken, strofer). Stdlib only. |
| `corpus_diag.py` | Korpusdiagnostik: kör pipelinen över hela Drive-samlingen → `corpus_results.csv` + rapport. |
| `diag_headings.py` | Engångsundersökning av rubrikformat i korpusens detekteringsmissar. |
| `stress_test.py` | Snabbtest av pjäsexplosionen på `samples/hamlet.txt`. |

`samples/` innehåller public domain-texter för diagnostik (Drive-korpusens utgåvor,
skiljer sig från PG-paren i `golden/`).

Körning: `python eval/eval_chapters.py` från repo-roten (inga beroenden utöver stdlib).

## Facit

- `<bok>.chapters-facit.txt` — en kapitelrubrik per rad i läsordning.
  Kurateringsprincip för PG-paren: PG-epubens rubrikstruktur är referensen,
  minus boilerplate (PG-header, licens, Contents, halvtitlar, bylines).
  P&P: illustrationstexter bortklippta ur rubrikerna. RSR: manuellt facit
  ur pappersboken/txt:n.
- Kapitelträff: normaliserade titlar lika ELLER prediktionens tokens är
  prefix av facit-tokens (epub-facit slår ofta ihop rubrik + undertitel).
  Matchning i läsordning (LCS).

## Känt brus (accepterat)

- Rubrikrader ligger kvar som stycken i predikterad text men är exkluderade
  (h-taggar) ur styckefacit; PG-boilerplate skiljer något mellan txt och epub.
- Hamlet-styckesiffran domineras av versdialog (epub: `<p>` per replik) —
  det är dialog/vers-dimensionen, mäts medvetet här tills separat mätning finns.

## Baseline 2026-07-18 (att slå i Fas 1)

Kapitel (P/R/F1): C&P 0.932/0.837/0.882 · Dracula 0.261/0.429/0.324 ·
Hamlet 0.150/0.222/0.179 · Leaves 0.906/0.332/0.485 · P&P 0.827/1.000/0.905 ·
RSR 0.012/0.095/0.021 · **TOTALT 0.369/0.427/0.396**

Stycken (P/R/F1): C&P 0.875/0.943/0.908 · Dracula 0.812/0.938/0.870 ·
Hamlet 0.044/0.154/0.068 · Leaves 0.561/0.368/0.445 · P&P 0.752/0.946/0.838 ·
**TOTALT 0.556/0.555/0.555**

## Fas 1-logg

| Sprint | Ändring | Kapitel totalt | Stycken totalt |
|---|---|---|---|
| Baseline | — | 0.369/0.427/0.396 | 0.556/0.555/0.555 |
| 1 | Gutenberg-stripper (moderna \*\*\*-markörer + 90-tals-Etext); facit-sidan PG-filtrerad symmetriskt | 0.375/0.427/0.400 | 0.563/0.554/0.559 |
| 2 | Pjäsfixen: ACT/SCENE-mönster, upprepnings-undertryckning (≥ 3, explicit-mönster skyddade), avvisa `[`/`(`-rader och ALL-CAPS med komma | 0.817/0.511/0.629 | 0.563/0.554/0.559 |

| 3 | `N - Titel`-mönster + dominant-undertryckning (icke-explicita kandidater stryks när explicita ≥ 10 st och ≥ 60 %) | 0.946/0.535/0.683 | 0.563/0.554/0.559 |

| 4 | Avdelarsidor (explicit rubrik utan brödtext behålls; svit ≥ 3 = TOC → släng), ensam romersk siffra som mönster, egen titelregel (apostrofer/funktionsord) + fem avvisningar (kolumnlayout, sidnummer, scenanvisningar, talarcues, `;`/`:`) | 0.910/0.817/0.861 | 0.563/0.554/0.559 |

Sprint 4 per bok (kapitel-F1): C&P 0.990 (PART-avdelarna + epilogens I/II),
Leaves 0.485→0.801 (recall 0.33→0.73 — titelregeln), Dracula 0.931,
Hamlet 0.926 (akterna återtagna som avdelarsidor). P&P/RSR oförändrade
efter avvisningsreglerna (titelregeln läckte först: P&P→0.667, verken→1940;
kolumnlayout/sidnummer/scenanvisnings-avvisningarna tog tillbaka allt).

Sprint 3 per bok (kapitel-F1): RSR 0.614→0.930, P&P 0.919→**1.000**,
Dracula 0.667→0.947, C&P-P →1.000. Kostnad: Hamlet-R −2 (Dramatis Personæ,
"SCENE. Elsinore." — icke-explicita), Dracula-R −1 ("NOTE").
Andelskravet skyddar Leaves (25 % explicit → orörd). Corpus-Hamlet 27 exakt.

Sprint 2 per bok (kapitel-F1): Hamlet 0.185→0.778 (27 pred mot 27 facit),
Dracula 0.333→0.667 (undertitel-suppressionen ger bare "CHAPTER N" rätt titel),
RSR 0.021→0.614 (upprepade + komma-markörer borta; resten sprint 3).
Corpus-Hamlet 1137→38 kapitel, samlade verken 772→1022 (nu äkta akter/scener,
tidigare talarnamn) — båda regressionslåsta i testsviten.
Kvarvarande skräp: 1994 års Complete Works-header (eget markörformat, parkerad).

Sprint 1 syns mest utanför totalen: C&P kapitel-P 0.932→0.976, P&P F1 0.905→0.925,
Notes from the Underground 19→10 kapitel (licensskräpet borta). Testsvitens
char-preservation mäter nu mot strippad baseline (avsiktlig borttagning ≠ förlust).
