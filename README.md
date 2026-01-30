# Council Desktop Guardian

Local-first **4-agent AI council** (Security, Ethics, Code, Arbiter) with **Christian ethics** + **prompt-injection defenses**,
RAG via **Redis Stack**, and **human approval via Telegram (free)** or optional Twilio.

## What it does

- Accepts a *request* + a *proposed execution plan*.
- Runs a **4-agent council review**:
  1) Security reviewer
  2) Christian ethics reviewer
  3) Code reviewer
  4) Arbiter (final verdict)
- If approved, it messages you with an **approval code**. Only when you reply **YES <code>** does it execute.
- Includes **daily RSS research + prayer/reflection** message (Telegram).

## Quickstart (Docker + Ollama + Telegram)

### 0) Install Ollama (local AI)
Install: https://ollama.com  
Pull models (examples):
- `ollama pull llama3.1:8b`
- `ollama pull qwen2.5-coder:7b`

### 1) Create a Telegram bot (free)
- Message **@BotFather**
- Create a bot and copy `TELEGRAM_BOT_TOKEN`
- Get your chat id:
  1) Start your bot and send it “hi”
  2) Open: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
  3) Find `"chat":{"id": ... }` → set `TELEGRAM_CHAT_ID`

### 2) Configure `.env`
Copy `.env.example` to `.env` and fill values.

### 3) Start
```bash
docker compose up --build
```

### 4) Index your repo (optional but recommended for RAG)
```bash
curl -X POST http://localhost:7070/index
```

### 5) Send a request
```bash
curl -X POST http://localhost:7070/plan   -H "Content-Type: application/json"   -d @example_request.json
```

### 6) Approve via Telegram
Reply to your bot:
- `YES ABCD1234` to execute
- `NO ABCD1234` to deny

## Desktop automation permissions

### macOS
System Settings → Privacy & Security → Accessibility → enable for Terminal/Python.  
Also enable Screen Recording if you want screenshots.

### Windows
PyAutoGUI usually works without extra steps, but automation can trigger AV warnings.

## Safety Notes

- This template **does not execute arbitrary shell commands**.
- Desktop actions are **allowlisted** in `app/desktop_actions.py`.
- You still get final human approval before execution.

## RAG modes included

This package supports the following retrieval modes (select per request via `rag_mode` in `/plan`):

- **naive**: Vector retrieval from Redis (good default).
- **advanced**: Query rewriting + lightweight LLM reranking for higher precision.
- **graphrag**: Vector retrieval + simple entity relationship neighborhood (co-occurrence graph in Redis).
- **agentic**: Multi-step retrieval (LLM proposes subqueries; system retrieves per step).
- **finetune**: Safe “style overlay” (stored rules/snippets) that influences council behavior without weight training.
- **cag**: Cache-Augmented Generation – repeats of the same prompt reuse cached council output for consistency/speed.

Example request with advanced mode:
```json
{
  "action_request": "Take a screenshot and type hello",
  "proposed_plan": {"type":"desktop","actions":[{"name":"screenshot"},{"name":"type_text","text":"hello"}]},
  "rag_mode": "advanced"
}
```

## Tray client (send prompts from desktop)

This repo includes a small **tray app** that lets you send prompts to the council without curl:

- `client_tray/tray.py` (macOS menu bar + Windows tray)
- Run:
  - macOS: `bash client_tray/run_tray_mac.sh`
  - Windows: `powershell -ExecutionPolicy Bypass -File client_tray/run_tray_win.ps1`

It posts to `http://localhost:7070/plan` and shows the `pending_id` + `approval_code`.

## Full setup: local desktop prompting + SMS prompting

### 1) Start the Guardian API + Redis

**Option A (Docker, easiest for Redis):**
```bash
docker compose up --build
```

