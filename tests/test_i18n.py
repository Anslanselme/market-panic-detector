import re

import pytest

from panic_detector.config import load_settings, load_universe
from panic_detector.i18n import LANGUAGES, Translator, load_language

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_all_languages_have_exactly_the_same_keys():
    reference = set(load_language("en"))
    for code in LANGUAGES:
        keys = set(load_language(code))
        assert keys == reference, (
            f"{code}: missing {sorted(reference - keys)}, extra {sorted(keys - reference)}"
        )


@pytest.mark.parametrize("code", LANGUAGES)
def test_no_empty_strings(code):
    empty = [k for k, v in load_language(code).items() if not str(v).strip()]
    assert not empty


@pytest.mark.parametrize("code", LANGUAGES)
def test_placeholders_match_english(code):
    en = load_language("en")
    for key, text in load_language(code).items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(en[key])), key


def test_every_sector_and_crisis_is_translated():
    keys = set(load_language("en"))
    for sector in load_universe().sectors:
        assert f"sector.{sector}" in keys
    for crisis in load_settings().crises:
        assert f"crisis.{crisis.id}" in keys


def test_translator_formats_and_switches_language():
    t = Translator("en")
    assert t.tr("controls.days", n=60) == "60 days"
    t.language = "fr"
    assert t.tr("controls.days", n=60) == "60 jours"
    t.language = "zh_CN"
    assert t.tr("regime.panic") == "恐慌"
    with pytest.raises(ValueError):
        t.language = "de"
