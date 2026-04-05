"""
GBOT — Algorithmic Crypto Scalping Bot
Strategy: 4H Range Scalp with 5-min breakout re-entry
Exchange: Binance (via ccxt)
"""

import threading
import time
import logging
import smtplib
import schedule
from datetime import datetime
from email.mime.text import MIMEText

import pytz
import pandas as pd
import ccxt
from flask import Flask, jsonify, request, render_template

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("GBOT")

# ─────────────────────────────────────────────
# Flask App
# ─────────────────────────────────────────────
app = Flask(__name__)

# ─────────────────────────────────────────────
# Global State
# ─────────────────────────────────────────────
state = {
    "is_running": False,
    "logs": [],
    "open_orders": [],
    "closed_orders": [],
    "total_profit": 0.0,
    "wins": 0,
    "losses": 0,
    "profit_history": [],
}

settings = {
    "api_key": "",
    "api_secret": "",
    "risk_per_trade": 10.0,   # USD
    "smtp_email": "",
    "smtp_password": "",
}

# Per-pair strategy state
pair_state = {}

PAIRS = ["BTC/USDT", "SUI/USDT", "PAXG/USDT"]
NY_TZ = pytz.timezone("America/New_York")

state_lock = threading.Lock()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}]  {msg}"
    logger.info(entry)
    with state_lock:
        state["logs"].append(entry)
        if len(state["logs"]) > 500:
            state["logs"] = state["logs"][-500:]


