"""Streamlit arayüzü — Crypto Intelligence Dashboard."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd                              # noqa: E402
import plotly.graph_objects as go                # noqa: E402
import streamlit as st                           # noqa: E402
from plotly.subplots import make_subplots        # noqa: E402

from core.binance import get_client              # noqa: E402
from core.config import get_config               # noqa: E402
from core.indicators import enrich               # noqa: E402
from core.storage import get_storage             # noqa: E402

# page_title ana ekrana eklendiğinde simgenin altındaki yazı olur — kısa tutuluyor.
# initial_sidebar_state="auto": geniş ekranda açık, telefonda kapalı başlar.
st.set_page_config(page_title="Kripto Panel", page_icon="📊",
                   layout="wide", initial_sidebar_state="auto")

# ------------------------------------------------------------ mobil uyarlama
st.markdown("""
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Kripto">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
  /* Telefon: başlıkları küçült, boşlukları daralt, tablolara nefes aldır */
  @media (max-width: 640px) {
      .block-container { padding: 0.6rem 0.7rem 3rem 0.7rem !important; }
      h2 { font-size: 1.25rem !important; }
      h3 { font-size: 1.0rem !important; line-height: 1.35 !important; }
      .stTabs [data-baseweb="tab"] { padding: 6px 8px !important; font-size: 0.8rem; }
      [data-testid="stMetricValue"] { font-size: 1.15rem !important; }
      [data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
      .stDataFrame { font-size: 0.75rem; }
  }
  /* Sekme çubuğu telefonda yatay kaydırılabilsin */
  .stTabs [data-baseweb="tab-list"] {
      overflow-x: auto; flex-wrap: nowrap; scrollbar-width: none;
  }
  .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------- parola koruması
def _require_password():
    """.env içinde DASHBOARD_PASSWORD tanımlıysa parola sorar.

    Panel yerel ağa (--lan) veya tünele açıldığında erişimi kısıtlar.
    Parola tanımlı değilse hiçbir şey sormaz.
    """
    import os
    get_config()                      # .env yüklenir
    expected = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not expected or st.session_state.get("_auth_ok"):
        return

    st.title("🔒 Crypto Intelligence")
    st.caption("Panele erişmek için parolayı girin.")
    entered = st.text_input("Parola", type="password", key="_pwd")
    if entered:
        if entered == expected:
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Hatalı parola")
    st.stop()


_require_password()

DECISION_COLOR = {
    "STRONG LONG": "#00c853", "LONG": "#43a047", "WEAK LONG": "#7cb342",
    "NÖTR": "#fbc02d", "WEAK SHORT": "#ef6c00", "SHORT": "#e53935",
    "STRONG SHORT": "#b71c1c",
}


# ------------------------------------------------------------------ yardımcı
def fmt(v: Optional[float], d: int = 2, suffix: str = "") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{d}f}{suffix}"


@st.cache_data(ttl=30, show_spinner=False)
def load_latest(symbol: str) -> Optional[Dict[str, Any]]:
    return get_storage().latest_snapshot(symbol)


@st.cache_data(ttl=30, show_spinner=False)
def load_score_series(symbol: str, limit: int = 200) -> pd.DataFrame:
    rows = get_storage().score_series(symbol, limit)
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def load_candles(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    cfg = get_config()
    df = get_client(cfg).klines(symbol, interval, limit)
    return enrich(df, cfg.get("trend", {}))


def run_scan(symbol: str):
    from pipeline import scan_symbol
    with st.spinner(f"{symbol} taranıyor..."):
        snap = scan_symbol(symbol, get_config())
    st.cache_data.clear()
    return snap


# ------------------------------------------------------------------- sidebar
cfg = get_config()
storage = get_storage()

st.sidebar.title("📊 Crypto Intelligence")
symbol = st.sidebar.selectbox("Parite", cfg.symbols,
                              index=cfg.symbols.index(cfg.primary_symbol)
                              if cfg.primary_symbol in cfg.symbols else 0)

col_a, col_b = st.sidebar.columns(2)
if col_a.button("🔄 Tara", width="stretch"):
    run_scan(symbol)
if col_b.button("🏆 Tümü", width="stretch"):
    from pipeline import scan_all
    with st.spinner("Tüm pariteler taranıyor..."):
        scan_all(cfg.symbols, cfg)
    st.cache_data.clear()

auto = st.sidebar.checkbox("Otomatik yenile (60sn)", value=False)
if auto:
    st.sidebar.caption("Sayfa 60 saniyede bir yenilenir")
    st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)

