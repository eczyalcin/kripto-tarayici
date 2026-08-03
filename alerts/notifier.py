"""Alarm dağıtımı — konsol, Telegram, e-posta."""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, List

import requests

from core.logging_setup import log

SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🔵", "info": "⚪"}


def _console(alerts: List[Dict[str, Any]]):
    for a in alerts:
        icon = SEVERITY_ICON.get(a.get("severity", "info"), "•")
        log.warning(f"{icon} ALARM [{a['symbol']}] {a['title']} — {a['message']}")


def _telegram(alerts: List[Dict[str, Any]]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.warning("Telegram etkin ama TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanımlı değil")
        return False

    lines = []
    for a in alerts:
        icon = SEVERITY_ICON.get(a.get("severity", "info"), "•")
        lines.append(f"{icon} <b>{a['symbol']} — {a['title']}</b>\n{a['message']}")
    text = "\n\n".join(lines)[:4000]

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
        if resp.status_code != 200:
            log.error(f"Telegram gönderimi başarısız: {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except requests.RequestException as exc:
        log.error(f"Telegram hatası: {exc}")
        return False


def _email(alerts: List[Dict[str, Any]], subject: str = "") -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", user).strip()
    to = os.getenv("SMTP_TO", "").strip()

    if not (host and user and password and to):
        log.warning("E-posta etkin ama SMTP_* ortam değişkenleri eksik")
        return False

    body = "\n\n".join(f"[{a['symbol']}] {a['title']}\n{a['message']}" for a in alerts)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject or f"Kripto Alarm — {alerts[0]['symbol']} ({len(alerts)} olay)"
    msg["From"] = sender
    msg["To"] = to

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(sender, [x.strip() for x in to.split(",")], msg.as_string())
        return True
    except Exception as exc:  # noqa: BLE001
        log.error(f"E-posta gönderimi başarısız: {exc}")
        return False


def dispatch(alerts: List[Dict[str, Any]], cfg, storage=None) -> Dict[str, bool]:
    """Alarmları etkin kanallara gönderir ve veritabanına yazar."""
    if not alerts:
        return {}

    channels = cfg.get("alerts.channels", {})
    result: Dict[str, bool] = {}

    if channels.get("console", True):
        _console(alerts)
        result["console"] = True
    if channels.get("telegram", False):
        result["telegram"] = _telegram(alerts)
    if channels.get("email", False):
        result["email"] = _email(alerts)

    if storage:
        for a in alerts:
            storage.save_alert(a)

    return result


def send_text(text: str, cfg, subject: str = "Kripto Raporu") -> Dict[str, bool]:
    """Serbest metin gönderimi (günlük rapor için)."""
    channels = cfg.get("alerts.channels", {})
    fake = [{"symbol": "REPORT", "title": subject, "message": text, "severity": "info"}]
    result: Dict[str, bool] = {}
    if channels.get("telegram", False):
        result["telegram"] = _telegram(fake)
    if channels.get("email", False):
        result["email"] = _email(fake, subject)
    return result
