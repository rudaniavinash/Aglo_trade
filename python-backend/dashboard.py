"""
Streamlit Dashboard — Main entry point.
LIVE algo trading dashboard with all panels.
Run: streamlit run dashboard.py
"""

import streamlit as st
import time
import config
from login import create_session, get_profile, get_margin, refresh_session
from data_feed import (
    start_websocket, stop_websocket, is_ws_connected,
    get_live_ltp, get_all_live_prices, get_index_candles_5m, get_index_candles_15m,
)
from strategy import compute_indicators, generate_signal
from strike_selector import select_strike
from risk import (
    get_state as get_risk_state, can_trade, set_emergency_stop,
    reset_daily, set_max_daily_loss, set_risk_per_trade,
)
from orders import execute_entry, execute_exit, kill_switch, get_positions
from analytics import compute_analytics, compute_charges_per_trade
from utils import is_market_open, is_no_trade_window, is_square_off_time, format_inr

# ── Page Config ──────────────────────────────────
st.set_page_config(page_title="AlgoTrader Pro — LIVE", layout="wide", page_icon="📈")

# ── Session Init ─────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "trading_mode" not in st.session_state:
    st.session_state.trading_mode = "Signal Only"
if "selected_index" not in st.session_state:
    st.session_state.selected_index = "NIFTY"
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True

# ── Login ────────────────────────────────────────
if not st.session_state.logged_in:
    st.title("🔐 AlgoTrader Pro — Login")
    col1, col2 = st.columns(2)
    with col1:
        api_key = st.text_input("API Key", value=config.API_KEY, type="password")
        client_id = st.text_input("Client ID", value=config.CLIENT_ID)
    with col2:
        mpin = st.text_input("MPIN", type="password", value=config.MPIN)
        totp_secret = st.text_input("TOTP Secret", type="password", value=config.TOTP_SECRET)

    if st.button("🚀 Login & Start", type="primary", use_container_width=True):
        config.API_KEY = api_key
        config.CLIENT_ID = client_id
        config.MPIN = mpin
        config.TOTP_SECRET = totp_secret
        try:
            with st.spinner("Connecting to Angel One..."):
                create_session()
                start_websocket()
            st.session_state.logged_in = True
            st.success("✅ Connected!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Login failed: {e}")
    st.stop()

# ══════════════════════════════════════════════════
# MAIN DASHBOARD
# ══════════════════════════════════════════════════

# ── Top Bar ──────────────────────────────────────
top = st.columns([3, 1, 1, 1, 1])
with top[0]:
    st.markdown("## 📈 AlgoTrader Pro <span style='background:#22c55e;color:white;padding:2px 8px;border-radius:4px;font-size:12px'>LIVE</span>", unsafe_allow_html=True)
with top[1]:
    ws_status = "🟢 Connected" if is_ws_connected() else "🔴 Disconnected"
    st.metric("WebSocket", ws_status)
with top[2]:
    st.metric("Market", "🟢 OPEN" if is_market_open() else "🔴 CLOSED")
with top[3]:
    st.metric("Time", time.strftime("%H:%M:%S"))
with top[4]:
    risk_state = get_risk_state()
    if risk_state["trading_disabled"] or risk_state["emergency_stop"]:
        st.error("⛔ TRADING DISABLED")
    else:
        st.success("✅ TRADING ACTIVE")

st.divider()

# ── Emergency Banner ─────────────────────────────
risk_state = get_risk_state()
if risk_state["emergency_stop"]:
    st.error("⛔ **EMERGENCY STOP ACTIVE** — All trading disabled for today", icon="🚨")
elif risk_state["trading_disabled"]:
    st.warning("⚠️ **Trading Disabled** — Daily limit reached", icon="⚠️")

# ── Controls Row ─────────────────────────────────
ctrl = st.columns([2, 2, 1, 1, 1])
with ctrl[0]:
    st.session_state.selected_index = st.selectbox(
        "Index", list(config.INDEXES.keys()),
        index=list(config.INDEXES.keys()).index(st.session_state.selected_index),
    )
with ctrl[1]:
    st.session_state.trading_mode = st.selectbox(
        "Trading Mode", ["Signal Only", "Semi Auto", "Full Auto"],
    )
with ctrl[2]:
    if st.button("🔴 KILL SWITCH", type="primary", use_container_width=True):
        result = kill_switch()
        st.warning(f"Kill switch: {result}")
with ctrl[3]:
    if st.button("⛔ EMERGENCY STOP", use_container_width=True):
        set_emergency_stop(True)
        st.rerun()
