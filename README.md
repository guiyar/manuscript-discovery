# Manuscript Discovery

Set any contiguous passage of an Bible text as a clean manuscript for
[Manuscript Discovery](https://fionapfennigwerth.info/manuscript-discovery/)
study: no chapter or verse numbers, no headings, no footnotes, nothing added to
the text. Only a title (the passage reference), page numbers and line numbers,
with room around the text for notes. Output is a typeset PDF or plain text,
optionally with a second translation in a parallel column.

## Quick start (Nix)

```sh
nix develop                 # Python, Typst and fonts, all pinned
python -m manuscript_discovery ingest ~/ebible   # a folder of *_usfx.zip files; re-run any time
python -m manuscript_discovery                   # http://127.0.0.1:8000
pytest
```

## Getting texts

Download the **USFX** zip of each translation (`<id>_usfx.zip`, linked from its
[eBible](https://ebible.org) page) into one folder and run `ingest` on the
folder. Everything is read from inside each zip:

| Read from | Used for |
|---|---|
| `*_usfx.xml` | the text, its paragraph and poetry markup, and the translation's own book names |
| `*metadata.xml` (DBL) | name, abbreviation, language, script, direction, country, copyright statement |
| `*VernacularAdditional.xml` | the one-line licence notice, when the statement's first line is long |

Fonts, hyphenation language and text direction are derived from the language and
script in the metadata. Every metadata field is optional: a zip without the
files (or with a differently shaped one) still ingests, using its id as the name
and omitting the copyright notice.

`ingest` skips files whose SHA-256 is unchanged, parses changed ones in parallel
(`-j`), and replaces each translation in a single transaction, so it is safe to
run while the app is serving.

## What the manuscript contains

* **Paragraph breaks** and **poetry lines**: exactly as the source marks them
  (USFX `p`/`q` styles), each switchable off. Switching off only ever merges
  (nothing is invented). The method's purest form is continuous prose, so turn
  paragraphs off for that.
* **Line numbers** restart on each page; with two translations they count the
  first one.
* **Space for notes**: wide margins and open line spacing.
* **Copyright notice** at the end of each text: name, one-line licence notice,
  full statement.
* Left out as editorial: section headings, footnotes, cross-references, Psalm
  descriptive titles.

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
* **Typst:** one small binary, millisecond compiles, OpenType/hyphenation/CJK
  support, and text reaches it as JSON data, never as source, so there is
  nothing to escape or inject.
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