snap = load_latest(symbol)
if not snap:
    st.warning(f"{symbol} için kayıtlı tarama yok. Soldaki **Tara** düğmesine basın "
               f"veya terminalde `python run.py scan {symbol}` çalıştırın.")
    st.stop()

ts = snap.get("timestamp", "")
try:
    age = datetime.now().astimezone() - datetime.fromisoformat(ts)
    age_txt = f"{int(age.total_seconds() // 60)} dk önce"
except Exception:  # noqa: BLE001
    age_txt = ts
st.sidebar.caption(f"Son tarama: {age_txt}")

score = snap["score"]
trend = snap["trend"]
deriv = snap["derivatives"]
flow = snap["order_flow"]
whale = snap["whale"]
book = snap["orderbook"]
sm = snap["smart_money"]
risk = snap["risk"]
setup = snap["setup"]

# --------------------------------------------------------------------- başlık
color = DECISION_COLOR.get(score["decision"], "#888")
st.markdown(
    f"""<div style="padding:18px 22px;border-radius:12px;background:linear-gradient(90deg,{color}22,transparent);
        border-left:6px solid {color}">
    <h2 style="margin:0">{symbol} · {snap['price']}</h2>
    <h3 style="margin:6px 0;color:{color}">{score['decision']} — Long {score['long_score']}/100
        · Short {score['short_score']}/100 · güven %{score['confidence']}</h3>
    <p style="margin:0;opacity:.85"><i>{score['answer']}</i></p></div>""",
    unsafe_allow_html=True)
st.write("")

oi = deriv.get("open_interest", {})
f = deriv.get("funding", {})


def kpi_grid(items):
    """Responsive gösterge ızgarası.

    st.columns kullanılmıyor: telefonda 6 sütun alt alta dizilip sayfayı
    uzatıyordu. CSS grid geniş ekranda 6, telefonda 2 sütun gösterir.
    Alt etiketler yön bilgisi olduğu için st.metric'in yanıltıcı yeşil
    oku da böylece devre dışı kalıyor.
    """
    cards = []
    for label, value, state, tone in items:
        color = {"up": "#66bb6a", "down": "#ef5350"}.get(tone, "rgba(255,255,255,.62)")
        cards.append(
            f'<div class="kpi"><div class="l">{label}</div>'
            f'<div class="v">{value}</div>'
            f'<div class="s" style="color:{color}">{state or "—"}</div></div>')
    st.markdown(f"""
<style>
  /* 132px: geniş ekranda 6 kart yan yana, telefonda 2 sütun olur */
  .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
               gap:9px; margin:4px 0 14px; }}
  .kpi {{ background:rgba(255,255,255,.045); border:1px solid rgba(255,255,255,.09);
          border-radius:10px; padding:9px 12px; }}
  .kpi .l {{ font-size:.72rem; opacity:.62; line-height:1.2; }}
  .kpi .v {{ font-size:1.22rem; font-weight:700; margin:3px 0 1px; }}
  .kpi .s {{ font-size:.72rem; }}
</style>
<div class="kpi-grid">{''.join(cards)}</div>""", unsafe_allow_html=True)


def _tone(value, positive_good=True):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "flat"
    if value > 0:
        return "up" if positive_good else "down"
    if value < 0:
        return "down" if positive_good else "up"
    return "flat"


kpi_grid([
    ("Open Interest (1s)", f"%{fmt(oi.get('change_1h_pct'))}",
     oi.get("interpretation_1h", {}).get("state", ""), "flat"),
    ("Funding", f"%{fmt(f.get('current_pct'), 4)}", f.get("health", ""), "flat"),
    ("Vadeli CVD", fmt(flow.get("futures", {}).get("delta"), 0),
     flow.get("label", ""), _tone(flow.get("futures", {}).get("delta"))),
    ("Spot CVD",
     fmt(flow.get("spot", {}).get("delta"), 0)
     if flow.get("spot", {}).get("available") else "—",
     flow.get("divergence", ""),
     _tone(flow.get("spot", {}).get("delta")) if flow.get("spot", {}).get("available") else "flat"),
    ("Balina deltası", fmt(whale.get("total_whale_delta_usdt"), 0),
     whale.get("state", ""), _tone(whale.get("total_whale_delta_usdt"))),
    ("Risk", risk.get("level", "—"), f"{risk.get('points')} risk puanı", "flat"),
])

tabs = st.tabs(["🎯 Karar", "📈 Trend", "🧠 Smart Money", "⚙️ Türev",
                "💧 Order Flow", "🐋 Balina & Kitap", "🔔 Alarmlar", "🏆 Sıralama",
                "🌍 Tüm Piyasa"])

