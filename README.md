# PlainTXT-EPUB Converter — v0.1.0 beta

A desktop application for converting plain-text ebooks to EPUB format, with automatic chapter detection and a scrollable batch queue.

## System requirements

- Windows 10 or 11, 64-bit
- No Python installation needed — the pre-built release is self-contained

## Download & run

1. Download the `PlainTXT-EPUB Converter` folder from the [Releases](https://github.com/D4H4/plaintxt-epub/releases) page.
2. Copy the folder anywhere on your machine (Desktop, Documents, etc.).
3. Double-click `PlainTXT-EPUB Converter.exe` to launch.

> The folder must stay intact — the exe loads its dependencies from the `_internal`
> sub-folder next to it. Do not move the exe out of the folder on its own.

## Feedback & issues

Bug reports and suggestions are welcome on the [GitHub Issues page](https://github.com/D4H4/plaintxt-epub/issues).

## Requirements

| Package | Purpose | Required? |
|---|---|---|
| `ebooklib` | EPUB generation | Yes |
| `tkinterdnd2` | Drag-and-drop support | Optional |
| `Pillow` | Cover image thumbnails | Optional |

Install all at once:
```
pip install ebooklib tkinterdnd2 Pillow
```

## Usage

```
python converter.py
```

### Single book

1. Drop a `.txt` file onto the drop zone, or click the zone to browse.
2. Fill in **Title**, **Author**, and **Language** (auto-detected where possible).
3. Optionally add a cover image (`.jpg` / `.png`).
4. Click **Convert to EPUB**.
5. If chapter detection is on, a review dialog appears — uncheck any false positives, then confirm.
6. A summary dialog shows character-count stats after a successful conversion.

### Batch mode

Triggered automatically when two or more files are loaded.

1. Drop two or more `.txt` files at once, drop a folder (all `.txt` files inside are imported), or add files one by one until two are queued. Non-`.txt` files in a mixed drop or folder are silently ignored.
2. Edit titles, authors, and language codes inline in the table.
3. Select an output folder.
4. Click **Convert All**.
5. A chapter-review dialog appears for each book in sequence, unless **Skip** is checked for that row.
6. A summary dialog shows done / total counts and an **Open folder** button when finished.

## Options

| Option | Description |
|---|---|
| **Detect chapters** | Scans the text for chapter headings and builds a Table of Contents in the EPUB. When off, the whole book becomes a single section. |
| **Clean up line breaks** | Joins soft-wrapped lines (common in plain-text files) and normalises paragraph spacing. |

## Batch table columns

Columns appear left to right in this order:

| Column | Description |
|---|---|
| **Cover** | Thumbnail of the cover image. Auto-detected if a `.jpg` or `.png` with the same base filename exists in the same folder as the `.txt` file. A gray book-icon placeholder is shown when no cover is found. |
| **File** | Source filename. |
| **Title / Author** | Editable inline. |
| **Lang** | BCP-47 language code written into the EPUB (`en`, `fr`, `de`, `es`, …). |
| **Skip** | When checked, bypasses the chapter-review dialog for that book. All detected chapters are used automatically. |
| **Status** | Shows progress or result for each book. |

Hover over any column header for a tooltip. Click **?** next to the table header for a full column guide.

## Global help

Click **?** in the top-right of the app header for an overview covering single conversion, batch conversion, options, and table columns.

## Chapter detection

`TextProcessor.is_chapter_heading` uses a layered heuristic:

1. Lines longer than 100 characters are rejected.
2. The line must be surrounded by blank lines.
3. Explicit patterns match immediately: `Chapter N`, `Part N`, `Book N`, `Prologue`, `Epilogue`, `Introduction`, `Preface`, `Foreword`, `Afterword`, `Appendix`, `Conclusion`, numbered headings (`1. Title`), Roman-numeral headings (`IV. Title`).
4. Lines with only single-character alpha tokens (e.g. `O O O O`) are rejected.
5. Lines starting with a quote character are rejected (dialogue).
6. Lines ending with `?` or `!` are rejected.
7. ALL-CAPS lines ending with `.` and three or fewer words are rejected (closing signatures like `S. VERNON.`).
8. ALL-CAPS lines of three or more characters are accepted as headings.
9. Speaker-colon patterns (`Smith: ...`) are rejected.
10. Title-case lines of 2–8 words with no comma and not ending with `.` are accepted.

## Line-break cleaning

`clean_text` uses **page-width detection**: it computes the 90th-percentile line length of the source file and joins lines that end near that width (soft-wrapped lines), while preserving intentional short breaks (dialogue, verse, paragraph ends). This is more reliable than punctuation-based heuristics.

Line-ending normalisation order: `\r\r\n` first, then `\r\n`, then lone `\r` — handles Gutenberg-derived files that use `\r\r\n` as a line artifact.

Double hyphens (`--`) are converted to em dashes (`—`) during cleaning.

## Known limitations

- **Windows only** — the pre-built exe targets Windows 10/11 x64. Running from source works on any OS that supports tkinter.
- **Play-format texts** — books structured as scripts (e.g. Shakespeare plays) produce a large number of speaker-name false chapter headings. Use the chapter-review dialog to uncheck them, or disable chapter detection for those files.
- **Folder drag-and-drop** — imports only the immediate `.txt` children of the dropped folder, not sub-folders.

## Output

- EPUB files are named from the sanitised book title.
- If a file with the same name already exists in the output folder, a numeric suffix is appended automatically (`Book.epub`, `Book (2).epub`, …).
- Single-mode output folder is chosen via a save dialog. Batch-mode output folder is chosen once for the whole queue.

## File structure

```
converter.py          Main application (single file)
test_converter.py     Automated test suite
Sample txt files/     Sample books used for testing
```

## Running tests

```
cd "Epub converter"
python test_converter.py
```

Expected result: `OVERALL: WARN` (no FAILs). A small number of WARNs are inherent to specific source formats (Shakespeare plays, certain Gutenberg artifacts) and are not regressions.

## Building from source

Requires Python 3.12+ with Anaconda and PyInstaller installed.

Before building, open `converter.spec` and update the `_ANACONDA_BIN` path to match your Anaconda installation:

```python
_ANACONDA_BIN = r'C:\Users\YourName\anaconda3\Library\bin'
```

Then run:

```
build.bat
```

Output lands in `%TEMP%\pyinstaller-epub-output\PlainTXT-EPUB Converter\`. Copy that folder wherever you want to run or distribute the app from.
