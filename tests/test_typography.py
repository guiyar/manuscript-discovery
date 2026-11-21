from manuscript_discovery.metadata import Metadata
from manuscript_discovery.typography import typography_for


def ty(**kw):
    return typography_for(Metadata(**kw))


def test_three_letter_codes_become_the_two_letter_codes_typst_hyphenates_by():
    assert ty(language="eng").lang == "en" and ty(language="ind").lang == "id"
    assert (
        ty(language="grc").lang == "el"
    )  # Typst has no grc patterns; el hyphenates polytonic Greek
    assert ty(language=None).lang == "en"


def test_cjk_puts_the_cjk_font_first_and_picks_the_variant_from_the_data():
    sc = ty(language="cmn", country="CN", script="Han (Simplified variant)")
    tc = ty(language="cmn", country="TW")
    assert (sc.lang, sc.cjk, sc.hyphenate, sc.joiner) == ("zh", True, False, "")
    assert sc.font[0] == "Noto Serif CJK SC" and tc.font[0] == "Noto Serif CJK TC"
    assert (
        ty(language="cmn", script="Han (Traditional variant)").font[0]
        == "Noto Serif CJK TC"
    )
    assert ty(language="jpn").font[0] == "Noto Serif CJK JP"


def test_direction_and_region_come_from_metadata():
    t = ty(language="arb", direction="RTL", country="EG")
    assert (t.dir, t.region) == ("rtl", "eg") and ty(language="eng").dir == "ltr"
