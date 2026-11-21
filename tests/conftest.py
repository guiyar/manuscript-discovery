"""Synthetic eBible-shaped zips: BOM, style= attributes, Strong's <w>, footnotes, <d>/<b>/<s>,
DBL metadata. `tiny` is too short on purpose; `nometa` has no metadata files at all."""

import zipfile
from pathlib import Path

import pytest

from manuscript_discovery.ingest import ingest_paths
from manuscript_discovery.library import Library

BOM = "\ufeff"


def usfx(lang: str, v: dict[str, str], eph2: bool = True) -> str:
    chapter2 = (
        f"""<c id="2" />
<p style="p"><v id="1" bcv="EPH.2.1" />{v["5"]}
<ve />
</p>
<p style="p"><v id="2-3" bcv="EPH.2.2" />{v["6"]}
<ve />
</p>"""
        if eph2
        else ""
    )
    return f"""{BOM}<?xml version="1.0" encoding="utf-8"?><usfx xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><languageCode>{lang}</languageCode>
<book id="EPH"><id id="EPH">Ephesians
</id><h>Ephesians
</h><toc level="1">THE EPISTLE TO THE EPHESIANS
</toc><toc level="2">{v.get("name", "Ephesians")}
</toc><toc level="3">Eph
</toc><p sfm="mt" style="mt1">Title that must not appear
</p>
<c id="1" /><s style="s1">Heading that must not appear</s>
<p style="p"><v id="1" bcv="EPH.1.1" />{v["1"]}<f caller="+"><fr>1.1
</fr><ft>FOOTNOTE</ft></f>
<ve />
<v id="2" bcv="EPH.1.2" /><w s="G5485">{v["2"]}</w>
<ve />
</p>
<p style="p"><v id="3" bcv="EPH.1.3" />{v["3"]}
<ve />
<v id="4" bcv="EPH.1.4" />{v["4"]}
<ve />
</p>
{chapter2}</book>
<book id="PSA"><id id="PSA">Psalms
</id><toc level="2">Psalms
</toc><c id="23" /><d style="d">A Psalm of David.</d>
<q style="q1"><v id="1" bcv="PSA.23.1" />{v["q1"]}
</q>
<q style="q2">{v["q2"]}
<ve />
</q>
<b style="b" />
<q style="q1"><v id="2" bcv="PSA.23.2" />{v["q3"]}
<ve />
</q>
<p style="p"><v id="3" bcv="PSA.23.3" />{v["p"]}
<ve />
</p></book></usfx>"""


def dbl(name, abbr_local, iso, lang_name, script, direction, country, statement):
    return f"""{BOM}<?xml version="1.0" encoding="utf-8"?><DBLMetadata id="x" type="text"><identification><name>{name}</name><nameLocal>{name} (local)</nameLocal><abbreviation>{abbr_local.lower()}</abbreviation><abbreviationLocal>{abbr_local}</abbreviationLocal><description>About {name}</description></identification><language><iso>{iso}</iso><name>{lang_name}</name><script>{script}</script><scriptDirection>{direction}</scriptDirection></language><country><iso>{country}</iso></country><copyright><statement contentType="xhtml"><p>{statement}</p></statement></copyright></DBLMetadata>"""


PD = (
    "Public Domain\nLetters patent mean you need permission in the UK.\n\nCourtesy of "
    '&lt;a href="https://crosswire.org/"&gt;Crosswire&lt;/a&gt; &amp; eBible.'
)

EN = {
    "1": "Paul, an apostle of Jesus Christ",
    "2": "Grace be to you",
    "3": "Blessed be the God",
    "4": "According as he hath chosen us",
    "5": "And you hath he quickened",
    "6": "Wherein in time past ye walked",
    "q1": "The LORD is my shepherd;",
    "q2": "I shall not want.",
    "q3": "He maketh me to lie down",
    "p": "Surely goodness and mercy",
}
EL = dict(
    zip(
        EN,
        [
            "Παῦλος, ἀπόστολος Ἰησοῦ",
            "χάρις ὑμῖν καὶ εἰρήνη",
            "Εὐλογητὸς ὁ Θεὸς",
            "καθὼς ἐξελέξατο ἡμᾶς",
            "Καὶ ὑμᾶς ὄντας νεκροὺς",
            "ἐν αἷς ποτε περιεπατήσατε",
            "α",
            "β",
            "γ",
            "δ",
        ],
    ),
    name="Ἐφεσίους",
)
ZH = dict(
    zip(
        EN,
        [
            "藉着神旨意作基督耶稣使徒的保罗，",
            "愿恩惠、平安归与你们。",
            "愿颂赞归于神，",
            "就如神从创立世界以前",
            "你们死在过犯罪恶之中",
            "那时你们在其中行事",
            "耶和华是我的牧者，",
            "我必不致缺乏。",
            "他使我躺卧",
            "但愿",
        ],
    ),
    name="以弗所书",
)

ZIPS = {
    "eng-kjv2006": (
        usfx("eng", EN),
        dbl("King James Version", "KJV", "eng", "English", "Latin", "LTR", "GB", PD),
        "eng-kjv2006 Scripture is in the Public Domain.",
    ),
    "grctr": (
        usfx("grc", EL),
        dbl(
            "Greek Textus Receptus",
            "TR",
            "grc",
            "Greek",
            "Greek",
            "LTR",
            "GR",
            "Public Domain",
        ),
        None,
    ),
    "cmn2006": (
        usfx("cmn", ZH),
        dbl(
            "Chinese Test",
            "CT",
            "cmn",
            "Chinese",
            "Han (Simplified variant)",
            "LTR",
            "CN",
            "Public Domain",
        ),
        None,
    ),
    "tiny": (
        usfx("eng", {**EN, "name": "Ephesians"}, eph2=False),
        dbl(
            "Tiny Version",
            "TNY",
            "eng",
            "English",
            "Latin",
            "LTR",
            "US",
            "© 2020 Someone. " + "Long licence text. " * 12,
        ),
        "Short one-line notice.",
    ),
    "nometa": (usfx("ind", {**EN, "name": "Efesus"}), None, None),
}


def make_zip(
    directory: Path, tid: str, usfx_xml: str, meta: str | None, notice: str | None
) -> Path:
    path = directory / f"{tid}_usfx.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{tid}_usfx.xml", usfx_xml)
        if meta:
            zf.writestr(f"{tid}metadata.xml", meta)
        if notice:
            zf.writestr(
                f"{tid}-VernacularAdditional.xml",
                f'{BOM}<?xml version="1.0"?><vernacularParmsMiscellaneous><copyright>{notice}</copyright></vernacularParmsMiscellaneous>',
            )
        zf.writestr(
            "BookNames.xml", "<BookNames/>"
        )  # present in real zips, deliberately unused
    return path


@pytest.fixture(scope="session")
def zips(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("zips")
    for tid, parts in ZIPS.items():
        make_zip(d, tid, *parts)
    return d


@pytest.fixture(scope="session")
def db_path(zips, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("db") / "library.sqlite"
    added, _, failed = ingest_paths([zips], path)
    assert added == len(ZIPS) and not failed
    return path


@pytest.fixture(scope="session")
def lib(db_path):
    library = Library(db_path)
    yield library
    library.close()
