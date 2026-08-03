"""Yapılandırma yükleyici: config.yaml + .env"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


class Config:
    """Noktalı erişim destekleyen basit yapılandırma sarmalayıcısı.

    cfg.get("trend.ema_periods", [20, 50]) şeklinde kullanılır.
    """

    def __init__(self, data: Dict[str, Any], path: Path):
        self._data = data
        self.path = path
        self.root = ROOT

    # ---------------------------------------------------------------- yükleme
    @classmethod
    def load(cls, path: "str | Path | None" = None) -> "Config":
        load_dotenv(ROOT / ".env")
        p = Path(path) if path else DEFAULT_CONFIG
        if not p.exists():
            raise FileNotFoundError(f"Yapılandırma dosyası bulunamadı: {p}")
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data, p)

    # ----------------------------------------------------------------- erişim
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    # -------------------------------------------------------------- kısayollar
    @property
    def symbols(self) -> List[str]:
        return list(self.get("symbols", ["1000SHIBUSDT"]))

    @property
    def primary_symbol(self) -> str:
        return self.get("primary_symbol", self.symbols[0])

    def path_for(self, dotted: str, default: str) -> Path:
        """storage.* altındaki göreli yolları proje köküne göre çözer."""
        raw = self.get(dotted, default)
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # --------------------------------------------------------------- gizli env
    @staticmethod
    def env(name: str, default: str = "") -> str:
        return os.getenv(name, default)


_cached: "Config | None" = None


def get_config(reload: bool = False) -> Config:
    global _cached
    if _cached is None or reload:
        _cached = Config.load()
    return _cached
