
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
- Install Homebrew
- `brew install python node git redis`
    brew install python

Windows:
- Install: Python 3.10+ , Node.js LTS, Git
- Install Redis (or run Redis in Docker)
    https://python.org/downloads

Verify:
    python --version

======================
STEP 2 — Install project
======================

```bash
git clone https://github.com/PrinceFroggy/Council-Desktop-Guardian-
cd Council-Desktop-Guardian-
```

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

Set these keys if you want Alpaca integration:
- `TRADING_BROKER=alpaca`
- `ALPACA_API_KEY=...`
- `ALPACA_API_SECRET=...`
- `ALPACA_PAPER=1` (paper) or `0` (live)
- `ALPACA_BASE_URL` optional

======================
STEP 4 — Setup Telegram Approval (RECOMMENDED)
======================

Create bot:
1. Telegram → @BotFather
2. /newbot
3. Copy BOT TOKEN

3. Copy the **bot token** into:
   - `TELEGRAM_BOT_TOKEN=...`
4. Get your **chat id**
   - Easiest: add the bot to a private group, send one message, then use a “getUpdates” helper (many guides online)
   - Put it into:
   - `TELEGRAM_CHAT_ID=...`

Get chat id:
Message your bot once then open:
https://api.telegram.org/bot<TOKEN>/getUpdates

Copy:
"chat":{"id":123456789}

======================
STEP 4.5 — Python venv
======================

```bash
python -m venv venv
```

**macOS**
```bash
source venv/bin/activate
```

**Windows (PowerShell)**
```powershell
venv\Scripts\Activate.ps1
```

======================
STEP 5 — Create .env
======================

Copy the template:
- macOS/Linux: `cp .env.example .env`
- Windows: `copy .env.example .env`

Open `.env` and fill what you need.

✅ Minimum for **paper + Telegram**:
- `REDIS_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- (optional) `TRADING_BROKER=alpaca` + Alpaca keys if you want real broker integration
- Keep `ALPACA_PAPER=1` while testing

======================
STEP 5.5 — Start Redis
======================

**macOS**
```bash
brew services start redis
```

**Windows**
Start your Redis service, OR run:
```bash
docker run -p 6379:6379 redis:latest
```

======================
STEP 6 — Run Bot
======================

python -m app.main

```bash
python -m app.main
```
If your repo has a top-level runner:
```bash
python main.py
```
or:
```bash
python run.py
```

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

## Autopilot (quant loop)

Autopilot has two modes:
- **Report-only** (safe): generates candidates + signals + proposals
- **Execute**: can place orders (only if enabled)

Set:
- `AUTOPILOT_ENABLED=1`
- `AUTOPILOT_CAN_EXECUTE=0`  ← start here
- `AUTOPILOT_INTERVAL_SECONDS=1800`

When you are confident:
- `AUTOPILOT_CAN_EXECUTE=1`

---

## Safety Switches (important)

These exist because the bot may fetch web pages or run higher-risk actions.

- `ENABLE_WEB_RESEARCH=0|1`
- `WEB_ALLOWLIST=domain1.com,domain2.com` (strongly recommended)
- `ENABLE_DANGEROUS_TOOLS=0|1`
- `ALLOW_ABSOLUTE_PATHS=0|1`

Leave them OFF until you understand what they do.

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