def get_exchange():
    """Build a ccxt Binance instance with current credentials."""
    exchange = ccxt.binance({
        "apiKey": settings["api_key"],
        "secret": settings["api_secret"],
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    exchange.set_sandbox_mode(True)  # 🛑 Routes all trades to the Binance Testnet
    return exchange


def ohlcv_to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(NY_TZ)
    return df


def calc_position_size(entry: float, sl: float) -> float:
    """Calculate position size (units) based on risk_per_trade."""
    risk = settings["risk_per_trade"]
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return 0.0
    return round(risk / sl_distance, 6)


# ─────────────────────────────────────────────
# SMTP Daily Report
# ─────────────────────────────────────────────
def send_daily_report():
    if not settings["smtp_email"] or not settings["smtp_password"]:
        log("⚠ SMTP not configured — skipping daily report.")
        return
    try:
        with state_lock:
            profit = state["total_profit"]
            wins = state["wins"]
            losses = state["losses"]
            total = wins + losses
            win_rate = (wins / total * 100) if total > 0 else 0.0

        body = (
            f"GBOT Daily Performance Report\n"
            f"==============================\n"
            f"Total Profit : ${profit:.2f}\n"
            f"Win Rate     : {win_rate:.1f}%\n"
            f"Wins         : {wins}\n"
            f"Losses       : {losses}\n"
            f"Total Trades : {total}\n"
        )
        msg = MIMEText(body)
        msg["Subject"] = f"GBOT Report — {datetime.now(NY_TZ).strftime('%Y-%m-%d')}"
        msg["From"] = settings["smtp_email"]
        msg["To"] = settings["smtp_email"]

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings["smtp_email"], settings["smtp_password"])
            server.sendmail(settings["smtp_email"], settings["smtp_email"], msg.as_string())

        log("✉ Daily report sent successfully.")
    except Exception as e:
        log(f"✉ Failed to send daily report: {e}")


# ─────────────────────────────────────────────
# Strategy Core
# ─────────────────────────────────────────────
def get_4h_range(exchange, symbol: str):
    """Return (high, low) of the most recently CLOSED 4H candle (NY time)."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="4h", limit=3)
        df = ohlcv_to_df(ohlcv)
        # Second-to-last row = most recently closed candle
        closed = df.iloc[-2]
        return float(closed["high"]), float(closed["low"])
    except ccxt.NetworkError as e:
        log(f"⚠ Network error fetching 4H range for {symbol}: {e}")
    except ccxt.ExchangeError as e:
        log(f"⚠ Exchange error fetching 4H range for {symbol}: {e}")
    except Exception as e:
        log(f"⚠ Unexpected error fetching 4H range for {symbol}: {e}")
    return None, None


def get_latest_5m_candle(exchange, symbol: str):
    """Return the most recently CLOSED 5-min candle as a dict."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="5m", limit=3)
        df = ohlcv_to_df(ohlcv)
        closed = df.iloc[-2]
        return {
            "open": float(closed["open"]),
            "high": float(closed["high"]),
            "low": float(closed["low"]),
            "close": float(closed["close"]),
            "time": closed["timestamp"],
        }
    except ccxt.NetworkError as e:
        log(f"⚠ Network error fetching 5m candle for {symbol}: {e}")
    except ccxt.ExchangeError as e:
        log(f"⚠ Exchange error fetching 5m candle for {symbol}: {e}")
    except Exception as e:
        log(f"⚠ Unexpected error fetching 5m candle for {symbol}: {e}")
    return None


def init_pair_state(symbol: str):
    return {
        "range_high": None,
        "range_low": None,
        "range_last_updated": None,
        "breakout_direction": None,    # "up" | "down" | None
        "breakout_extreme": None,
        "in_breakout": False,
        "last_5m_time": None,
    }


def process_pair(exchange, symbol: str):
    """Run one tick of the strategy for a given pair."""
    ps = pair_state.setdefault(symbol, init_pair_state(symbol))

    # ── Step 1: Refresh 4H range every 4 hours (or on first run)
    now_ny = datetime.now(NY_TZ)
    should_refresh_range = (
        ps["range_high"] is None or
        ps["range_last_updated"] is None or
        (now_ny - ps["range_last_updated"]).total_seconds() >= 4 * 3600
    )
    if should_refresh_range:
        high, low = get_4h_range(exchange, symbol)
        if high is None:
            return
        ps["range_high"] = high
        ps["range_low"] = low
        ps["range_last_updated"] = now_ny
        # Reset breakout tracking on new range
        ps["breakout_direction"] = None
        ps["breakout_extreme"] = None
        ps["in_breakout"] = False
        log(f"📐 [{symbol}] 4H Range updated — High: {high:.4f}  Low: {low:.4f}")

    # ── Step 2/3: Fetch latest 5m candle
    candle = get_latest_5m_candle(exchange, symbol)
    if candle is None:
        return

    # Avoid reprocessing the same candle
    if candle["time"] == ps["last_5m_time"]:
        return
    ps["last_5m_time"] = candle["time"]

    close = candle["close"]
    high_wick = candle["high"]
    low_wick = candle["low"]
    rh = ps["range_high"]
    rl = ps["range_low"]

    if not ps["in_breakout"]:
        # ── Step 2: Detect breakout (close, not wick)
        if close > rh:
            ps["in_breakout"] = True
            ps["breakout_direction"] = "up"
            ps["breakout_extreme"] = high_wick
            log(f"🚀 [{symbol}] Breakout UP detected! Close: {close:.4f} > Range High: {rh:.4f}")
        elif close < rl:
            ps["in_breakout"] = True
            ps["breakout_direction"] = "down"
            ps["breakout_extreme"] = low_wick
            log(f"🔻 [{symbol}] Breakout DOWN detected! Close: {close:.4f} < Range Low: {rl:.4f}")
    else:
        # ── Track extreme during breakout
        if ps["breakout_direction"] == "up":
            if high_wick > ps["breakout_extreme"]:
                ps["breakout_extreme"] = high_wick
            # ── Step 3: Re-entry — close back below High → SHORT
            if close < rh:
                fire_signal(symbol, "SHORT", close, ps["breakout_extreme"], rh, rl)
                ps["in_breakout"] = False
                ps["breakout_direction"] = None
                ps["breakout_extreme"] = None
        elif ps["breakout_direction"] == "down":
            if low_wick < ps["breakout_extreme"]:
                ps["breakout_extreme"] = low_wick
            # ── Step 3: Re-entry — close back above Low → LONG
            if close > rl:
                fire_signal(symbol, "LONG", close, ps["breakout_extreme"], rh, rl)
                ps["in_breakout"] = False
                ps["breakout_direction"] = None
                ps["breakout_extreme"] = None


def fire_signal(symbol: str, side: str, entry: float, extreme: float, rh: float, rl: float):
    """Calculate SL/TP, build order object, and update state."""
    sl = extreme
    sl_dist = abs(entry - sl)
    tp_dist = 2 * sl_dist

    if side == "SHORT":
        tp = entry - tp_dist
    else:
        tp = entry + tp_dist

    qty = calc_position_size(entry, sl)

    order = {
        "time": datetime.now(NY_TZ).strftime("%Y-%m-%d %H:%M"),
        "pair": symbol,
        "side": side,
        "entry": round(entry, 4),
        "tp": round(tp, 4),
        "sl": round(sl, 4),
        "qty": qty,
        "status": "open",
        "pnl": 0.0,
    }

    with state_lock:
        state["open_orders"].append(order)

    log(
        f"{'🟢 LONG' if side == 'LONG' else '🔴 SHORT'} [{symbol}]  "
        f"Entry: {entry:.4f}  SL: {sl:.4f}  TP: {tp:.4f}  Qty: {qty}"
    )


# ─────────────────────────────────────────────
# Scanner Thread
# ─────────────────────────────────────────────
SCAN_INTERVAL = 30  # seconds between scans

def scanner_loop():
    log("🤖 GBOT scanner thread started.")
    exchange = None

    while True:
        try:
            if not state["is_running"]:
                time.sleep(2)
                continue

            # Build / rebuild exchange if keys changed
            try:
                exchange = get_exchange()
            except Exception as e:
                log(f"⚠ Could not initialise exchange: {e}")
                time.sleep(10)
                continue

            log(f"🔍 Scanning {len(PAIRS)} pairs …")
            for symbol in PAIRS:
                try:
                    process_pair(exchange, symbol)
                except Exception as e:
                    log(f"⚠ Error processing {symbol}: {e}")

            # Run scheduled jobs (daily report)
            schedule.run_pending()

            time.sleep(SCAN_INTERVAL)

        except Exception as e:
            log(f"💥 Scanner loop error: {e}")
            time.sleep(10)


# ─────────────────────────────────────────────
# Schedule daily report at 07:00 AM
# ─────────────────────────────────────────────
schedule.every().day.at("07:00").do(send_daily_report)


# ─────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with state_lock:
        total = state["wins"] + state["losses"]
        win_rate = round(state["wins"] / total * 100, 1) if total > 0 else 0.0
        return jsonify({
            "is_running": state["is_running"],
            "logs": state["logs"][-100:],
            "open_orders": state["open_orders"],
            "closed_orders": state["closed_orders"],
            "total_profit": round(state["total_profit"], 2),
            "wins": state["wins"],
            "losses": state["losses"],
            "win_rate": win_rate,
            "profit_history": state["profit_history"],
        })


@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    with state_lock:
        state["is_running"] = not state["is_running"]
        status = state["is_running"]
    log(f"{'▶ Bot STARTED' if status else '⏹ Bot STOPPED'} via dashboard.")
    return jsonify({"is_running": status})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json(silent=True) or {}
    if "api_key" in data:
        settings["api_key"] = data["api_key"]
    if "api_secret" in data:
        settings["api_secret"] = data["api_secret"]
    if "risk_per_trade" in data:
        try:
            settings["risk_per_trade"] = float(data["risk_per_trade"])
        except ValueError:
            pass
    if "smtp_email" in data:
        settings["smtp_email"] = data["smtp_email"]
    if "smtp_password" in data:
        settings["smtp_password"] = data["smtp_password"]
    log("⚙ Settings updated via dashboard.")
    return jsonify({"status": "ok", "risk_per_trade": settings["risk_per_trade"]})


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Start scanner as daemon thread
    t = threading.Thread(target=scanner_loop, daemon=True, name="GBOTScanner")
    t.start()
    log("🚀 GBOT initialised — dashboard at http://127.0.0.1:8080")
    app.run(debug=False, port=8080, use_reloader=False)
