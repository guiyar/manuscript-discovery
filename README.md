# Manuscript Discovery

Set any contiguous passage of an [eBible.org](https://ebible.org) text as a
clean manuscript for [Manuscript
Discovery](https://fionapfennigwerth.info/manuscript-discovery/) study: no
chapter or verse numbers, no headings, no footnotes, nothing added to the text.
Only a title (the passage reference), page numbers and line numbers, with room
around the text for notes. Output is a typeset PDF or plain text, optionally
with a second translation in a parallel column.

## Quick start (Nix)

```sh
git add -A                  # flakes only see git-tracked files
nix develop                 # Python, Typst and fonts, all pinned
python -m manuscript_discovery ingest ~/ebible   # a folder of *_usfx.zip files; re-run any time
python -m manuscript_discovery                   # http://127.0.0.1:8000
pytest
```

## Getting texts

Download the **USFX** zip of each translation (`<id>_usfx.zip`, linked from its
eBible page) into one folder and run `ingest` on the folder. Everything else is
read from inside each zip:

| Read from | Used for |
|---|---|
| `*_usfx.xml` | the text, its paragraph and poetry markup, and the translation's own book names |
| `*metadata.xml` (DBL) | name, abbreviation, language, script, direction, country, copyright statement |
| `*VernacularAdditional.xml` | the one-line licence notice, when the statement's first line is long |

Nothing is kept in a hand-maintained list. Fonts, hyphenation language and text
direction are derived from the language and script in the metadata. Every
metadata field is optional: a zip without the files (or with a differently
shaped one) still ingests, using its id as the name and omitting the copyright
notice.

`ingest` skips files whose SHA-256 is unchanged, parses changed ones in parallel
(`-j`), and replaces each translation in a single transaction, so it is safe to
run while the app is serving.

## What the manuscript contains

* **Continuous text** by default, which is the method's purest form. **Paragraph
  breaks** (off by default) and **poetry lines** (on by default) follow exactly
  what the source marks (USFX `p`/`q` styles); each is a toggle, and a toggle
  only ever merges, so nothing is invented.
* **Line numbers** restart on each page; with two translations they count the
  first one.
* **Space for notes**: wide margins and open line spacing.
* **Copyright notice** at the end of each text: name, one-line licence notice,
  full statement.
* Left out as editorial: section headings, footnotes, cross-references, Psalm
  descriptive titles.

## Live preview

The page preview follows every change. It is rendered by Typst as low-resolution
PNGs (96 ppi, first 6 pages, for the screen; the PDF download is the
print-quality output). To keep that cheap:

* the browser waits 450 ms after the last change and cancels any request still
  in flight;
* previews are cached by a hash of exactly what was rendered, so returning to
  earlier settings is free;
* layout is cut off after about six pages' worth of text, so cost does not grow
  with the selection;
* the server starts no render for a client that has already left, and kills one
  in progress;
* at most one Typst process per CPU core runs at a time
  (`MANUSCRIPT_MAX_CONCURRENT`).

Measured on a single CPU core (real KJV, distinct requests so nothing is
cached): a chapter previews in about 90 ms of work (≈13/s), a whole epistle in
about 300 ms (≈3/s), and a whole Genesis, cut, in about 300 ms. Twenty users
each changing a setting ten times, 50 ms apart, produced 200 requests but only
20 renders and no leftover processes. Each active user needs roughly one render
per pause in editing, so capacity is in the tens of simultaneous users per core,
and scales with cores. That is an estimate from these tests, not a measurement
under production traffic; the server logs every render and every abandoned one
at INFO so real load can be watched. Rate limiting per client belongs in the
reverse proxy.

## Choosing between translations

The passage is independent of the translation. Switching translations never
changes it, and the choice is kept in the URL. If the new translation cannot
supply the range (a verse, chapter or whole book it lacks), the page says
exactly what is missing, disables the buttons, and offers an explicit **Fit
passage to these translations** action. The server enforces the same rule and
never clamps.

## Deployment

* **NixOS:** `services.manuscript-discovery = { enable = true; sourceDir =
  "/srv/ebible"; };` ingests new or changed zips before each start. Put a
  reverse proxy in front for TLS.
* **Docker, built by Nix:** `nix build .#docker && docker load < result`, then
  `docker run --rm -v md:/data -v ~/ebible:/sources:ro manuscript-discovery
  ingest /sources` and `docker run -p 8000:8000 -v md:/data
  manuscript-discovery`.

Settings are `MANUSCRIPT_*` environment variables (see `settings.py`).

## Design

* **Storage:** one SQLite file. Per translation, one row per chapter holding
  zlib-compressed JSON, plus small `book` rows (verse counts, names) so outlines
  never decode text. Nothing is cached in Python, so memory does not grow with
  the number of translations. A real KJV is ~4.8 MB and reads a 176-verse range
  in well under a millisecond.
* **Typst, not XeLaTeX:** one small binary, millisecond compiles,
  OpenType/hyphenation/CJK support, and text reaches it as JSON data, never as
  source, so there is nothing to escape or inject.
* **Boundaries:** `usfx`/`metadata` (read files) → `library` (SQLite) →
  `document` (selection to blocks) → `typeset` (Typst). `typography` derives
  per-text settings. There are no abstract interfaces yet; add one when a second
  implementation exists.

## Limitations

* Ranges stay within one book. Verse numbering differs between traditions in
  places (Psalms, some Prophets), so a range valid in one translation may be
  refused by another, by design.
* Fonts: Latin, Greek and Cyrillic use Libertinus Serif; CJK uses Noto Serif CJK
  (SC/TC/JP/KR chosen from the metadata); other scripts rely on Noto per-glyph
  fallback, which is untested here.
* The Nix files (flake, package, module, image) have not been evaluated; the
  Python and Typst pipeline has, against a real eBible zip.