with ctrl[4]:
    if st.button("🔄 Reset Day", use_container_width=True):
        reset_daily()
        st.rerun()

st.divider()

# ── Fetch Data & Signal ──────────────────────────
idx = st.session_state.selected_index
live_ltp = get_live_ltp(idx)

# Use live LTP if available, else fetch from candles
df_5m = get_index_candles_5m(idx)
df_15m = get_index_candles_15m(idx)
indicators = compute_indicators(df_5m, df_15m)
signal = generate_signal(idx, indicators)

# Override LTP with live feed if available
if live_ltp > 0:
    signal["ltp"] = live_ltp

# ══════════════════════════════════════════════════
# LIVE SIGNAL PANEL
# ══════════════════════════════════════════════════

st.subheader("🔔 LIVE SIGNAL")

if signal["type"] == "CALL":
    st.markdown(
        f"""<div style='background:linear-gradient(135deg,#065f46,#047857);padding:24px;border-radius:12px;text-align:center'>
        <h1 style='color:white;margin:0'>🟢 BUY {signal['strike_label']}</h1>
        <p style='color:#a7f3d0;font-size:18px'>Confidence: {signal['confidence']:.0f}% | R:R {signal['risk_reward']}</p>
        </div>""",
        unsafe_allow_html=True,
    )
