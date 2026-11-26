# Manuscript Discovery

Set any contiguous passage of an [eBible.org] text as a
clean manuscript for [Manuscript Discovery] study: no
chapter or verse numbers, no headings, no footnotes, nothing added to the text.
Only a title (the passage reference), page numbers and line numbers, with room
around the text for notes. Output is a typeset PDF or plain text, optionally
with a second translation in a parallel column.

[eBible.org]: https://ebible.org
[Manuscript Discovery]: https://fionapfennigwerth.info/manuscript-discovery/


## Quick start (Nix)

```sh
git add -A                  # flakes only see git-tracked files
nix develop                 # Python, Typst and fonts, all pinned
python -m manuscript_discovery ingest ~/ebible   # a folder of *_usfx.zip files; re-run any time
python -m manuscript_discovery                   # http://127.0.0.1:8000
(cd tests/ui && npm ci)                          # once, for the UI tests
pytest
```


## Getting texts

Download the **USFX** zip of each translation (`<id>_usfx.zip`, linked from its
eBible page) into one folder and run `ingest` on the folder. Everything else is
read from inside each zip:

| Read from                   | Used for                                                                        |
| --------------------------- | ------------------------------------------------------------------------------- |
| `*_usfx.xml`                | the text, its paragraph and poetry markup, and the translation's own book names |
| `*metadata.xml` (DBL)       | name, abbreviation, language, script, direction, country, copyright statement   |
| `*VernacularAdditional.xml` | the one-line licence notice, when the statement's first line is long            |

Nothing is kept in a hand-maintained list. Fonts, hyphenation language and text
direction are derived from the language and script in the metadata. Every
metadata field is optional: a zip without the files (or with a differently
shaped one) still ingests, using its id as the name and omitting the copyright
notice.

`ingest` skips files whose SHA-256 is unchanged, parses changed ones in parallel
(`-j`), and replaces each translation in a single transaction, so it is safe to
run while the app is serving.


## What the manuscript contains

- **Continuous text** by default, which is the method's purest form. **Paragraph
    breaks** (off by default) and **poetry lines** (on by default) follow
    exactly what the source marks (USFX `p`/`q` styles); each is a toggle, and
    a toggle only ever merges, so nothing is invented.
- **Line numbers** restart on each page. With two translations only the first is
    numbered: Typst counts every numbered line on a page and draws all the
    numbers in one margin, so numbering both columns scrambled them whenever
    the columns' lines differ in height (Chinese beside English or Greek).
- **Space for notes**: wide margins and open line spacing, **1.5 lines or
    double** (the choice belongs to, and is disabled with, “Space for notes”).
- **Copyright notice** at the end of each text: name, one-line licence notice,
    full statement.
- Left out as editorial: section headings, footnotes, cross-references, Psalm
    descriptive titles.


## Behind a reverse proxy

The app is built to sit behind a proxy that terminates TLS and handles HSTS,
compression and per-client rate limiting. What the app itself provides and
expects:

- **Security headers** on every response: a `Content-Security-Policy` that
    allows exactly the page's own inline script by hash and its own stylesheet
    from the same origin (no `unsafe-inline`, no `unsafe-eval`, no framing, no
    external resources), plus
    `nosniff`, `no-referrer`, `X-Frame-Options: DENY` and same-origin resource
    policy. The proxy should add HSTS, not overwrite the CSP, and must not
    rewrite the HTML (the hashes would stop matching). No `Server` header; no
    API docs or schema.
- **Load shedding.** At most `MAX_CONCURRENT` (default: one per core)
    preview and render requests run at once, including document construction and
    plain-text output. At most `MAX_WAITING` (16) queue before loading chapters;
    the rest get `503` with `Retry-After: 5`, which the UI shows as “busy”. The
    outer Uvicorn limit, `LIMIT_CONCURRENCY` (64), also bounds connections and
    request tasks, including cheap endpoints. Keep it above the total render
    admission limit, allowing room for other requests and proxy connections.
    One Typst render is killed after `TIMEOUT_S` (30), or if its client leaves.
    The proxy read timeout also needs to allow for queueing and document
    construction. Cached preview lookups share the request limit, but fetching
    an already-rendered PNG does not. PDF responses and the combined PNG
    output (including the lookahead page) are each capped at 32 MiB by
    `MAX_PDF_MB` and `MAX_PREVIEW_MB`. Compiler diagnostics retain at most
    64 KiB per stream. On NixOS the web unit also limits individual files
    to 64 MiB (`LimitFSIZE`); adjust that limit if raising the application caps.
    Ingestion has no such file-size cap. Each optional metadata XML member
    is limited to 2 MiB of decompressed data; oversized metadata is ignored.
    Ingestion rejects ZIPs and USFX XML members larger than 64 MiB each, and
    XML deeper than 128 elements or containing more than a million elements.
    These are input limits, not a guarantee of bounded parser memory.
