"""Everything we know about a translation beyond its text, read from the files in its zip.

eBible zips carry a Digital Bible Library ``<id>metadata.xml`` (name, language, script,
copyright statement) and a ``*VernacularAdditional.xml`` with a one-line copyright. Their
presence and exact schema are not guaranteed, so every field is optional, unknown elements are
ignored, and a missing or unreadable file just leaves its fields empty.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, fields
from html.parser import HTMLParser
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as ET

log = logging.getLogger(__name__)
_MAX_METADATA_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Metadata:
    name: str | None = None
    name_local: str | None = None
    abbreviation: str | None = None
    abbreviation_local: str | None = None
    description: str | None = None
    language: str | None = None  # ISO 639-3, e.g. "eng"
    language_name: str | None = None
    script: str | None = None
    direction: str | None = None  # "LTR" / "RTL"
    country: str | None = None  # ISO 3166-1 alpha-2
    copyright: str | None = None  # full statement, as plain text
    notice: str | None = None  # one-line licence notice

    @classmethod
    def from_dict(cls, data: dict) -> "Metadata":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def short_notice(self) -> str | None:
        """A one-line licence notice: the statement's first line if it is short, else the
        dedicated one-line copyright, else the start of the statement."""
        first = next(
            (ln.strip() for ln in (self.copyright or "").splitlines() if ln.strip()),
            None,
        )
        if first and len(first) <= 100:
            return first
        return self.notice or (first[:100] if first else None)

    @property
    def statement_paragraphs(self) -> list[str]:
        """The statement minus its first line when that is the short notice, as paragraphs."""
        lines = (self.copyright or "").splitlines()
        if lines and lines[0].strip() == self.short_notice:
            lines = lines[1:]
        paragraphs = re.split(r"\n\s*\n", "\n".join(lines))
        return [" ".join(p.split()) for p in paragraphs if p.strip()]


class _Text(HTMLParser):
    """HTML (often escaped inside the XML) to plain text, keeping paragraph breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("p", "br", "div", "li"):
            self.parts.append("\n")


def _plain(markup: str) -> str:
    parser = _Text()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts).replace("\r", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _text(root: Element, path: str) -> str | None:
    el = root.find(path)
    return " ".join("".join(el.itertext()).split()) or None if el is not None else None


def _root(xml: bytes, what: str) -> Element | None:
    try:
        root = ET.fromstring(xml)
    except ParseError as e:
        log.warning("%s is not readable XML (%s); ignoring it", what, e)
        return None
    for el in root.iter():  # tolerate namespaced variants
        el.tag = el.tag.rpartition("}")[2]
    return root


def _member(zf: zipfile.ZipFile, suffix: str) -> bytes | None:
    name = next((n for n in zf.namelist() if n.lower().endswith(suffix)), None)
    if name is None:
        return None
    if zf.getinfo(name).file_size > _MAX_METADATA_BYTES:
        log.warning("%s exceeds the metadata size limit; ignoring it", name)
        return None
    with zf.open(name) as stream:
        data = stream.read(_MAX_METADATA_BYTES + 1)
    if len(data) > _MAX_METADATA_BYTES:
        log.warning("%s exceeds the metadata size limit; ignoring it", name)
        return None
    return data


def read_metadata(
    zf: zipfile.ZipFile, fallback_language: str | None = None
) -> Metadata:
    values: dict[str, str | None] = {"language": fallback_language}
    if xml := _member(zf, "metadata.xml"):
        if (root := _root(xml, "metadata.xml")) is not None:
            statement = root.find("copyright/statement")
            values |= {
                "name": _text(root, "identification/name"),
                "name_local": _text(root, "identification/nameLocal"),
                "abbreviation": _text(root, "identification/abbreviation"),
                "abbreviation_local": _text(root, "identification/abbreviationLocal"),
                "description": _text(root, "identification/description"),
                "language": _text(root, "language/iso") or fallback_language,
                "language_name": _text(root, "language/name"),
                "script": _text(root, "language/script"),
                "direction": _text(root, "language/scriptDirection"),
                "country": _text(root, "country/iso"),
                "copyright": _plain("".join(statement.itertext()))
                if statement is not None
                else None,
            }
    if xml := _member(zf, "additional.xml"):
        if (root := _root(xml, "VernacularAdditional")) is not None:
            values["notice"] = _text(root, "copyright")
    return Metadata(**values)
