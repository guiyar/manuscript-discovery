import zipfile
from pathlib import Path

import pytest

USFX_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?><usfx xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="usfx.xsd"><languageCode>{lang}</languageCode>'
)


def eph(v: dict[str, str]) -> str:
    """Ephesians 1:1-4 and 2:1-3 plus Psalm 23 poetry, in the shape eBible's USFX uses."""
    return f"""<book id="EPH"><id id="EPH">intro</id><h>Ephesians</h>
<p sfm="mt">Title that must not appear</p>
<c id="1"/><s>Heading that must not appear</s>
<p sfm="r"><ref tgt="X.1.1">Cross-ref that must not appear</ref></p>
<p><v id="1" bcv="EPH.1.1"/>{v["1"]}<f caller="+">FOOTNOTE</f><ve/>
<v id="2" bcv="EPH.1.2"/>{v["2"]}<ve/></p>
<p><v id="3" bcv="EPH.1.3"/>{v["3"]}<ve/><v id="4" bcv="EPH.1.4"/>{v["4"]}<ve/></p>
<c id="2"/>
<p><v id="1" bcv="EPH.2.1"/>{v["5"]}<ve/></p>
<p><v id="2-3" bcv="EPH.2.2"/>{v["6"]}<ve/></p></book>
<book id="PSA"><c id="23"/><p sfm="d">A Psalm of David.</p>
<q level="1"><v id="1" bcv="PSA.23.1"/>{v["q1"]}</q>
<q level="2">{v["q2"]}<ve/></q>
<p sfm="q1"><v id="2" bcv="PSA.23.2"/>{v["q3"]}<ve/></p></book>"""


TEXTS = {
    "eng-kjv2006": (
        "eng",
        dict(
            {
                "1": "Paul, an apostle of Jesus Christ",
                "2": "Grace be to you",
                "3": "Blessed be the God",
                "4": "According as he hath chosen us",
                "5": "And you hath he quickened",
                "6": "Wherein in time past ye walked",
                "q1": "The LORD is my shepherd;",
                "q2": "I shall not want.",
                "q3": "He maketh me to lie down",
            }
        ),
    ),
    "grctr": (
        "grc",
        {
            "1": "Παῦλος, ἀπόστολος Ἰησοῦ",
            "2": "χάρις ὑμῖν καὶ εἰρήνη",
            "3": "Εὐλογητὸς ὁ Θεὸς",
            "4": "καθὼς ἐξελέξατο ἡμᾶς",
            "5": "Καὶ ὑμᾶς ὄντας νεκροὺς",
            "6": "ἐν αἷς ποτε περιεπατήσατε",
            "q1": "α",
            "q2": "β",
            "q3": "γ",
        },
    ),
    "cmn2006": (
        "cmn",
        {
            "1": "藉着神旨意作基督耶稣使徒的保罗，",
            "2": "愿恩惠、平安归与你们。",
            "3": "愿颂赞归于神，",
            "4": "就如神从创立世界以前",
            "5": "你们死在过犯罪恶之中",
            "6": "那时你们在其中行事",
            "q1": "耶和华是我的牧者，",
            "q2": "我必不致缺乏。",
            "q3": "他使我躺卧",
        },
    ),
}


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("ebible")
    for tid, (lang, verses) in TEXTS.items():
        xml = USFX_HEAD.format(lang=lang) + eph(verses) + "</usfx>"
        with zipfile.ZipFile(d / f"{tid}_usfx.zip", "w") as zf:
            zf.writestr(f"{tid}_usfx.xml", xml)
    return d