**Option B (best for macOS desktop control):**
Run Guardian on your host so macOS Accessibility permissions apply cleanly:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Start Redis Stack separately (docker is fine), then:
uvicorn app.main:app --host 0.0.0.0 --port 7070
```

### 2) Index your repo (RAG)
```bash
curl -X POST http://localhost:7070/index
```

### 3) Local desktop prompting (tray app)
- macOS: `bash client_tray/run_tray_mac.sh`
- Windows: `powershell -ExecutionPolicy Bypass -File client_tray/run_tray_win.ps1`

This sends your prompt to `/plan` and shows the `pending_id` + `approval_code`.  
The council runs, then you must approve before any execution.

### 4) Text-message prompting (SMS via Twilio) — optional
For real SMS prompting, you need an SMS provider. This package supports **Twilio** inbound + outbound.

**A) Configure .env**
Set:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM` (your Twilio number, e.g. +1...)
- `APPROVER_PHONE` (your personal phone number; only this number is accepted)

**B) Expose your local server to Twilio**
Twilio must reach your webhook, so you need a public URL that forwards to `localhost:7070`.  
Use a tunnel like **ngrok** or **cloudflared**.

**C) Twilio Console webhook**
In Twilio Console → Phone Numbers → Messaging, set:
- Webhook URL: `https://<your-public-url>/inbound/twilio`
- Method: POST

### 5) SMS command format
Text your Twilio number:

```
PLAN ADVANCED :: Take a screenshot and type hello | SHOT | TYPE: hello
```

Supported allowlisted actions:
- `SHOT`
- `TYPE: <text>`
- `HOTKEY: ctrl+shift+p`
- `CLICK: x,y`

### 6) Approval gate (SMS)
If the council approves, you’ll get a reply asking:
- `YES <approval_code>` → execute
- `NO <approval_code>` → deny

Nothing executes before your YES.

## MCP (Model Context Protocol) integration

This package lets you add MCP tool servers to the council, so plans can include `mcp_call` actions.

### 1) Add your MCP server config
Copy:
```bash
cp app/mcp_servers.example.json app/mcp_servers.json
```

Edit `app/mcp_servers.json`:
- Add one or more servers (stdio transport)
- Add tool names to `allowlisted_tools` (keep this tight)

### 2) Restart Guardian
Restart `docker compose up --build` or your `uvicorn` process.

### 3) List tools (optional)
```bash
curl http://localhost:7070/mcp/tools
```

### 4) Use MCP tool in a plan
Example `proposed_plan`:
```json
{
  "type": "desktop",
  "actions": [
    {"name":"mcp_call", "server":"example_stdio", "tool":"filesystem.read_file", "args":{"path":"README.md"}},
    {"name":"screenshot", "path":"after.png"}
  ]
}
```

Even for MCP tools: council must approve AND you must reply YES before anything runs.


### MCP tool audit snapshot

You can snapshot MCP tools into Redis (for audit + tray UI):

```bash
curl -X POST http://localhost:7070/mcp/sync
```

Then view:
```bash
curl http://localhost:7070/mcp/tools
```

### MCP policy checks

MCP calls are validated by `app/mcp_policy.py` before execution. By default it:
- blocks shell-like tokens in args
- blocks `..` path traversal
- blocks absolute paths (unless you change the policy)
- blocks tools with risky names like *delete/exec/shell/network/upload* (generic safety)

## Dangerous tools (opt-in)

You asked for more power (shell + broader filesystem + web research). This package includes **opt-in** tools,
but it still **does not support stealth/background control**.

### Why no “stealth background control”
Stealth control is the same building block used for spyware/malware. This project is designed to be auditable and consent-based.

### Enable dangerous tools
Set env vars (in `.env` or your shell):

- `ENABLE_DANGEROUS_TOOLS=1`  
  Enables `shell_exec`, `fs_read`, `fs_write` actions.
- `ALLOW_ABSOLUTE_PATHS=1` *(optional)*  
  Allows absolute paths for filesystem actions. Not recommended.

Even when enabled:
- Council must approve
- You must reply YES with approval code
- Shell commands are still screened for obviously destructive/exfil patterns

### Enable web research (fetch URLs)
Set:
- `ENABLE_WEB_RESEARCH=1`
- `WEB_ALLOWLIST=example.com,arstechnica.com,hnrss.org`  (comma-separated domains)

