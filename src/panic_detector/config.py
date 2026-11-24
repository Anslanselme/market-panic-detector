"""Load and validate the YAML configuration (universe and settings)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

REQUIRED_TICKERS = ("NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA")
MAX_SECTOR_GROUPS = 8


@dataclass(frozen=True)
class Stock:
    ticker: str
    name: str
    sector: str


@dataclass(frozen=True)
class Universe:
    benchmark: str
    benchmark_name: str
    leaders: tuple[str, ...]
    sectors: tuple[str, ...]
    stocks: tuple[Stock, ...]

    @property
    def tickers(self) -> list[str]:
        return [s.ticker for s in self.stocks]

    def by_ticker(self) -> dict[str, Stock]:
        return {s.ticker: s for s in self.stocks}


@dataclass(frozen=True)
class Crisis:
    id: str
    start: str
    end: str


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any] = field(repr=False)
    crises: tuple[Crisis, ...] = ()

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    @property
    def cache_dir(self) -> Path:
        path = Path(self.raw["data"]["cache_dir"])
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def windows(self) -> list[int]:
        return [int(w) for w in self.raw["metrics"]["windows"]]


class ConfigError(ValueError):
    """Raised when a configuration file is inconsistent."""


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_universe(path: Path | None = None) -> Universe:
    raw = _read_yaml(path or CONFIG_DIR / "universe.yaml")
    stocks = tuple(Stock(str(s["ticker"]), str(s["name"]), str(s["sector"])) for s in raw["stocks"])
    universe = Universe(
        benchmark=str(raw["benchmark"]["ticker"]),
        benchmark_name=str(raw["benchmark"]["name"]),
        leaders=tuple(raw["leaders"]),
        sectors=tuple(raw["sectors"]),
        stocks=stocks,
    )
    validate_universe(universe)
    return universe


def validate_universe(u: Universe) -> None:
    tickers = u.tickers
    if len(tickers) != len(set(tickers)):
        raise ConfigError("Duplicate tickers in universe.")
    missing = [t for t in REQUIRED_TICKERS if t not in tickers]
    if missing:
        raise ConfigError(f"Required tickers missing: {missing}")
    if len(u.sectors) > MAX_SECTOR_GROUPS:
        raise ConfigError(f"At most {MAX_SECTOR_GROUPS} sector groups allowed.")
    unknown = {s.sector for s in u.stocks} - set(u.sectors)
    if unknown:
        raise ConfigError(f"Stocks use undeclared sectors: {sorted(unknown)}")
    if u.benchmark in tickers:
        raise ConfigError("The benchmark must not be part of the network universe.")
    if not set(u.leaders) <= set(tickers):
        raise ConfigError("Every leader must be in the universe.")


def load_settings(path: Path | None = None) -> Settings:
    raw = _read_yaml(path or CONFIG_DIR / "settings.yaml")
    crises = tuple(Crisis(str(c["id"]), str(c["start"]), str(c["end"])) for c in raw.get("crises", []))
    return Settings(raw=raw, crises=crises)
