"""Interface translations. All user-facing strings live in the JSON files of this package."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent
LANGUAGES = ("en", "fr", "zh_CN")
DEFAULT_LANGUAGE = "en"


@lru_cache(maxsize=None)
def load_language(code: str) -> dict[str, str]:
    with open(I18N_DIR / f"{code}.json", encoding="utf-8") as fh:
        return json.load(fh)


class Translator:
    """Look up interface strings for the active language; falls back to English."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = language

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, code: str) -> None:
        if code not in LANGUAGES:
            raise ValueError(f"Unsupported language: {code}")
        self._language = code

    def tr(self, key: str, **kwargs: object) -> str:
        text = load_language(self._language).get(key) or load_language(DEFAULT_LANGUAGE).get(key, key)
        return text.format(**kwargs) if kwargs else text