- **Client address.** Set `MANUSCRIPT_TRUSTED_PROXIES` to the proxy's address
    (default `127.0.0.1`) so `X-Forwarded-For` is honoured from it and from
    nobody else; use `*` only when nothing else can reach the port. Without
    this, logs and any proxy-side logic see the proxy's address.
- **Probes.** `/healthz` is liveness (always 200 while the event loop turns).
    `/readyz` is readiness: 200 once the library has translations and Typst is
    present, otherwise 503 with the reasons. `/api/health` adds the version and
    the CJK font self-test.
- **Lifecycle.** SIGTERM finishes requests in flight (up to 15 s), then stops; a
    Typst process is never left behind. Bad configuration exits with status 2
    naming each offending `MANUSCRIPT_*` variable.
- **One process.** The preview cache and the render gate live in the process, so
    run a single worker and scale with cores (`MAX_CONCURRENT`) or replicas
    behind the proxy.
- **Logs** go to stderr at `MANUSCRIPT_LOG_LEVEL`. The access log records query
    strings, which hold the passage and any custom title.


## Serving with nginx (NixOS)

`services.manuscript-discovery.nginx.enable` puts a hardened nginx in front of
the app:

```nix
services.manuscript-discovery = {
  enable = true;
  sourceDir = "/srv/ebible";
  openFirewall = true;
  nginx = {
    enable = true;
    domain = "manuscripts.example.org";
  };
};
security.acme.acceptTerms = true;
security.acme.defaults.email = "ops@example.org";
```

The NixOS module defaults to one concurrent document request, four queued
requests and two parallel jobs per Typst compiler, matching its conservative
200% CPU quota. Override `settings.max_concurrent`, `settings.max_waiting` and
`settings.typst_jobs` on the host after measuring memory and CPU usage. The
startup font self-test shares the compiler limit. Outside NixOS, `TYPST_JOBS`
(default: unset) leaves Typst's own parallelism unchanged. Queueing time is
additional to the render timeout; a proxy may time out first during overload.