# ------------------------------------------------------------------ 1) Karar
with tabs[0]:
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Skor Dağılımı")
        comp = pd.DataFrame(score["components"])
        fig = go.Figure(go.Bar(
            x=comp["points"], y=comp["name"], orientation="h",
            marker_color=["#43a047" if p > 0 else "#e53935" if p < 0 else "#9e9e9e"
                          for p in comp["points"]],
            text=[f"{p:+.1f} / {m}" for p, m in zip(comp["points"], comp["max_points"])],
            textposition="outside",
            hovertext=comp["detail"], hoverinfo="text",
        ))
        fig.update_layout(height=430, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="Ağırlıklı puan", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig)

        st.dataframe(
            comp[["name", "points", "max_points", "direction", "detail"]].rename(columns={
                "name": "Gösterge", "points": "Puan", "max_points": "Maks",
                "direction": "Yön", "detail": "Detay"}),
            width="stretch", hide_index=True)

    with right:
        st.subheader("AI Trade Setup")
        if setup.get("available"):
            st.markdown(f"### :{'green' if setup['direction'] == 'LONG' else 'red'}"
                        f"[{setup['direction']}]  ·  olasılık %{setup['probability']}")
            rows = [
                ("Giriş bölgesi", f"{setup['entry_zone'][0]} – {setup['entry_zone'][1]}"),
                ("Giriş", setup["entry"]),
                ("Stop", f"{setup['stop']}  (%{setup['stop_distance_pct']})"),
            ]
            for t in setup["targets"]:
                rows.append((t["name"], f"{t['price']}  ({t['r_multiple']}R, "
                                        f"%{t['gain_pct']:+.2f})"))
            rows += [
                ("R/R", f"{setup['risk_reward']}" + ("" if setup["rr_ok"] else " ⚠️ düşük")),
                ("Pozisyon", f"{setup['position']['qty']} adet "
                             f"(~{fmt(setup['position']['notional_usdt'], 0)} USDT)"),
                ("Maks kaldıraç", f"{setup['position']['suggested_max_leverage']}x"),
                ("Giriş dayanağı", setup["entry_basis"]),
                ("Stop dayanağı", setup["stop_basis"]),
            ]
            # Değerler karışık tipte (sayı + metin) olduğu için tamamı metne çevrilir;
            # aksi hâlde Arrow dönüşümü hata veriyor.
            st.table(pd.DataFrame([(a, str(b)) for a, b in rows],
                                  columns=["Alan", "Değer"]).set_index("Alan"))
            st.caption("Geçersizlik: " + "; ".join(setup.get("invalidation", [])))
        else:
            st.info(setup.get("reason", "Setup yok"))

        st.subheader("Risk Faktörleri")
        st.dataframe(pd.DataFrame(risk["factors"]).rename(columns={
            "factor": "Faktör", "value": "Değer", "state": "Durum", "points": "Puan"}),
            width="stretch", hide_index=True)

    st.subheader("Skor Geçmişi")
    hist = load_score_series(symbol, 300)
    if not hist.empty and len(hist) > 1:
        hist["ts"] = pd.to_datetime(hist["ts"], format="ISO8601")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=hist["ts"], y=hist["long_score"], name="Long skor",
                                 line=dict(color="#43a047", width=2)), secondary_y=False)
        fig.add_trace(go.Scatter(x=hist["ts"], y=hist["price"], name="Fiyat",
                                 line=dict(color="#90a4ae", width=1, dash="dot")),
                      secondary_y=True)
        fig.add_hline(y=62, line_dash="dash", line_color="#43a047", opacity=.4)
        fig.add_hline(y=38, line_dash="dash", line_color="#e53935", opacity=.4)
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
        fig.update_yaxes(title_text="Long skor", range=[0, 100], secondary_y=False)
        fig.update_yaxes(title_text="Fiyat", secondary_y=True)
        st.plotly_chart(fig)
    else:
        st.caption("Skor geçmişi için en az iki tarama gerekiyor.")