elif signal["type"] == "PUT":
    st.markdown(
        f"""<div style='background:linear-gradient(135deg,#7f1d1d,#b91c1c);padding:24px;border-radius:12px;text-align:center'>
        <h1 style='color:white;margin:0'>🔴 BUY {signal['strike_label']}</h1>
        <p style='color:#fecaca;font-size:18px'>Confidence: {signal['confidence']:.0f}% | R:R {signal['risk_reward']}</p>
        </div>""",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""<div style='background:linear-gradient(135deg,#1e293b,#334155);padding:24px;border-radius:12px;text-align:center'>
        <h1 style='color:#94a3b8;margin:0'>⚪ NO TRADE ZONE</h1>
        <p style='color:#64748b;font-size:16px'>{signal['reason']}</p>
        </div>""",
        unsafe_allow_html=True,
    )

# Signal Details
s1, s2, s3, s4, s5, s6 = st.columns(6)
s1.metric("LTP", f"₹{signal['ltp']:,.2f}")
s2.metric("RSI", f"{signal['rsi']:.1f}")
s3.metric("Trend (5m)", signal["trend"])
s4.metric("Trend (15m)", signal["trend_15m"])
s5.metric("Target", f"₹{signal['target']:,.2f}" if signal["target"] else "—")
s6.metric("Stop Loss", f"₹{signal['stoploss']:,.2f}" if signal["stoploss"] else "—")

st.divider()

# ── Live Index Prices ────────────────────────────
st.subheader("📊 Live Index Prices")
prices = get_all_live_prices()
pcols = st.columns(len(config.INDEXES))
for i, (name, _) in enumerate(config.INDEXES.items()):
    with pcols[i]:
        ltp = prices.get(name, 0)
        st.metric(name, f"₹{ltp:,.2f}" if ltp else "—")

st.divider()

# ── Trading Actions ──────────────────────────────
if st.session_state.trading_mode == "Semi Auto":
    st.subheader("🎯 Manual Execution")
    ac1, ac2 = st.columns(2)
    with ac1:
        if st.button("🟢 BUY CE", use_container_width=True, disabled=risk_state["trading_disabled"]):
            if signal["type"] == "CALL":
                result = execute_entry(signal)
                st.success(f"Order: {result}")
            else:
                st.warning("No CALL signal active")
    with ac2:
        if st.button("🔴 BUY PE", use_container_width=True, disabled=risk_state["trading_disabled"]):
            if signal["type"] == "PUT":
                result = execute_entry(signal)
                st.success(f"Order: {result}")
            else:
                st.warning("No PUT signal active")

elif st.session_state.trading_mode == "Full Auto":
    st.info("🤖 **Full Auto Mode** — Orders execute automatically on valid signals")
    can, reason = can_trade()
    if can and signal["type"] != "NO_TRADE" and not is_no_trade_window() and not is_square_off_time():
        result = execute_entry(signal)
        st.success(f"Auto-executed: {result}")

# ── Active Trade ─────────────────────────────────
active = risk_state.get("active_trade")
if active:
    st.subheader("📌 Active Position")
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Symbol", active["symbol"])
    p2.metric("Entry", f"₹{active['entry_price']:,.2f}")
    p3.metric("Qty", active["quantity"])
    p4.metric("Target", f"₹{active['target']:,.2f}")
    p5.metric("Stop Loss", f"₹{active['current_sl']:,.2f}")

    if st.button("🔻 EXIT TRADE", type="primary"):
        result = execute_exit("Manual exit")
        st.info(f"Exit: {result}")
        st.rerun()

    st.divider()

# ── P&L & Risk ───────────────────────────────────
st.subheader("💰 P&L & Risk")
r1, r2, r3, r4, r5 = st.columns(5)
r1.metric("Daily P&L", format_inr(risk_state["daily_pnl"]))
r2.metric("Trades Today", f"{risk_state['trades_today']}/{config.MAX_TRADES_PER_DAY}")
r3.metric("Consec. Losses", risk_state["consecutive_losses"])
r4.metric("Max Daily Loss", format_inr(-risk_state["max_daily_loss"]))
r5.metric("Volume Spike", "✅ Yes" if signal.get("volume_spike") else "❌ No")

st.divider()

# ── Risk Settings ────────────────────────────────
with st.expander("⚙️ Risk Settings"):
    rc1, rc2 = st.columns(2)
    with rc1:
        new_max_loss = st.number_input("Max Daily Loss (₹)", value=risk_state["max_daily_loss"], step=500)
        if new_max_loss != risk_state["max_daily_loss"]:
            set_max_daily_loss(new_max_loss)
    with rc2:
        new_risk = st.number_input("Risk Per Trade (%)", value=risk_state["risk_per_trade_pct"], step=0.5)
        if new_risk != risk_state["risk_per_trade_pct"]:
            set_risk_per_trade(new_risk)

# ── Analytics ────────────────────────────────────
st.subheader("📊 Analytics")
stats = compute_analytics()
a1, a2, a3, a4, a5, a6 = st.columns(6)
a1.metric("Total Trades", stats["total_trades"])
a2.metric("Win Rate", f"{stats['win_rate']:.1f}%")
a3.metric("Avg Win", format_inr(stats["avg_win"]))
a4.metric("Avg Loss", format_inr(-stats["avg_loss"]))
a5.metric("Profit Factor", f"{stats['profit_factor']:.2f}" if stats["profit_factor"] != float("inf") else "∞")
a6.metric("Net P&L", format_inr(stats["net_pnl"]))

# Equity Curve
if stats["equity_curve"]:
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[e["trade"] for e in stats["equity_curve"]],
        y=[e["equity"] for e in stats["equity_curve"]],
        mode="lines+markers",
        fill="tozeroy",
        line=dict(color="#22c55e", width=2),
    ))
    fig.update_layout(
        title="Equity Curve",
        xaxis_title="Trade #",
        yaxis_title="Cumulative P&L (₹)",
        template="plotly_dark",
        height=300,
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Trade Log ────────────────────────────────────
st.subheader("📝 Trade Log")
trade_log = risk_state.get("trade_log", []) or get_risk_state().get("trade_log", [])
if trade_log:
    import pandas as pd
    df = pd.DataFrame(trade_log)
    st.dataframe(df, use_container_width=True)
else:
    st.info("No trades yet today.")

# ── Brokerage Calculator ─────────────────────────
with st.expander("💸 Brokerage & Charges Calculator"):
    bc1, bc2 = st.columns(2)
    with bc1:
        calc_premium = st.number_input("Option Premium (₹)", value=200.0, step=10.0)
    with bc2:
        calc_qty = st.number_input("Quantity", value=25, step=1)
    charges = compute_charges_per_trade(calc_premium, calc_qty)
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Brokerage", f"₹{charges['brokerage']:.2f}")
    cc2.metric("STT", f"₹{charges['stt']:.2f}")
    cc3.metric("Total Charges", f"₹{charges['total']:.2f}")

# ── Time Filter Info ─────────────────────────────
with st.expander("⏰ Time Filter Rules"):
    st.markdown(f"""
    - **No Trade**: 9:15–9:20 AM (opening volatility)
    - **No Trade**: 12:00–1:00 PM (lunch hour)
    - **Auto Square Off**: {config.AUTO_SQUARE_OFF_TIME}
    - **Current Status**: {'🚫 No-Trade Window' if is_no_trade_window() else '✅ Trading Allowed'}
    - **Square Off Due**: {'⚠️ YES' if is_square_off_time() else 'No'}
    """)

# ── Auto Square Off Check ────────────────────────
if is_square_off_time() and risk_state.get("active_trade"):
    execute_exit("Auto square-off 3:15 PM")
    st.warning("⏰ Auto square-off executed at 3:15 PM")
    st.rerun()

# ── Auto Refresh ─────────────────────────────────
if st.session_state.auto_refresh:
    time.sleep(5)
    st.rerun()
