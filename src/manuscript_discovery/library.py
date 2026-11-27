"""The library: every ingested translation, stored in SQLite (schema in schema.sql).

``Library`` is what the web app uses (read-only, nothing cached in Python, so memory does not
grow with the number of translations). ``LibraryWriter`` is used only by ``ingest``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from .books import book_name, book_sort_key
from .metadata import Metadata
from .usfx import Piece

SCHEMA_VERSION = 1
Ref = tuple[int, int]  # (chapter, verse)


class LibraryUnavailable(RuntimeError):
    """The database is missing or has an incompatible schema."""


class UnknownTranslation(KeyError):
    pass


class UnknownBook(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class Translation:
    id: str
    name: str
    lang: str
    meta: Metadata
    source_sha256: str = ""

    @property
    def abbreviation(self) -> str:
        return self.meta.abbreviation_local or self.meta.abbreviation or self.id

    @property
    def search_text(self) -> str:
        m = self.meta
        parts = [
            self.id,
            self.name,
            m.name_local,
            m.abbreviation,
            m.abbreviation_local,
            m.language_name,
            self.lang,
        ]
        return " ".join(p for p in parts if p).lower()


@dataclass(frozen=True, slots=True)
class BookOutline:
    code: str
    name: str
    verses: Sequence[int]  # verses[i] = highest verse number in chapter i + 1


def _encode(pieces: Sequence[Piece]) -> bytes:
    rows = [[p.par, p.kind, p.level, p.start, p.end, p.text] for p in pieces]
    return zlib.compress(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(), 9
    )


def _decode(chapter: int, blob: bytes) -> list[Piece]:
    return [
        Piece(par, kind, level, chapter, start, end, text)
        for par, kind, level, start, end, text in json.loads(zlib.decompress(blob))
    ]


def _like(term: str) -> str:
    return (
        "%"
        + term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        + "%"
    )


def _translation(row: tuple) -> Translation:
    id_, name, lang, meta, sha = row
    return Translation(id_, name, lang, Metadata.from_dict(json.loads(meta)), sha)


_COLUMNS = "id, name, lang, meta, source_sha256"


class Library:
    """Read side. One read-only connection per thread."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._conns: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if not self.path.exists():
                raise LibraryUnavailable(
                    f"Library not found at {self.path}. Run `manuscript-discovery ingest`."
                )
            conn = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro",
                uri=True,
                check_same_thread=False,
                timeout=10,
            )
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA mmap_size = 268435456")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                conn.close()
                raise LibraryUnavailable(
                    f"Library schema v{version}, expected v{SCHEMA_VERSION}"
                )
            self._local.conn = conn
            with self._lock:
                self._conns.append(conn)
        return conn

    def search(
        self,
        q: str | None = None,
        lang: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Translation]:
        where, args = [], []
        if lang:
            where.append("lang = ?")
            args.append(lang)
        for word in (q or "").split():  # every word must match somewhere
            where.append("search LIKE ? ESCAPE '\\'")
            args.append(_like(word))
        sql = f"SELECT {_COLUMNS} FROM translation"  # noqa: S608 - _COLUMNS is a constant; values are bound
        sql += (" WHERE " + " AND ".join(where)) if where else ""
        rows = (
            self._conn()
            .execute(
                sql + " ORDER BY lang, name LIMIT ? OFFSET ?", [*args, limit, offset]
            )
            .fetchall()
        )
        return [_translation(r) for r in rows]

    def count(self) -> int:
        return self._conn().execute("SELECT count(*) FROM translation").fetchone()[0]

    def get(self, translation_id: str) -> Translation:
        row = (
            self._conn()
            .execute(
                f"SELECT {_COLUMNS} FROM translation WHERE id = ?",  # noqa: S608 - _COLUMNS is a constant
                (translation_id,),
            )
            .fetchone()
        )
        if row is None:
            raise UnknownTranslation(translation_id)
        return _translation(row)

    def outline(self, translation_id: str) -> list[BookOutline]:
        self.get(translation_id)
        rows = (
            self._conn()
            .execute(
                "SELECT code, name, verses FROM book WHERE translation_id = ? ORDER BY ord",
                (translation_id,),
            )
            .fetchall()
        )
        return [BookOutline(code, name, json.loads(v)) for code, name, v in rows]

    def pieces(
        self, translation_id: str, book: str, start: Ref, end: Ref
    ) -> list[Piece]:
        """Pieces overlapping start..end inclusive, in document order (a verse bridge such as
        2:2-3 is returned for a request touching either verse)."""
        conn = self._conn()
        if (
            conn.execute(
                "SELECT 1 FROM book WHERE translation_id = ? AND code = ?",
                (translation_id, book),
            ).fetchone()
            is None
        ):
            self.get(translation_id)
            raise UnknownBook(book)
        rows = conn.execute(
            "SELECT chapter, data FROM chapter WHERE translation_id = ? AND book = ? "
            "AND chapter BETWEEN ? AND ? ORDER BY chapter",
            (translation_id, book, start[0], end[0]),
        ).fetchall()
        return [
            p
            for ch, blob in rows
            for p in _decode(ch, blob)
            if (p.chapter, p.end) >= start and (p.chapter, p.start) <= end
        ]

    def close(self) -> None:
        with self._lock:
            for c in self._conns:
                c.close()
            self._conns.clear()


class LibraryWriter:
    """Write side; creates the database on first use."""

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.execute("PRAGMA foreign_keys = ON")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.conn.executescript(
                resources.files("manuscript_discovery")
                .joinpath("schema.sql")
                .read_text("utf-8")
            )
        elif version != SCHEMA_VERSION:
            raise LibraryUnavailable(
                f"Library schema v{version}, expected v{SCHEMA_VERSION}"
            )

    def current_sha(self, translation_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT source_sha256 FROM translation WHERE id = ?", (translation_id,)
        ).fetchone()
        return row[0] if row else None

    def add(
        self, t: Translation, books: Mapping[str, list[Piece]], names: Mapping[str, str]
    ) -> int:
        """Replace one translation in a single transaction (readers see old or new, never half).
        Returns the number of pieces stored."""
        stored = 0
        with self.conn:
            self.conn.execute("DELETE FROM translation WHERE id = ?", (t.id,))
            self.conn.execute(
                "INSERT INTO translation VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    t.id,
                    t.name,
                    t.lang,
                    t.search_text,
                    json.dumps(asdict(t.meta), ensure_ascii=False),
                    t.source_sha256,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            for code in sorted(books, key=book_sort_key):
                by_chapter: dict[int, list[Piece]] = {}
                for p in books[code]:
                    by_chapter.setdefault(p.chapter, []).append(p)
                if not by_chapter:
                    continue
                verses = [
                    max((p.end for p in by_chapter.get(c, [])), default=0)
                    for c in range(1, max(by_chapter) + 1)
                ]
                self.conn.execute(
                    "INSERT INTO book VALUES (?, ?, ?, ?, ?)",
                    (
                        t.id,
                        code,
                        book_sort_key(code)[0],
                        names.get(code) or book_name(code),
                        json.dumps(verses),
                    ),
                )
                self.conn.executemany(
                    "INSERT INTO chapter VALUES (?, ?, ?, ?)",
                    [
                        (t.id, code, ch, _encode(ps))
                        for ch, ps in sorted(by_chapter.items())
                    ],
                )
                stored += len(books[code])
        return stored

    def close(self) -> None:
        self.conn.close()