# ------------------------------------------------------------------ 2) Trend
with tabs[1]:
    tf_names = {"ltf": cfg.get("timeframes.ltf"), "mtf": cfg.get("timeframes.mtf"),
                "htf": cfg.get("timeframes.htf")}
    rows = []
    for key, name in tf_names.items():
        tf = trend.get("timeframes", {}).get(key, {})
        if not tf.get("available"):
            continue
        rows.append({
            "TF": name, "Yön": tf["label"], "EMA dizilimi": tf["ema_alignment"],
            "ADX": f"{tf['adx']['value']:.1f} ({tf['adx']['strength']})",
            "SuperTrend": tf["supertrend"]["direction"] + (" ⚡dönüş" if tf["supertrend"]["flipped"] else ""),
            "Yapı": tf["structure"]["state"],
            "Son etiketler": " → ".join(tf["structure"]["recent_labels"]),
            "RSI": round(tf["rsi"], 1), "ATR %": tf["atr"]["pct"],
            "VWAP-D farkı %": tf["vwap"]["price_vs_daily_pct"],
            "VWAP-W farkı %": tf["vwap"]["price_vs_weekly_pct"],
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    interval = st.selectbox("Grafik zaman dilimi",
                            [tf_names["ltf"], tf_names["mtf"], tf_names["htf"]], index=1)
    df = load_candles(symbol, interval, 300)
    if not df.empty:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
                            vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=df["open_time"], open=df["open"], high=df["high"],
                                     low=df["low"], close=df["close"], name="Fiyat"), row=1, col=1)
        for p, c in ((20, "#42a5f5"), (50, "#ab47bc"), (100, "#ffa726"), (200, "#ef5350")):
            if f"ema{p}" in df:
                fig.add_trace(go.Scatter(x=df["open_time"], y=df[f"ema{p}"], name=f"EMA{p}",
                                         line=dict(width=1, color=c)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["open_time"], y=df["vwap_d"], name="VWAP-D",
                                 line=dict(width=1.5, color="#26c6da", dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["open_time"], y=df["supertrend"], name="SuperTrend",
                                 line=dict(width=1, color="#66bb6a", dash="dash")), row=1, col=1)

        # smart money bölgeleri (yalnızca ana zaman diliminde anlamlı)
        if interval == tf_names["mtf"]:
            for fv in sm.get("fvg", {}).get("open", [])[:6]:
                fig.add_hrect(y0=fv["bottom"], y1=fv["top"],
                              fillcolor="#43a047" if fv["direction"] == "bullish" else "#e53935",
                              opacity=0.12, line_width=0, row=1, col=1)
            for ob in sm.get("order_blocks", {}).get("fresh", [])[:6]:
                fig.add_hrect(y0=ob["bottom"], y1=ob["top"],
                              fillcolor="#1e88e5" if ob["direction"] == "bullish" else "#fb8c00",
                              opacity=0.10, line_width=0, row=1, col=1)

        fig.add_trace(go.Bar(x=df["open_time"], y=df["volume"], name="Hacim",
                             marker_color="#78909c"), row=2, col=1)
        fig.update_layout(height=620, xaxis_rangeslider_visible=False,
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig)

    mtf = trend.get("timeframes", {}).get("mtf", {})
    if mtf.get("structure", {}).get("points"):
        st.subheader("Market Structure (HH / HL / LH / LL)")
        st.dataframe(pd.DataFrame(mtf["structure"]["points"]).rename(columns={
            "time": "Zaman", "type": "Tip", "price": "Fiyat", "label": "Etiket"}),
            width="stretch", hide_index=True)

# ------------------------------------------------------------ 3) Smart Money
with tabs[2]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Likidite Süpürmeleri")
        sweeps = sm.get("liquidity_sweeps", [])
        if sweeps:
            st.dataframe(pd.DataFrame(sweeps)[
                ["type", "time", "swept_level", "wick_ratio", "volume_ratio",
                 "volume_confirmed", "bars_ago"]].rename(columns={
                    "type": "Tip", "time": "Zaman", "swept_level": "Süpürülen seviye",
                    "wick_ratio": "Fitil oranı", "volume_ratio": "Hacim x",
                    "volume_confirmed": "Hacim teyidi", "bars_ago": "Kaç mum önce"}),
                width="stretch", hide_index=True)
        else:
            st.caption("Tespit edilen süpürme yok")

        st.subheader("Yapı Kırılımları (BOS / CHOCH)")
        breaks = sm.get("structure_breaks", [])
        if breaks:
            st.dataframe(pd.DataFrame(breaks)[
                ["type", "direction", "time", "broken_level", "bars_ago"]].rename(columns={
                    "type": "Tip", "direction": "Yön", "time": "Zaman",
                    "broken_level": "Kırılan seviye", "bars_ago": "Kaç mum önce"}),
                width="stretch", hide_index=True)
        else:
            st.caption("Kırılım yok")

    with c2:
        st.subheader("Fair Value Gap (açık)")
        fvgs = sm.get("fvg", {}).get("open", [])
        if fvgs:
            st.dataframe(pd.DataFrame(fvgs)[
                ["type", "bottom", "top", "size_atr", "distance_pct", "mitigated",
                 "bars_ago"]].rename(columns={
                    "type": "Tip", "bottom": "Alt", "top": "Üst", "size_atr": "Boyut (ATR)",
                    "distance_pct": "Uzaklık %", "mitigated": "Dokunuldu",
                    "bars_ago": "Kaç mum önce"}),
                width="stretch", hide_index=True)
        else:
            st.caption("Açık FVG yok")

        st.subheader("Order Block (taze)")
        obs = sm.get("order_blocks", {}).get("fresh", [])
        if obs:
            st.dataframe(pd.DataFrame(obs)[
                ["type", "bottom", "top", "displacement_atr", "distance_pct",
                 "bars_ago"]].rename(columns={
                    "type": "Tip", "bottom": "Alt", "top": "Üst",
                    "displacement_atr": "Hareket (ATR)", "distance_pct": "Uzaklık %",
                    "bars_ago": "Kaç mum önce"}),
                width="stretch", hide_index=True)
        else:
            st.caption("Taze order block yok")

# ---------------------------------------------------------------- 4) Türev
with tabs[3]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Open Interest")
        series = oi.get("series", [])
        if series:
            d = pd.DataFrame(series)
            d["time"] = pd.to_datetime(d["time"], format="ISO8601")
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(x=d["time"], y=d["oi"], name="OI (adet)",
                                     line=dict(color="#42a5f5")), secondary_y=False)
            fig.add_trace(go.Scatter(x=d["time"], y=d["oi_usdt"], name="OI (USDT)",
                                     line=dict(color="#ffa726", dash="dot")), secondary_y=True)
            fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig)
        st.write(pd.DataFrame([
            {"Pencere": "1 saat", "Değişim %": oi.get("change_1h_pct"),
             "Yorum": oi.get("interpretation_1h", {}).get("state")},
            {"Pencere": "4 saat", "Değişim %": oi.get("change_4h_pct"),
             "Yorum": oi.get("interpretation_4h", {}).get("state")},
            {"Pencere": "24 saat", "Değişim %": oi.get("change_24h_pct"), "Yorum": ""},
        ]))
        st.caption(oi.get("interpretation_1h", {}).get("meaning", ""))

    with c2:
        st.subheader("Funding")
        fh = f.get("history", [])
        if fh:
            d = pd.DataFrame(fh)
            d["time"] = pd.to_datetime(d["time"], format="ISO8601")
            fig = go.Figure(go.Bar(x=d["time"], y=d["rate_pct"],
                                   marker_color=["#43a047" if v >= 0 else "#e53935"
                                                 for v in d["rate_pct"]]))
            fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="Funding %")
            st.plotly_chart(fig)
        st.write(pd.DataFrame([{
            "Şu an %": f.get("current_pct"), "Ortalama %": f.get("avg_pct"),
            "Tahmini %": f.get("predicted_pct"), "Yıllık %": f.get("annualized_pct"),
            "Durum": f.get("health"), "Trend": f.get("trend")}]))
        st.caption(f.get("bias", ""))

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("Long / Short Oranları")
        ls = deriv.get("long_short", {})
        st.write(pd.DataFrame([{
            "Büyük hesap (pozisyon)": ls.get("top_positions_ratio"),
            "Büyük hesap (hesap)": ls.get("top_accounts_ratio"),
            "Global hesap": ls.get("global_accounts_ratio"),
            "6 bar değişim %": ls.get("top_positions_delta_pct")}]))
        if ls.get("series"):
            d = pd.DataFrame(ls["series"])
            d["time"] = pd.to_datetime(d["time"], format="ISO8601")
            fig = go.Figure(go.Scatter(x=d["time"], y=d["ratio"], line=dict(color="#ab47bc")))
            fig.add_hline(y=1.0, line_dash="dash", opacity=.4)
            fig.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis_title="Long/Short")
            st.plotly_chart(fig)
        for n in ls.get("notes", []):
            st.caption(f"• {n}")

    with c4:
        st.subheader("Taker Buy / Sell")
        taker = deriv.get("taker", {})
        if taker.get("available"):
            d = pd.DataFrame(taker["series"])
            d["time"] = pd.to_datetime(d["time"], format="ISO8601")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=d["time"], y=d["buy"], name="Alım", marker_color="#43a047"))
            fig.add_trace(go.Bar(x=d["time"], y=-d["sell"], name="Satım", marker_color="#e53935"))
            fig.update_layout(height=240, barmode="relative",
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig)
            st.write(pd.DataFrame([{
                "Alım hacmi": taker.get("buy_volume"), "Satım hacmi": taker.get("sell_volume"),
                "Delta": taker.get("delta"), "Dengesizlik %": taker.get("imbalance_pct"),
                "Durum": taker.get("state")}]))

        st.subheader("Likidasyonlar")
        liq = deriv.get("liquidations", {})
        if liq.get("available"):
            st.write(pd.DataFrame([{
                "Long likidasyon": liq.get("long_usdt"), "Short likidasyon": liq.get("short_usdt"),
                "Toplam": liq.get("total_usdt"), "Adet": liq.get("count"),
                "Squeeze": liq.get("squeeze")}]))
            if liq.get("largest"):
                st.dataframe(pd.DataFrame(liq["largest"]), width="stretch",
                             hide_index=True)
        else:
            st.info(liq.get("note", "Likidasyon verisi yok"))

    basis = deriv.get("basis", {})
    if basis.get("available"):
        st.subheader("Basis (Perpetual − Spot)")
        st.write(pd.DataFrame([{
            "Perp mark": basis.get("perp_mark"), "Spot": basis.get("spot_price"),
            "Fark": basis.get("basis"), "Fark %": basis.get("basis_pct"),
            "Durum": basis.get("state")}]))

