# GBOT — Algorithmic Crypto Scalping Bot 🚀

Welcome to **GBOT**, a fully autonomous cryptocurrency scalping system equipped with an elegant, modern Glassmorphism web dashboard. Built for precision and speed, GBOT monitors key crypto pairs and executes trades based on a specialized 4H Range Breakout strategy.

> **Disclaimer**: This software is for **educational purposes only**. Live trading involves substantial risk of financial loss. Always backtest thoroughly before deploying real capital. The current default logic is hardcoded to route trades to the Binance Testnet for safety.

---

## ✨ Features

- **Autonomous Trading Engine**: Automatically monitors markets 24/7 scanning for optimal entry points based on the configured strategy.
- **Advanced 4H Range Scalp Strategy**: Trades the breakout patterns of 4-hour candles with a 5-minute precision re-entry layer.
- **Premium User Dashboard**: Beautiful Glassmorphism UI that gives you real-time insight into the bot’s status, profits, open orders, and live logs.
- **Risk Management System**: Dynamically sizes positions based on a configured USD risk amount per trade, keeping your capital safe from oversized losses.
- **Daily Performance Reports**: Ships automated EOD (End of Day) stats right to your inbox, detailing win rate, PnL, and total trades via SMTP.
- **Privacy-First Configuration**: No configuration keys or passwords are saved to disk. All secrets are stored directly in-memory, ensuring ultimate safety and limiting unauthorized access.

---

## 🏗️ Architecture

```text
GBOT/
├── gbot.py              # Backend Trading Engine + Flask API serving on Port 8080
├── requirements.txt     # Python dependencies
├── README.md            # This documentation file
└── templates/
    └── index.html       # The frontend Glassmorphism dashboard UI
```

---

## 📈 The Strategy: 4H Range Scalp

The core logic attempts to capture mean-reversion trades immediately following false breakouts on higher timeframes.

1. **Calculate Range**: Evaluates the High and Low of the most recently closed **4-hour candle** (in the NY timezone).
2. **Breakout Detection**: Constantly monitors the 5-minute chart. Waits for a **5-min candle** to *close* strictly outside of the 4H range boundaries.
3. **Re-entry Confirmation**: Once the price closes back *inside* the 4H range, the trap is set and the bot fires a trade signal:
   - If it broke *above* the High and returned → **Execute SHORT**
   - If it broke *below* the Low and returned → **Execute LONG**
4. **Risk Profile**: Stop Loss (SL) is strictly placed at the breakout's extreme wick. Take Profit (TP) targets a 1:2 Risk-to-Reward ratio.

### Supported Pairs
By default, the scanner handles:
- `BTC/USDT`
- `SUI/USDT`
- `PAXG/USDT`

*(You can easily modify the `PAIRS` constant in `gbot.py` to add more assets.)*

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.9+
- Binance Account (Testnet or Live)
- An active Internet connection to websocket/REST endpoints.

### 1. Clone the repository
```bash
git clone https://github.com/<your-username>/GBOT.git
cd GBOT
```

### 2. Install Dependencies
It's strongly recommended to use a virtual environment.
```bash
pip install -r requirements.txt
```

### 3. Run the Bot
```bash
python gbot.py
```
After executing, the Python script will instantly launch the Trading Scanner Thread in a background loop and the Flask application will become available on port `8080`.

Open your browser and navigate to the dashboard:
👉 **[http://127.0.0.1:8080](http://127.0.0.1:8080)**

---

## ⚙️ Configuration & Security

**GBOT stores no sensitive info in its source files.** Upon launching the server, you must configure your parameters directly via the web dashboard:

1. **Settings Panel**: Go to your web dashboard.
2. Enter your **Binance API Key** and **Secret Key**.
3. Set your **Risk Per Trade ($)** (e.g., $10).
4. *(Optional)* Setup **SMTP Email & Password** for daily trade summaries.
5. Click **Save Configuration**.
6. Press the **START** button in the header.

*Note: Because keys are injected safely into volatile memory, they will reset whenever the application stops or restarts, heavily increasing security.*

---

## 🌐 API Reference

GBOT provides several useful HTTP endpoints used by the frontend:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/`      | Returns the Glassmorphism Dashboard. |
| `GET`  | `/api/state` | Returns the current bot execution state, PnL, logs, and orders as JSON. |
| `POST` | `/api/toggle`| Signals the background execution thread to either Start or Stop scanning. |
| `POST` | `/api/settings` | Updates in-memory trading and mail configurations. |

---

## 📬 Automated Daily Reports
Set up the SMTP fields in the dashboard to receive daily updates. Every day at **07:00 AM (New York Time)**, GBOT will securely dispatch a report to your email, bringing you full visibility on:
- Cumulative Profit & Loss
- Live Win Percentage
- Daily Win/Loss metrics
