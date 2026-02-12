
# 🚀 Council Desktop Guardian — ULTIMATE README
## AI Council Governance + Quant Autopilot Trading + Telegram Approval + Desktop Automation

This document is the **complete master guide** for the entire bot.

It combines:
• Original Council‑Desktop‑Guardian features
• Quant hedge‑fund style autopilot trading
• Alpaca wallet integration
• Telegram approvals
• Dashboard
• Desktop automation
• macOS + Windows setup
• Docker deployment
• All environment variables
• Every feature documented

Nothing is left undocumented.

=====================================================================
🧠 WHAT THIS BOT IS
=====================================================================

This project is THREE SYSTEMS in one:

1️⃣ AI Council Governance (original)
   News → Plan → Council vote → Telegram approval → Execute

2️⃣ Quant Trading Autopilot (new)
   Market scan → Indicators → Backtest → Risk engine → Auto trade

3️⃣ Desktop Guardian
   Mouse/keyboard/shell automation on your computer

You can run:
• Council only
• Autopilot only
• Both together (recommended)

=====================================================================
🔥 FULL FEATURE LIST
=====================================================================

🧠 Council Engine
• Multi-agent voting
• Risk scoring
• Prompt injection protection
• Plan approval gating
• Telegram confirmations
• Daily summaries
• Redis RAG memory

📈 Quant Trading Engine
• Scheduled autopilot loop
• SMA / EMA / RSI / MACD / ATR indicators
• Historical backtesting
• Strategy scoring (0–1 confidence)
• Position sizing
• Stop-loss / take-profit bracket orders
• Paper trading
• Live trading
• Multi-asset ready (stocks, ETFs, crypto)

📡 Signals (optional)
• RSS/news
• Reddit sentiment
• Google Trends
• Fundamentals
• Congressional trades
• Macro indicators (FRED)

🛡 Risk Engine
• Max capital per trade
• ATR stops
• Reward:Risk targets
• Max trades per run

💻 Desktop Guardian
• Screenshots
• Mouse/keyboard control
• File read/write
• Shell commands
• MCP tool execution

📊 Dashboard
• Portfolio view
• Trades
• Logs
• Autopilot decisions
• History

💼 SaaS (optional scaffold)
• JWT auth
• Stripe billing
• Multi-user support

=====================================================================
🖥 SUPPORTED SYSTEMS
=====================================================================

macOS  ✅
Windows ✅
Linux  ✅
Docker  ✅

=====================================================================
⚡ COMPLETE INSTALLATION
=====================================================================

======================
STEP 1 — Install Python
======================

macOS:
    brew install python

Windows:
    https://python.org/downloads

Verify:
    python --version

======================
STEP 2 — Install project
======================

pip install -r requirements.txt

Windows alt:
    py -m pip install -r requirements.txt

======================
STEP 3 — Create Alpaca Wallet (REQUIRED FOR TRADING)
======================

1. https://alpaca.markets
2. Create account
3. Enable PAPER trading
4. Generate API keys

======================
STEP 4 — Setup Telegram Approval (RECOMMENDED)
======================

Create bot:
1. Telegram → @BotFather
2. /newbot
3. Copy BOT TOKEN

Get chat id:
Message your bot once then open:
https://api.telegram.org/bot<TOKEN>/getUpdates

Copy:
"chat":{"id":123456789}

======================
STEP 5 — Create .env
======================

Create file named `.env` in project root.

Paste:

TRADING_BROKER=alpaca
ALPACA_API_KEY=YOUR_KEY
ALPACA_API_SECRET=YOUR_SECRET
ALPACA_PAPER=1

TELEGRAM_BOT_TOKEN=YOUR_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID

AUTOPILOT_ENABLED=1
AUTOPILOT_CAN_EXECUTE=0
AUTOPILOT_INTERVAL_SECONDS=1800
AUTOPILOT_MIN_SCORE=0.7
AUTOPILOT_MAX_TRADES_PER_RUN=2

RISK_MAX_POSITION_PCT=0.10

(Optional signals)
NEWS_API_KEY=
FRED_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_SECRET=

======================
STEP 6 — Run Bot
======================

python -m app.main

Bot starts:
• Council
• Telegram
• Autopilot
• Scheduler
• Trading engine

======================
STEP 7 — Run Dashboard
======================

streamlit run app/dashboard/streamlit_app.py

Open:
http://localhost:8501

=====================================================================
⚙ EXECUTION MODES
=====================================================================

SAFE MONITOR ONLY:
AUTOPILOT_CAN_EXECUTE=0

PAPER TRADING:
ALPACA_PAPER=1
AUTOPILOT_CAN_EXECUTE=1

LIVE TRADING:
ALPACA_PAPER=0
AUTOPILOT_CAN_EXECUTE=1
⚠ real money

=====================================================================
🐳 DOCKER (optional)
=====================================================================

docker compose up --build

=====================================================================
🧠 HOW IT WORKS
=====================================================================

Autopilot:
scan → indicators → backtest → signals → score → risk → council → trade

Council:
review → approve/reject → telegram → execute

Desktop:
runs approved OS actions

=====================================================================
⚠ SAFETY CHECKLIST
=====================================================================

ALWAYS:
• Start paper trading
• Test Telegram first
• Use small positions
• Watch dashboard

NEVER:
• Turn on live immediately

=====================================================================
✅ SUMMARY
=====================================================================

You now have:

AI governance council
+ autonomous quant trading
+ telegram approvals
+ dashboard
+ desktop automation
+ cross-platform

Everything runs locally.

END