# ------------------------------------------------------------ 5) Order Flow
with tabs[4]:
    c1, c2 = st.columns(2)
    fut = flow.get("futures", {})
    spot = flow.get("spot", {})

    with c1:
        st.subheader("Kümülatif Delta (CVD)")
        fig = go.Figure()
        if fut.get("series"):
            d = pd.DataFrame(fut["series"])
            d["time"] = pd.to_datetime(d["time"], format="ISO8601")
            fig.add_trace(go.Scatter(x=d["time"], y=d["cvd"], name="Vadeli CVD",
                                     line=dict(color="#42a5f5", width=2)))
        if spot.get("series"):
            d = pd.DataFrame(spot["series"])
            d["time"] = pd.to_datetime(d["time"], format="ISO8601")
            fig.add_trace(go.Scatter(x=d["time"], y=d["cvd"], name="Spot CVD",
                                     line=dict(color="#ffa726", width=2)))
        fig.add_hline(y=0, line_dash="dash", opacity=.4)
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis_title="Kümülatif delta (USDT)", legend=dict(orientation="h"))
        st.plotly_chart(fig)

    with c2:
        st.subheader("Agresif Alıcı / Satıcı")
        rows = []
        if fut.get("available"):
            rows.append({"Piyasa": "Vadeli", "Alım": fut["buy"], "Satım": fut["sell"],
                         "Delta": fut["delta"], "Dengesizlik %": fut["imbalance_pct"],
                         "İşlem": fut["trades"]})
        if spot.get("available"):
            rows.append({"Piyasa": "Spot", "Alım": spot["buy"], "Satım": spot["sell"],
                         "Delta": spot["delta"], "Dengesizlik %": spot["imbalance_pct"],
                         "İşlem": spot["trades"]})
        if rows:
            d = pd.DataFrame(rows)
            st.dataframe(d, width="stretch", hide_index=True)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=d["Piyasa"], y=d["Alım"], name="Agresif alım",
                                 marker_color="#43a047"))
            fig.add_trace(go.Bar(x=d["Piyasa"], y=-d["Satım"], name="Agresif satım",
                                 marker_color="#e53935"))
            fig.update_layout(height=250, barmode="relative",
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig)

        st.info(f"**{flow.get('divergence')}** — {flow.get('divergence_note')}")
        if fut.get("window_minutes"):
            st.caption(f"Pencere: son {fut['window_minutes']} dakika · "
                       f"{fut.get('trades')} vadeli işlem")

