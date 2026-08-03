"""SQLite kalıcı depolama.

Tablolar:
  snapshots        - her taramanın tam JSON çıktısı (skor, setup, tüm motorlar)
  liquidations     - websocket ile toplanan zorunlu kapanışlar
  depth_snapshots  - order book üst seviyeleri (spoof/absorption karşılaştırması)
  whale_trades     - eşik üstü tekil işlemler
  alerts           - gönderilen alarmlar (cooldown ve geçmiş için)

Not: Zaman serisi hacmi büyüdüğünde şema aynı kalarak PostgreSQL + TimescaleDB'ye
taşınabilir; sorgular standart SQL'dir.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    ts          TEXT NOT NULL,
    price       REAL,
    long_score  REAL,
    short_score REAL,
    decision    TEXT,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_symbol_ts ON snapshots(symbol, ts);

CREATE TABLE IF NOT EXISTS liquidations (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT NOT NULL,
    ts       TEXT NOT NULL,
    side     TEXT NOT NULL,       -- SELL = long likidasyonu, BUY = short likidasyonu
    price    REAL,
    qty      REAL,
    notional REAL
);
CREATE INDEX IF NOT EXISTS idx_liq_symbol_ts ON liquidations(symbol, ts);

CREATE TABLE IF NOT EXISTS depth_snapshots (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol  TEXT NOT NULL,
    ts      TEXT NOT NULL,
    mid     REAL,
    bids    TEXT NOT NULL,
    asks    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_depth_symbol_ts ON depth_snapshots(symbol, ts);

CREATE TABLE IF NOT EXISTS whale_trades (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT NOT NULL,
    ts       TEXT NOT NULL,
    side     TEXT NOT NULL,
    price    REAL,
    qty      REAL,
    notional REAL,
    market   TEXT NOT NULL        -- futures | spot
);
CREATE INDEX IF NOT EXISTS idx_whale_symbol_ts ON whale_trades(symbol, ts);

CREATE TABLE IF NOT EXISTS screenings (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    total   INTEGER,
    payload TEXT NOT NULL        -- ön eleme tablosunun tamamı (JSON)
);
CREATE INDEX IF NOT EXISTS idx_screening_ts ON screenings(ts);

CREATE TABLE IF NOT EXISTS alerts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT NOT NULL,
    ts       TEXT NOT NULL,
    rule     TEXT NOT NULL,
    severity TEXT,
    title    TEXT,
    message  TEXT,
    payload  TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_symbol_rule ON alerts(symbol, rule, ts);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime] = None) -> str:
    return (dt or utcnow()).astimezone(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: "str | Path"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------- bağlantı
    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30,
                                   check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------ snapshots
    def save_snapshot(self, snapshot: Dict[str, Any]) -> int:
        conn = self.connect()
        cur = conn.execute(
            "INSERT INTO snapshots(symbol, ts, price, long_score, short_score, decision, payload)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                snapshot["symbol"],
                snapshot["timestamp"],
                snapshot.get("price"),
                snapshot.get("score", {}).get("long_score"),
                snapshot.get("score", {}).get("short_score"),
                snapshot.get("score", {}).get("decision"),
                json.dumps(snapshot, default=str, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)

    def latest_snapshot(self, symbol: str, offset: int = 0) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        row = conn.execute(
            "SELECT payload FROM snapshots WHERE symbol=? ORDER BY id DESC LIMIT 1 OFFSET ?",
            (symbol, offset),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def snapshot_history(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT payload FROM snapshots WHERE symbol=? ORDER BY id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows][::-1]

    def score_series(self, symbol: str, limit: int = 200) -> List[Dict[str, Any]]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT ts, price, long_score, short_score, decision FROM snapshots "
            "WHERE symbol=? ORDER BY id DESC LIMIT ?", (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows][::-1]

    # --------------------------------------------------------- likidasyonlar
    def add_liquidation(self, symbol: str, ts: str, side: str, price: float,
                        qty: float, notional: float):
        conn = self.connect()
        conn.execute(
            "INSERT INTO liquidations(symbol, ts, side, price, qty, notional) VALUES(?,?,?,?,?,?)",
            (symbol, ts, side, price, qty, notional),
        )
        conn.commit()

    def liquidations_since(self, symbol: str, hours: int = 24) -> List[Dict[str, Any]]:
        since = iso(utcnow() - timedelta(hours=hours))
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM liquidations WHERE symbol=? AND ts>=? ORDER BY ts",
            (symbol, since),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- order book
    def save_depth(self, symbol: str, mid: float, bids: List[List[float]],
                   asks: List[List[float]]):
        conn = self.connect()
        conn.execute(
            "INSERT INTO depth_snapshots(symbol, ts, mid, bids, asks) VALUES(?,?,?,?,?)",
            (symbol, iso(), mid, json.dumps(bids), json.dumps(asks)),
        )
        conn.commit()

    def previous_depth(self, symbol: str, max_age_minutes: int = 180) -> Optional[Dict[str, Any]]:
        """Bir öncekini döndürür (en son kaydedilen hariç)."""
        since = iso(utcnow() - timedelta(minutes=max_age_minutes))
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM depth_snapshots WHERE symbol=? AND ts>=? "
            "ORDER BY id DESC LIMIT 1 OFFSET 1", (symbol, since),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["bids"] = json.loads(d["bids"])
        d["asks"] = json.loads(d["asks"])
        return d

    # -------------------------------------------------------------- whales
    def add_whale_trades(self, symbol: str, trades: List[Dict[str, Any]], market: str):
        if not trades:
            return
        conn = self.connect()
        conn.executemany(
            "INSERT INTO whale_trades(symbol, ts, side, price, qty, notional, market)"
            " VALUES(?,?,?,?,?,?,?)",
            [(symbol, t["time"], t["side"], t["price"], t["qty"], t["notional"], market)
             for t in trades],
        )
        conn.commit()

    def whale_trades_since(self, symbol: str, hours: int = 24) -> List[Dict[str, Any]]:
        since = iso(utcnow() - timedelta(hours=hours))
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM whale_trades WHERE symbol=? AND ts>=? ORDER BY ts DESC",
            (symbol, since),
        ).fetchall()
        return [dict(r) for r in rows]

    def whale_trade_exists(self, symbol: str, ts: str, notional: float) -> bool:
        conn = self.connect()
        row = conn.execute(
            "SELECT 1 FROM whale_trades WHERE symbol=? AND ts=? AND ABS(notional-?)<0.01 LIMIT 1",
            (symbol, ts, notional),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------- piyasa ön eleme
    def save_screening(self, records: List[Dict[str, Any]]):
        conn = self.connect()
        conn.execute(
            "INSERT INTO screenings(ts, total, payload) VALUES(?,?,?)",
            (iso(), len(records), json.dumps(records, default=str, ensure_ascii=False)),
        )
        conn.commit()

    def latest_screening(self) -> Optional[Dict[str, Any]]:
        conn = self.connect()
        row = conn.execute(
            "SELECT ts, total, payload FROM screenings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {"ts": row["ts"], "total": row["total"],
                "records": json.loads(row["payload"])}

    # -------------------------------------------------------------- alarmlar
    def last_alert_time(self, symbol: str, rule: str) -> Optional[datetime]:
        conn = self.connect()
        row = conn.execute(
            "SELECT ts FROM alerts WHERE symbol=? AND rule=? ORDER BY id DESC LIMIT 1",
            (symbol, rule),
        ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["ts"])
        except ValueError:
            return None

    def save_alert(self, alert: Dict[str, Any]):
        conn = self.connect()
        conn.execute(
            "INSERT INTO alerts(symbol, ts, rule, severity, title, message, payload)"
            " VALUES(?,?,?,?,?,?,?)",
            (alert["symbol"], alert.get("ts", iso()), alert["rule"],
             alert.get("severity", "info"), alert.get("title", ""),
             alert.get("message", ""), json.dumps(alert.get("payload", {}), default=str)),
        )
        conn.commit()

    def recent_alerts(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self.connect()
        if symbol:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- bakım
    def prune(self, keep_days: int = 30):
        cutoff = iso(utcnow() - timedelta(days=keep_days))
        conn = self.connect()
        for table in ("snapshots", "liquidations", "depth_snapshots", "whale_trades", "alerts"):
            conn.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
        conn.commit()
        conn.execute("VACUUM")


_storage: Optional[Storage] = None


def get_storage(db_path: Optional[str] = None) -> Storage:
    global _storage
    if _storage is None:
        from core.config import get_config
        cfg = get_config()
        path = db_path or cfg.path_for("storage.db_path", "data/market.db")
        _storage = Storage(path)
    return _storage