On NixOS, ingestion runs in a separate oneshot unit before the web service
starts (only when `sourceDir` is set). The web unit mounts `dataDir` read-only
and does not mount source archives. The ingestion unit uses its own
`manuscript-discovery-ingest` UID; the web unit receives read access through
the dedicated `manuscript-discovery-db` group (not nginx's socket group).

`services.manuscript-discovery.dataDir` defaults to
`/var/lib/manuscript-discovery`. The database is always `library.sqlite` inside
that directory. Use a dedicated directory; tmpfiles sets its owner and mode
(0750), and all of its contents are visible to the web unit. With ingestion
enabled, tmpfiles also sets the owner and mode (0640) of an existing database.
Ensure the ingestion user can read the source archives. With no `sourceDir`,
provide an existing `library.sqlite` readable by the web user or database group.

If upgrading from a custom `dbPath`, stop the web service, set `dataDir` to
the old database's parent directory, and rename the database to `library.sqlite`
if necessary, after closing all writers and checkpointing any WAL. The default
location is unchanged. To refresh sources, restart
`manuscript-discovery.service`, not the ingestion unit directly. Stop the web
unit before running any external database writer.

The app then listens on a Unix socket instead of a TCP port, which is what
makes the rest tighter:

- **No port to reach.** The socket is `/run/manuscript-discovery/app.sock`, mode
    0660 in a 0750 directory, both owned by the service's user and group. nginx
    reaches it through `SupplementaryGroups` on its own unit; no other local
    user can connect.
- **No network for the app.** The unit runs with `PrivateNetwork=true` and only
    `AF_UNIX`, so the app, and every Typst process it starts, sit in an empty
    network namespace.
- **The app binds the socket itself.** uvicorn's own `uds` option sets the socket
    to 0666, so `listen.py` creates it with exactly 0660, replaces a stale file
    from a crash, and refuses to touch a live listener or anything that is not
    a socket.
- **Forwarded headers are trusted by default on a socket.** Peers on a Unix
    socket have no address for uvicorn's list of IPs to match, and file
    permissions already decide who may connect. `MANUSCRIPT_TRUSTED_PROXIES`
    still overrides this either way.

What nginx does:

- Terminates TLS (ACME by default; set `nginx.acme = false` to supply your own
    certificate), redirects HTTP, and sends HSTS for a year.
- Sets `X-Forwarded-For` to the peer address rather than appending to what the
    client sent.
- Limits each client per route: `rateLimit.preview` (live preview),
    `rateLimit.pdf` (PDF downloads, the dearest request; `?format=txt` does not
    count) and `rateLimit.other`, all as `Nr/s` or `Nr/m`.
- Allows only `GET` and `HEAD`, keeps request bodies and header timeouts small,
    and never retries a render on another attempt.
- Waits `nginx.readTimeout` (default 45 s) for the app, which must stay above
    `MANUSCRIPT_TIMEOUT_S`.
- Answers `404` for `/healthz`, `/readyz` and `/api/health` from outside. Probe
    them on the host through the socket, e.g.
    `curl --unix-socket /run/manuscript-discovery/app.sock http://localhost/readyz`.

The app's own security headers (including the hash-based CSP) pass through
untouched.

Things to know:

- The service now runs as a static `manuscript-discovery` user rather than
    `DynamicUser`, so nginx can share its group.
- `openFirewall` opens 80 and 443 with nginx, or the app's port without.
- The nginx settings it enables are `mkDefault`s, so the host can override them.
- Rate limits are per client address as nginx sees it. Behind a CDN or another
    proxy, nginx needs the real-IP module configured, which this does not do.


## Web assets

The UI is `src/manuscript_discovery/static/index.html` (markup and JS, styled
with [Tailwind CSS] utility classes) plus `ui/tailwind.css`, the Tailwind input.
The palette (vellum, ink, oxblood and brass by day; lamplit oak and brass by
night) is a set of CSS variables in that file, exposed as Tailwind colours
(`bg-panel`, `text-accent`, ...) and switched by the browser's colour scheme, so
re-colouring the page means editing those values. Everything else is Tailwind's
default theme. The stylesheet,
`static/styles.css`, is compiled from those, and then everything is minified
into `static/dist/` (about 41 kB to 31 kB, 9 kB gzipped). Both outputs are
generated and gitignored. The compiler is the [standalone Tailwind CLI] and the
minifier is [tdewolff/minify] (the one Hugo uses); `assets.py` runs them.

- **`manuscript-discovery build-assets`** compiles the stylesheet and then
    minifies (needs `tailwindcss` and `minify` on PATH, both in the Nix dev
    shell). While editing the UI, leave the compiler watching instead:

    ```sh
    tailwindcss -i ui/tailwind.css -o src/manuscript_discovery/static/styles.css --watch
    ```

    The page is unstyled until the stylesheet exists, and the app logs a warning
    saying so. Only `index.html` is scanned for classes, so classes for elements
    the script creates are written out in full in its `<script>`. The page has
    no inline styles: the CSP allows the stylesheet as `style-src 'self'`, which
    also rules out Tailwind's Play CDN.
- **Wheel and Nix builds** do both steps automatically (`hatch_build.py`). The
    Nix build sets `MANUSCRIPT_REQUIRE_TAILWIND` and `MANUSCRIPT_REQUIRE_MINIFY`,
    so it fails rather than silently shipping an unstyled or unminified UI, and
    checks that `dist/index.html` and `dist/styles.css` are in the installed
    package. A plain `pip install` without those tools on PATH still works, but
    ships an unstyled UI (no `tailwindcss`) or the unminified source (no
    `minify`).
- **At runtime** the app serves `dist/` if it exists, otherwise the source, and
    logs which. In development that means edits to `index.html` show up
    immediately (with `styles.css` rebuilt by the watcher); run
    `manuscript-discovery build-assets` to try the minified build.
- Served with `ETag` and `Cache-Control: no-cache`, so a browser revalidates (a
    304 costs nothing) and a new release is picked up at once. Compression
    (gzip/brotli) is left to the reverse proxy.

[tdewolff/minify]: https://github.com/tdewolff/minify
[Tailwind CSS]: https://tailwindcss.com
[standalone Tailwind CLI]: https://tailwindcss.com/docs/installation/tailwind-cli


## Tests

`pytest` runs everything. The UI tests (`tests/ui`, Node's built-in runner with
jsdom) drive the real page against real servers, and `tests/test_ui.py` runs
them twice: against the readable source and against the **minified build**, so a
minifier that breaks the page is caught. They cover the first-visit defaults,
that switching translations never moves the passage (and what is shown when a
translation lacks it), the live preview (a real screen-resolution PNG, debounced
to one request per burst of edits, nothing requested for an invalid passage),
and the line-spacing control. Mutation-checked: breaking either the spacing link
or the passage-preservation logic in the minified build makes the suite fail.

One-time setup: `cd tests/ui && npm ci`. Without it, or without Node, Typst or
`minify`, the affected tests skip with a reason. `pytest -m "not ui"` skips
them; `npm test` inside `tests/ui` runs them against any running server
(`UI_BASE_URL=http://127.0.0.1:8000`). The Nix build does not run them, because
that would need the npm dependency hash, which I could not compute without Nix;
it does run the asset-build tests.

The UI tests are verified on Node 22 and 24. jsdom has its own `AbortSignal`,
which Node 24's `fetch` refuses outright, so `tests/ui/helpers.mjs` bridges the
two (a real browser has only one) and `tests/ui/harness.test.mjs` guards that
bridge.


## Fonts, and the preview showing empty boxes for CJK

The preview is PNG, and **Typst before 0.15 draws empty boxes in PNG export for
the variable Noto Serif CJK font that nixpkgs ships, while the same document
exports to PDF perfectly.** Nothing errors, so it looks like Chinese “does not
render in the preview”. Reproduced with Typst 0.12 and 0.14.2; 0.15 is fine, and
static fonts work on all of them. The Nix font set therefore pins the *static*
Noto Serif CJK (`nix/cjk-font.nix`) instead of `noto-fonts-cjk-serif`.

At startup the app renders two different characters per CJK family and compares
them (missing glyphs come out as identical boxes). It logs an ERROR if any
family fails, and `GET /api/health` reports the Typst version and the result.
The Nix build runs the same check against its own font set, so a font closure
that cannot draw CJK fails `nix flake check` rather than a user's preview.


## Live preview

The page preview follows every change. It is rendered by Typst as low-resolution
PNGs (96 ppi, first 6 pages, for the screen; the PDF download is the
print-quality output). To keep that cheap:

- the browser waits 450 ms after the last change and cancels any request still
    in flight;
- previews are cached by a hash of exactly what was rendered, so returning to
    earlier settings avoids another render. Concurrent misses for an identical
    preview share one compiler task; it is cancelled only when the last waiter
    leaves. Each waiter still occupies a document admission slot;
- layout is cut off after about six pages' worth of text, so cost does not grow
    with the selection;
- the server starts no render for a client that has already left, and kills one
    in progress;
- at most one Typst process per CPU core runs at a time
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

- **NixOS:**
    `services.manuscript-discovery = { enable = true; sourceDir = "/srv/ebible"; };`
    ingests new or changed zips before each start. Put a reverse proxy in front
    for TLS.
- **Docker, built by Nix:** `nix build .#docker && docker load < result`, then
    `docker run --rm -v md:/data -v ~/ebible:/sources:ro manuscript-discovery ingest /sources`
    and `docker run -p 8000:8000 -v md:/data manuscript-discovery`.

Settings are `MANUSCRIPT_*` environment variables (see `settings.py`).


## Design

- **Storage:** one SQLite file. Per translation, one row per chapter holding
    zlib-compressed JSON, plus small `book` rows (verse counts, names) so
    outlines never decode text. Nothing is cached in Python, so memory does not
    grow with the number of translations. A real KJV is ~4.8 MB and reads a
    176-verse range in well under a millisecond.
- **Typst, not XeLaTeX:** one small binary, millisecond compiles,
    OpenType/hyphenation/CJK support, and text reaches it as JSON data, never as
    source, so there is nothing to escape or inject.
- **Boundaries:** `usfx`/`metadata` (read files) → `library` (SQLite) →
    `document` (selection to blocks) → `typeset` (Typst). `typography` derives
    per-text settings. There are no abstract interfaces yet; add one when a
    second implementation exists.


## Limitations

- Ranges stay within one book. Verse numbering differs between traditions in
    places (Psalms, some Prophets), so a range valid in one translation may be
    refused by another, by design.
- Fonts: Latin, Greek and Cyrillic use Libertinus Serif; CJK uses the static
    Noto Serif CJK (SC/TC/JP/KR chosen from the metadata; some zips mislabel the
    script, e.g. a Chinese text with `Latin`, so the language code decides);
    other scripts rely on Noto per-glyph fallback, which is untested here.
- The Nix files evaluate against the pinned nixpkgs
    (`nix flake check --no-build`, and a NixOS configuration using the module),
    but nothing has been built or started: the package build, the Docker image,
    the systemd unit and the nginx configuration have never been run. The
    Python and Typst pipeline has, against a real eBible zip.