# --------------------------------------------------------- 6) Balina & Kitap
with tabs[5]:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Balina Dilimleri")
        sc = whale.get("tier_scaling", {})
        if sc.get("scaled"):
            st.caption(f"⚙️ Bu paritede tek işlem 100k USDT'yi nadiren aştığı için eşikler "
                       f"otomatik ölçeklendi (taban ≈ {fmt(sc.get('base'), 0)} USDT, "
                       f"%{sc.get('percentile')} yüzdelik).")
        for mkt_key, mkt_name in (("futures", "Vadeli"), ("spot", "Spot")):
            m = whale.get(mkt_key, {})
            if not m.get("available"):
                continue
            st.markdown(f"**{mkt_name}** — {m['state']} "
                        f"(delta {fmt(m['whale_delta_usdt'], 0)} USDT)")
            rows = [{"Dilim": k, "Eşik USDT": v.get("threshold_usdt"), "İşlem": v["count"],
                     "Alım": v["buy_usdt"], "Satım": v["sell_usdt"], "Delta": v["delta_usdt"]}
                    for k, v in m.get("tiers", {}).items()]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        st.subheader("En Büyük İşlemler")
        big = (whale.get("futures", {}).get("largest_trades", []) or [])[:10]
        if big:
            st.dataframe(pd.DataFrame(big).rename(columns={
                "time": "Zaman", "side": "Yön", "price": "Fiyat", "qty": "Miktar",
                "notional": "USDT"}), width="stretch", hide_index=True)

        ice = (whale.get("futures", {}).get("icebergs", []) or []) + \
              (whale.get("spot", {}).get("icebergs", []) or [])
        if ice:
            st.subheader("Iceberg Şüphesi")
            st.dataframe(pd.DataFrame(ice).rename(columns={
                "qty": "Miktar", "side": "Yön", "repeats": "Tekrar",
                "total_notional": "Toplam USDT", "avg_price": "Ort. fiyat",
                "span_seconds": "Süre (sn)"}), width="stretch", hide_index=True)

    with c2:
        st.subheader("Order Book Derinliği")
        if book.get("available"):
            dc = book.get("depth_chart", {})
            bids = pd.DataFrame(dc.get("bids", []))
            asks = pd.DataFrame(dc.get("asks", []))
            if not bids.empty and not asks.empty:
                bids = bids.sort_values("price", ascending=False)
                bids["cum"] = bids["notional"].cumsum()
                asks = asks.sort_values("price")
                asks["cum"] = asks["notional"].cumsum()
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=bids["price"], y=bids["cum"], name="Bid (kümülatif)",
                                         fill="tozeroy", line=dict(color="#43a047")))
                fig.add_trace(go.Scatter(x=asks["price"], y=asks["cum"], name="Ask (kümülatif)",
                                         fill="tozeroy", line=dict(color="#e53935")))
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                  xaxis_title="Fiyat", yaxis_title="Kümülatif USDT")
                st.plotly_chart(fig)

            st.write(pd.DataFrame([{
                "Durum": book["state"], "Yakın denge %": book["near_imbalance_pct"],
                "Toplam denge %": book["full_imbalance_pct"],
                "Spread %": book["spread_pct"], "Seviye": book["levels_read"]}]))

            if book.get("bid_walls") or book.get("ask_walls"):
                st.markdown("**Duvarlar**")
                st.dataframe(pd.DataFrame(book.get("bid_walls", []) + book.get("ask_walls", []))
                             .rename(columns={"side": "Taraf", "price": "Fiyat", "qty": "Miktar",
                                              "notional": "USDT", "x_average": "Ort. x",
                                              "distance_pct": "Uzaklık %"}),
                             width="stretch", hide_index=True)
            if book.get("spoofs"):
                st.markdown("**⚠️ Spoof şüphesi**")
                st.dataframe(pd.DataFrame(book["spoofs"]), width="stretch",
                             hide_index=True)
            if book.get("absorptions"):
                st.markdown("**Absorption**")
                st.dataframe(pd.DataFrame(book["absorptions"]), width="stretch",
                             hide_index=True)
            st.caption(book.get("compare_note", ""))

