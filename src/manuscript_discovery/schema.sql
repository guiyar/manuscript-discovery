-- Schema v1. One database holds every translation. Written only by `ingest`, opened
-- read-only by the web app. The default rollback journal is used on purpose: readers then
-- need no -wal/-shm files, so a read-only service directory works.
--
-- Storage unit = one chapter of one translation: a zlib-compressed JSON array of
-- [par, kind, level, start, end, text] rows. A verse range touches a handful of chapter rows.
PRAGMA user_version = 1;

CREATE TABLE translation (
  id            TEXT PRIMARY KEY,         -- eBible id, e.g. 'grctr'
  name          TEXT NOT NULL,
  lang          TEXT NOT NULL,            -- ISO 639-3
  search        TEXT NOT NULL,            -- lower-cased id/names/abbreviations/language
  meta          TEXT NOT NULL,            -- JSON of everything read from the metadata files
  source_sha256 TEXT NOT NULL,            -- ingest skips a file whose hash is unchanged
  ingested_at   TEXT NOT NULL
) STRICT;
CREATE INDEX translation_by_lang ON translation (lang, name);

CREATE TABLE book (                       -- answers /outline without decoding any chapter
  translation_id TEXT NOT NULL REFERENCES translation (id) ON DELETE CASCADE,
  code           TEXT NOT NULL,
  ord            INTEGER NOT NULL,        -- canonical order
  name           TEXT NOT NULL,           -- the translation's own short name for the book
  verses         TEXT NOT NULL,           -- JSON: highest verse per chapter, e.g. [4,3]
  PRIMARY KEY (translation_id, code)
) WITHOUT ROWID, STRICT;

CREATE TABLE chapter (
  translation_id TEXT NOT NULL,
  book           TEXT NOT NULL,
  chapter        INTEGER NOT NULL,
  data           BLOB NOT NULL,
  PRIMARY KEY (translation_id, book, chapter),
  FOREIGN KEY (translation_id, book) REFERENCES book (translation_id, code) ON DELETE CASCADE
) WITHOUT ROWID, STRICT;