Then you can use `web_fetch` actions to retrieve a page (content is capped).

## Dry run mode (preview without execution)

You can request a **dry run** to preview exactly what would happen without executing any actions.

### HTTP example
Send `dry_run: true`:

```bash
curl -X POST http://localhost:7070/plan \
  -H "Content-Type: application/json" \
  -d '{
    "action_request": "Take a screenshot and type hello",
    "proposed_plan": {"type":"desktop","actions":[{"name":"screenshot","path":"shot.png"},{"name":"type_text","text":"hello"}]},
    "rag_mode":"advanced",
    "dry_run": true
  }'
```

Response includes `execution_preview`. Status will be `DRY_RUN`. No approval code is needed because nothing executes.

### Tray app
The tray app now has a checkbox: **Dry run (preview only, no execution)**.

To actually execute, resend the same request with `dry_run: false`.




## News → Signals → (Paper) Investing Proposals (NEW)

This package adds an automated RSS news poller that:

- Polls `app/news_sources.txt` every `NEWS_POLL_INTERVAL_SECONDS`
- Indexes each new article into the Redis Vector RAG as `doc:news:<id>` so it can be referenced in later prompts
- Generates a cautious *paper-trade-only* proposal and sends a Telegram message with a **dry run preview**
- Keeps execution gated: paper trades only execute after the normal approval flow, and `paper_trade` actions can require a manual quote confirmation

### Environment variables

- `NEWS_POLL_INTERVAL_SECONDS` (default: `900`)
- `NEWS_MAX_ITEMS_PER_POLL` (default: `25`)
- `NEWS_ENABLE_MARKET_HOURS_ONLY` (default: `0`)
- `NEWS_WATCHLIST` (optional comma-separated tickers, e.g. `AAPL,TSLA,NVDA`)
- `NEWS_SOURCES_FILE` (default: `app/news_sources.txt`)
- `PAPER_START_CASH` (default: `100000`)

### Editing the feeds

Edit `app/news_sources.txt` (one RSS URL per line). Restart the API container/service for changes to apply.

### Enabling execution of paper trades

The poller creates proposals in **dry run** mode by default. To actually execute a trade you must:

1) Create a plan with `dry_run=false` and a `paper_trade` action that includes a real price, and
2) If `requires_quote=true`, set `price_confirmed=true` before approving (prevents placeholder execution).



## Live trading (optional) via Alpaca

This repo now supports a **real broker order action** (still behind the existing approval gate).

### Configure Alpaca
Set these in your `.env`:

- `TRADING_BROKER=alpaca`
- `ALPACA_API_KEY=...`
- `ALPACA_API_SECRET=...`
- `ALPACA_PAPER=1` for paper trading, or `ALPACA_PAPER=0` for live trading
- Optional: `ALPACA_BASE_URL=` (leave blank to use Alpaca defaults)

### Action: `alpaca_order`
Example (paper, dry run):

```json
{
  "action_request": "Buy 1 share of AAPL (paper)",
  "proposed_plan": {
    "type": "trading",
    "actions": [
      {
        "name": "alpaca_order",
        "broker_mode": "paper",
        "symbol": "AAPL",
        "side": "buy",
        "qty": 1,
        "order_type": "market",
        "time_in_force": "day"
      }
    ]
  },
  "dry_run": true
}
```

### Safety rails
- Orders **only execute** when the plan is approved (same `YES <code>` flow).
- Live orders additionally require: `broker_mode="live"` **and** `confirm_live_trade=true`.
- The code rejects mode mismatches (`ALPACA_PAPER` vs `broker_mode`).



### News trading proposals (paper + live)

- Set `TRADING_BROKER=alpaca` to include Alpaca order proposals.
- Set `NEWS_PROPOSE_LIVE=1` to include an additional **LIVE** Alpaca order proposal in each signal.
  - Live proposals **never auto-confirm**; execution requires your usual YES approval **and** `confirm_live_trade=true`.