# --------------------------------------------------------------- 7) Alarmlar
with tabs[6]:
    st.subheader("Son Alarmlar")
    alerts = storage.recent_alerts(symbol, 100)
    if alerts:
        d = pd.DataFrame(alerts)[["ts", "rule", "severity", "title", "message"]]
        st.dataframe(d.rename(columns={"ts": "Zaman", "rule": "Kural", "severity": "Önem",
                                       "title": "Başlık", "message": "Mesaj"}),
                     width="stretch", hide_index=True)
    else:
        st.caption("Kayıtlı alarm yok")

    st.subheader("Alarm Kuralları")
    rules = cfg.get("alerts.rules", {})
    st.json(rules)
    ch = cfg.get("alerts.channels", {})
    st.caption(f"Kanallar — konsol: {ch.get('console')} · telegram: {ch.get('telegram')} "
               f"· e-posta: {ch.get('email')}")

# -------------------------------------------------------------- 8) Sıralama
with tabs[7]:
    st.subheader("Parite Sıralaması")
    rows = []
    for sym in cfg.symbols:
        s = load_latest(sym)
        if not s:
            continue
        sc = s["score"]
        rows.append({
            "Parite": sym, "Fiyat": s["price"], "Long": sc["long_score"],
            "Short": sc["short_score"], "Karar": sc["decision"], "Güven %": sc["confidence"],
            "Trend": s["trend"].get("label"),
            "OI 1s %": s["derivatives"].get("open_interest", {}).get("change_1h_pct"),
            "Funding %": s["derivatives"].get("funding", {}).get("current_pct"),
            "CVD": s["order_flow"].get("label"), "Balina": s["whale"].get("state"),
            "Risk": s["risk"].get("level"),
            "Setup": s["setup"].get("direction") if s["setup"].get("available") else "-",
            "Tarama": s["timestamp"][:16].replace("T", " "),
        })
    if rows:
        d = pd.DataFrame(rows).sort_values("Long", ascending=False).reset_index(drop=True)
        d.index = d.index + 1
        st.dataframe(d, width="stretch")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=d["Parite"], y=d["Long"], name="Long skoru",
                             marker_color="#43a047"))
        fig.add_trace(go.Bar(x=d["Parite"], y=d["Short"], name="Short skoru",
                             marker_color="#e53935"))
        fig.update_layout(barmode="group", height=320,
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig)
    else:
        st.caption("Henüz tarama yok — soldaki **Tümü** düğmesine basın.")

