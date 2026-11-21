# Scripture typesetter

Pick any contiguous run of verses from an [eBible.org](https://ebible.org) text and get a
professionally typeset PDF (or plain text). No verse, chapter or book numbers appear in the
body; the only reference is the title (`Ephesians 1:15–2:10`). Optionally set two translations
side by side in independently flowing columns.

## Quick start (Nix)

```sh
git add -A                      # flakes only see git-tracked files
nix develop                     # Python, Typst and the fonts, all pinned
# put eBible *_usfx.zip files in ./data   (see "Getting texts")
python -m bible_typeset         # http://127.0.0.1:8000
pytest                          # also exercises real Typst + the pinned fonts
```

## Getting texts

Download the **USFX** zip of each translation (the `…_usfx.zip` link on its eBible page) into
`data/`, e.g. `grctr_usfx.zip`, `eng-kjv2006_usfx.zip`, `cmn2006_usfx.zip`.

The `*_readaloud.zip` files used in the proof of concept cannot be used here: they contain one file
per chapter with verse boundaries removed, so a verse range cannot be cut from them. USFX keeps
verse markers *and* paragraph/poetry structure, and is plain XML.

Display names, hyphenation language and fonts per text live in `src/bible_typeset/texts.toml`
(override with `BIBLE_TEXTS_CONFIG`). Unlisted texts still work, using defaults. **Check the two
Chinese entries**: confirm whether each is simplified or traditional and adjust font/region.

## Deployment

* **Docker, built by Nix:** `nix build .#docker && docker load < result`, then
  `docker run -p 8000:8000 -v $PWD/data:/data:ro bible-typeset`
* **NixOS service:**
  ```nix
  inputs.bible-typeset.url = "github:you/bible-typeset";
  # ...
  imports = [ bible-typeset.nixosModules.default ];
  services.bible-typeset = { enable = true; dataDir = "/srv/ebible"; port = 8000; };
  ```
  Put a reverse proxy (nginx/Caddy) in front for TLS.

Settings are environment variables (`BIBLE_DATA_DIR`, `BIBLE_FONT_DIR`, `BIBLE_MAX_VERSES`,
`BIBLE_MAX_CONCURRENT`, `BIBLE_TIMEOUT_S`, `BIBLE_HOST`, `BIBLE_PORT`; see `settings.py`).

## Why these choices

**The font problem.** The old `shell.nix` provided TeX Live but no fonts, and nothing told fontconfig
where fonts were; `\setmainfont{Noto Serif}` only worked when the host happened to have it. Fonts are
now Nix packages, and the app passes Typst `--ignore-system-fonts --font-path <that closure>`, so the
same fonts are used on every machine, in the container and in the service.

**Typst instead of XeLaTeX.** Typst is one small binary (no TeX Live closure, no package
collections to enumerate), compiles in milliseconds, and has the typographic features needed here:
OpenType shaping, hyphenation, justification, CJK line-breaking and punctuation handling, and flowing
grid cells for parallel columns. Most importantly for a web service, text is passed to it as **JSON
data**, not spliced into source, so there is no escaping step and no TeX-style injection surface
(`\write18`, `\input`, …). XeLaTeX remains the more mature engine, and the tests exercise the same
Greek, Latin and CJK cases that matter; swap it back in only if specific LaTeX packages are needed.

**Python/FastAPI.** The work is parsing text, validating input and supervising one subprocess, which is
squarely in Python's range. FastAPI gives typed query validation (Pydantic), async subprocess handling
and OpenAPI docs at `/api/docs`; `defusedxml` parses the XML; `pydantic-settings` handles configuration.

## Notes and limitations

* **Greek uses `lang = "el"`** (see `texts.toml`): Typst has no `grc` hyphenation patterns, but the
  Greek ones hyphenate polytonic text correctly (checked with Libertinus Serif).
* **Parallel columns flow independently**, as with LaTeX `parallel`. Verse numbering differs between
  traditions in places (Psalms, some of the Prophets), and columns are not aligned verse by verse.
* Ranges stay within one book. Section headings, cross-references, footnotes and Psalm descriptive
  titles (`\d`) are intentionally left out; poetry keeps its line structure and indentation.
* Texts are parsed on first use and cached in memory (warmed in the background at startup).
* Rendered PDFs are not cached; Typst is fast enough that this has not mattered.

## Layout

```
src/bible_typeset/
  usfx.py      USFX → verse-addressable pieces       library.py   catalogue, loading, selection
  document.py  selection → blocks, title, plain text typeset.py   Typst subprocess (sandboxed temp dir)
  app.py       FastAPI routes                         template/book.typ   the page design
  static/index.html   the UI                          texts.toml          per-text settings
nix/           package + NixOS module      flake.nix   dev shell, package, docker image
tests/         pytest (parser, selection, API, real PDF rendering)
```