# ----------------------------------------------------------- 9) Tüm Piyasa
with tabs[8]:
    st.subheader("Binance Vadeli — Tüm Piyasa Ön Elemesi")
    st.caption("Piyasadaki tüm sürekli pariteler ucuz toplu veriyle taranır "
               "(fiyat, hacim, funding, Open Interest). 'Dikkat' skoru yön değil, "
               "hareketlilik ölçer — bakmaya değer mi sorusunu yanıtlar.")

    c1, c2, c3 = st.columns([1, 1, 2])
    only_screen = c1.button("🔍 Ön eleme (~40 sn)", width="stretch")
    full_scan = c2.button("🚀 Ön eleme + derin tarama", width="stretch")

    if only_screen or full_scan:
        from pipeline import scan_market
        box = st.empty()
        with st.spinner("Tüm piyasa taranıyor..."):
            scan_market(cfg, deep=bool(full_scan),
                        progress=lambda m: box.caption(m))
        box.empty()
        st.cache_data.clear()
        st.rerun()

    scr = storage.latest_screening()
    if not scr:
        st.info("Henüz piyasa taraması yapılmadı. Yukarıdaki düğmeye basın veya "
                "terminalde `python run.py market` çalıştırın.")
    else:
        st.caption(f"Son piyasa taraması: {scr['ts'][:16].replace('T', ' ')} · "
                   f"{scr['total']} parite")
        m = pd.DataFrame(scr["records"])

        f1, f2, f3 = st.columns(3)
        min_interest = f1.slider("En düşük dikkat skoru", 0, 100, 0, 5)
        durum_secenek = ["(hepsi)"] + sorted(m["oi_state"].dropna().unique().tolist()) \
            if "oi_state" in m.columns else ["(hepsi)"]
        durum = f2.selectbox("OI durumu", durum_secenek)
        egilim = f3.selectbox("Ön eğilim", ["(hepsi)", "LONG EĞİLİM", "SHORT EĞİLİM", "NÖTR"])

        view = m[m["interest"] >= min_interest] if "interest" in m.columns else m
        if durum != "(hepsi)":
            view = view[view["oi_state"] == durum]
        if egilim != "(hepsi)":
            view = view[view["bias_label"] == egilim]

        show = view.rename(columns={
            "symbol": "Parite", "lastPrice": "Fiyat",
            "priceChangePercent": "24s %", "quoteVolume": "24s Hacim",
            "funding_pct": "Funding %", "oi_usdt": "OI (USDT)",
            "oi_change_1h": "OI 1s %", "oi_change_4h": "OI 4s %",
            "price_change_1h": "Fiyat 1s %", "oi_state": "OI Durumu",
            "interest": "Dikkat", "bias_label": "Ön eğilim"})
        drop = [c for c in ("oi", "bias", "markPrice", "indexPrice") if c in show.columns]
        st.dataframe(show.drop(columns=drop), width="stretch", height=520)
        st.caption(f"{len(view)} parite gösteriliyor")

        if "interest" in m.columns and len(m) > 1:
            top = m.nlargest(20, "interest")
            fig = go.Figure(go.Bar(
                x=top["interest"], y=top["symbol"], orientation="h",
                marker_color=["#43a047" if b == "LONG EĞİLİM" else
                              "#e53935" if b == "SHORT EĞİLİM" else "#9e9e9e"
                              for b in top.get("bias_label", [""] * len(top))],
                text=[f"{v:.0f}" for v in top["interest"]], textposition="outside"))
            fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10),
                              xaxis_title="Dikkat skoru",
                              yaxis=dict(autorange="reversed"),
                              title="En dikkat çekici 20 parite (renk = ön eğilim)")
            st.plotly_chart(fig)

st.caption("Bu panel otomatik üretilmiş veri özetidir, yatırım tavsiyesi değildir. "
           "Veri kaynağı: Binance halka açık market-data API'leri.")
