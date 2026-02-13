import os
import json
import time
import uuid
from fastapi import FastAPI, Request
from pydantic import BaseModel
from dotenv import load_dotenv

from .config import settings
from .redis_store import get_redis, ensure_vector_index
from .rag import RAG
from .repo_indexer import index_repo
from .rag_modes import get_context
from .cache import cag_set
from .llm_providers import load_providers
from .council import Council
from .notify import telegram_send
from .desktop_actions import execute_action
from .scheduler import start_scheduler
from .mcp_client import MCPRegistry, MCPError
from .mcp_policy import validate_mcp_call, MCPPolicyError
from .dangerous_tools import run_shell, fs_read, fs_write, DangerousToolError
from .web_fetch import fetch_url, WebFetchError
from .sms_commands import parse_sms_to_plan
from .twilio_notify import twilio_send_sms

# Optional SaaS mode
from .saas.db import init_db, get_user_by_email, create_user
from .saas.auth import hash_password, verify_password, create_jwt, decode_jwt
from .saas.stripe_webhook import handle_stripe_webhook

load_dotenv()

app = FastAPI()

r = get_redis(settings.REDIS_URL)
# ------------------------------------------------------------------
# Outbound priority gating (Tray app wins)
# When tray sends a prompt, temporarily suppress outbound Telegram
# notifications from background schedulers so the tray message is
# delivered "instantly" and doesn't get buried.
# ------------------------------------------------------------------
OUTBOUND_PAUSE_KEY = "outbound_pause_until"
OUTBOUND_TRAY_PAUSE_SECONDS = int(os.getenv("OUTBOUND_TRAY_PAUSE_SECONDS", "12"))

def _outbound_pause_active() -> bool:
    try:
        raw = r.get(OUTBOUND_PAUSE_KEY.encode())
        if not raw:
            return False
        until = float(raw.decode())
        return time.time() < until
    except Exception:
        return False

def _outbound_pause_set() -> None:
    try:
        until = time.time() + float(OUTBOUND_TRAY_PAUSE_SECONDS)
        # store until timestamp; TTL slightly longer as safety
        r.set(OUTBOUND_PAUSE_KEY.encode(), str(until).encode(), ex=max(OUTBOUND_TRAY_PAUSE_SECONDS + 5, 10))
    except Exception:
        pass
providers = load_providers()
rag = RAG(r)
ensure_vector_index(r, rag.dim)
council = Council(providers)

# MCP registry (optional)
_mcp = MCPRegistry(config_path=os.path.join(os.path.dirname(__file__), "mcp_servers.json"))
try:
    _mcp.load()
except Exception:
    pass

# Start daily research + reflection (Telegram)
# NOTE: Don't swallow startup errors silently—if the scheduler fails to start,
# it can look like "news is paused" even though the server is running.
try:
    start_scheduler(rag, r, providers, council)
    print("[scheduler] started")
except Exception as ex:
    print(f"[scheduler] FAILED to start: {ex}")
    try:
        telegram_send(f"[scheduler] FAILED to start: {ex}")
    except Exception:
        pass

# init SaaS DB (safe no-op if SAAS_ENABLED=0)
try:
    if getattr(settings, "SAAS_ENABLED", 0):
        init_db()
except Exception:
    pass


class _AuthRequest(BaseModel):
    email: str
    password: str


class PlanRequest(BaseModel):
    action_request: str
    proposed_plan: dict
    rag_mode: str = "naive"  # naive|advanced|graphrag|agentic|finetune|cag
    dry_run: bool = False
    # {"type":"desktop","actions":[...]} etc.


# ------------------------------------------------------------------
# Tray fast-path
#
# The tray UI is explicitly user-operated on the same machine.
# Waiting for multi-pass Council review can make the UI feel "stuck".
#
# When enabled, and ONLY when the tray proposes a *safe* desktop plan
# (no shell/fs/web fetch), we skip Council and immediately return a
# WAITING_HUMAN pending item with a Telegram/SMS approval code.
#
# This makes the tray feel instant while keeping execution gated.
# ------------------------------------------------------------------
TRAY_FASTPATH_ENABLED = os.getenv("TRAY_FASTPATH_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

# Keep this conservative. Add more only if you are comfortable.
TRAY_SAFE_ACTIONS = {"screenshot", "move_mouse", "click", "type_text", "hotkey"}


def _is_tray_safe_plan(plan: dict) -> bool:
    if not isinstance(plan, dict):
        return False
    if (plan.get("type") or "desktop") != "desktop":
        return False
    actions = plan.get("actions") or []
    if not isinstance(actions, list):
        return False
    for act in actions:
        if not isinstance(act, dict):
            return False
        name = act.get("name")
        if name not in TRAY_SAFE_ACTIONS:
            return False
    return True


def _preview_actions(plan: dict) -> list[str]:
    actions = (plan or {}).get("actions", []) or []
    out = []
    for i, act in enumerate(actions):
        name = act.get("name")
        if name == "type_text":
            txt = (act.get("text") or "")
            out.append(f"{i+1}. type_text: {txt[:60]}{'...' if len(txt) > 60 else ''}")
        elif name == "hotkey":
            out.append(f"{i+1}. hotkey: {act.get('keys')}")
        elif name == "click":
            out.append(
                f"{i+1}. click: x={act.get('x')} y={act.get('y')} button={act.get('button','left')}"
            )
        elif name == "move_mouse":
            out.append(
                f"{i+1}. move_mouse: x={act.get('x')} y={act.get('y')} duration={act.get('duration',0.2)}"
            )
        elif name == "screenshot":
            out.append(f"{i+1}. screenshot: path={act.get('path','screenshot.png')}")
        elif name == "mcp_call":
            out.append(
                f"{i+1}. mcp_call: {act.get('server')}:{act.get('tool')} args={act.get('args')}"
            )
        elif name == "shell_exec":
            out.append(f"{i+1}. shell_exec: {act.get('cmd')}")
        elif name == "fs_read":
            out.append(f"{i+1}. fs_read: path={act.get('path')}")
        elif name == "fs_write":
            out.append(
                f"{i+1}. fs_write: path={act.get('path')} bytes≈{len((act.get('content') or '').encode('utf-8'))}"
            )
        elif name == "web_fetch":
            out.append(f"{i+1}. web_fetch: url={act.get('url')}")
        else:
            out.append(f"{i+1}. {name}: {act}")
    return out


def _approval_code(n=8) -> str:
    import random, string

    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))


@app.post("/index")
def index():
    index_repo(settings.REPO_PATH, rag, redis_client=r)
    return {"ok": True}


@app.post("/plan")
def plan(req: PlanRequest, request: Request):
    caller = "unknown"
    try:
        caller = request.headers.get("X-Caller", "unknown")
    except Exception:
        pass

    caller_l = (caller or "unknown").lower()
    tray_callers = ("tray", "tray_app", "council_tray", "trayapp")

    # Suppress background outbound messages briefly when tray is active.
    suppress_telegram = _outbound_pause_active() and (caller_l not in tray_callers)

    # ------------------------------------------------------------------
    # Tray fast-path: return immediately for safe desktop plans.
    # ------------------------------------------------------------------
    if caller_l in tray_callers and TRAY_FASTPATH_ENABLED:
        if _is_tray_safe_plan(req.proposed_plan):
            pending_id = f"pending:{int(time.time())}:{uuid.uuid4().hex[:6]}"
            code = _approval_code()
            verdict = {
                "final": {
                    "verdict": "YES",
                    "reasons": [
                        "tray fast-path: safe desktop plan (no shell/fs/web fetch)",
                        "execution remains gated behind human approval",
                    ],
                    "message_to_human": "Fast-path used: Council review skipped to keep the tray snappy. Review the planned actions below and approve only if it looks right.",
                },
                "reviews": [],
            }

            blob = {
                "pending_id": pending_id,
                "approval_code": code,
                "created_at": time.time(),
                "status": "DRY_RUN" if bool(req.dry_run) else "WAITING_HUMAN",
                "rag": {"mode": "tray_fastpath", "chunks": []},
                "verdict": verdict,
                "proposed_plan": req.proposed_plan,
                "dry_run": bool(req.dry_run),
                "execution_preview": _preview_actions(req.proposed_plan),
                "action_request": req.action_request,
            }
            r.set(pending_id.encode(), json.dumps(blob).encode())

            # Tray gets outbound priority
            _outbound_pause_set()

            preview = "\n".join(blob.get("execution_preview") or []) or "(no actions)"
            msg = verdict["final"].get("message_to_human") or ""

            if not suppress_telegram:
                if blob["status"] == "WAITING_HUMAN":
                    telegram_send(
                        f"[{caller}] Pending approval (tray fast-path).\n"
                        f"Approval code: {code}\n"
                        f"Pending: {pending_id}\n\n"
                        f"{msg}\n\n"
                        f"Planned actions:\n{preview}\n\n"
                        f"Reply: YES {code} or NO {code}"
                    )
                else:
                    telegram_send(
                        f"[{caller}] Dry run preview (tray fast-path).\n"
                        f"Pending: {pending_id}\n\n"
                        f"{msg}\n\n"
                        f"Planned actions:\n{preview}"
                    )

            return {
                "pending_id": pending_id,
                "status": blob["status"],
                "approval_code": code,
                "verdict": verdict,
                "execution_preview": blob.get("execution_preview"),
            }

    # ------------------------------------------------------------------
    # Normal Council review path
    # ------------------------------------------------------------------
    pending_id = f"pending:{int(time.time())}:{uuid.uuid4().hex[:6]}"
    code = _approval_code()

    # Pick provider/model plan (simple default: Ollama for all passes)
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    provider_plan = [("ollama", model), ("ollama", model), ("ollama", model), ("ollama", model)]

    # Build RAG context
    llm_provider = providers.get("ollama")
    ctx = get_context(rag, r, llm_provider, model, req.action_request, req.rag_mode)

    def _extract_chunks(c: dict) -> list:
        if not isinstance(c, dict):
            return []
        if "chunks" in c and isinstance(c.get("chunks"), list):
            return c.get("chunks") or []
        # agentic mode bundles
        if "bundles" in c and isinstance(c.get("bundles"), list):
            out = []
            for b in c.get("bundles") or []:
                out.extend((b or {}).get("chunks") or [])
            return out
        # graphrag mode: chunks + graph
        if "graph" in c and isinstance(c.get("chunks"), list):
            return c.get("chunks") or []
        # finetune style overlay: no chunks
        if c.get("mode") == "finetune":
            return []
        # cag mode: context lives at ["context"]
        if c.get("mode") == "cag":
            inner = c.get("context") or {}
            if isinstance(inner, dict):
                return _extract_chunks(inner)
        return []

    rag_chunks = _extract_chunks(ctx)

    # CAG cache hit: reuse stored verdict object
    verdict = None
    if isinstance(ctx, dict) and ctx.get("mode") == "cag" and ctx.get("cache_hit") and ctx.get("cached"):
        verdict = ctx.get("cached")

    if verdict is None:
        verdict = council.review(
            action_request=req.action_request,
            rag_context=rag_chunks,
            proposed_plan=req.proposed_plan,
            provider_plan=provider_plan,
        )
        # store to CAG cache if enabled
        if isinstance(ctx, dict) and ctx.get("mode") == "cag":
            try:
                cag_set(r, prompt=req.action_request, rag_mode="cag", response_obj=verdict)
            except Exception:
                pass

    final = (verdict or {}).get("final") or {}
    final_verdict = str(final.get("verdict", "NO")).strip().upper()

    status = "REJECTED_BY_COUNCIL"
    if final_verdict == "YES":
        status = "DRY_RUN" if bool(req.dry_run) else "WAITING_HUMAN"

    blob = {
        "pending_id": pending_id,
        "approval_code": code,
        "created_at": time.time(),
        "status": status,
        "rag": ctx,
        "verdict": verdict,
        "proposed_plan": req.proposed_plan,
        "dry_run": bool(req.dry_run),
        "execution_preview": _preview_actions(req.proposed_plan),
        "action_request": req.action_request,
    }
    r.set(pending_id.encode(), json.dumps(blob).encode())

    # Telegram notification for review results
    if status == "WAITING_HUMAN":
        msg = final.get("message_to_human") or json.dumps(final, ensure_ascii=False)

        # Always attach a trimmed copy of original news snippets + derived trade line for news callers.
        news_context = ""
        trade_line = ""
        try:
            if caller_l in ("news_prayer_loop", "scheduler", "news"):
                ar = (req.action_request or "").strip()
                if ar:
                    news_context = "\n\n--- News context ---\n" + ar[-2500:]

                pp = req.proposed_plan or {}
                if (pp.get("type") == "trading") and (pp.get("actions") or []):
                    a0 = (pp.get("actions") or [])[0] or {}
                    sym = a0.get("symbol") or a0.get("ticker") or "?"
                    side = (a0.get("side") or "").upper() or "BUY/SELL"
                    qty = a0.get("qty", "?")
                    mode = a0.get("broker_mode") or a0.get("name") or "paper"
                    trade_line = f"\n\nProposed trade: {side} {qty} {sym} ({mode})"
                else:
                    trade_line = "\n\nProposed trade: PASS (no order)"
        except Exception:
            pass

        if not suppress_telegram:
            text_to_send = (
                f"[{caller}] Council approved (pending human).\n"
                f"Approval code: {code}\n"
                f"Pending: {pending_id}\n"
                f"{trade_line}\n\n"
                f"{msg}"
                f"{news_context}\n\n"
                f"Reply: YES {code} or NO {code}"
            )
            telegram_send(text_to_send)

    elif status == "DRY_RUN":
        preview = "\n".join(blob.get("execution_preview") or []) or "(no actions)"
        msg = final.get("message_to_human") or ""
        if not suppress_telegram:
            telegram_send(
                f"[{caller}] Dry run preview (no execution).\n"
                f"Pending: {pending_id}\n\n"
                f"{msg}\n\n"
                f"Planned actions:\n{preview}"
            )

    elif status == "REJECTED_BY_COUNCIL":
        reasons = final.get("reasons") or []
        required = final.get("required_changes") or []
        msg = final.get("message_to_human") or ""

        reasons_txt = "\n".join([f"- {r}" for r in reasons]) or "(no reasons)"
        required_txt = "\n".join([f"- {r}" for r in required]) or "(none)"

        if not suppress_telegram:
            telegram_send(
                f"[{caller}] Council REJECTED the request.\n"
                f"Pending: {pending_id}\n"
                f"Approval code: {code}\n\n"
                f"Reasons:\n{reasons_txt}\n\n"
                f"Required changes:\n{required_txt}\n\n"
                f"{msg}"
            )

    return {
        "pending_id": pending_id,
        "status": blob["status"],
        "approval_code": code,
        "verdict": verdict,
        "execution_preview": blob.get("execution_preview"),
    }
@app.get("/status/{pending_id}")
def status(pending_id: str):
    data = r.get(pending_id.encode())
    if not data:
        return {"error": "not found"}
    return json.loads(data.decode())


@app.get("/status/scheduler")
def scheduler_status():
    """Lightweight heartbeat/status for background threads."""
    def _get(key: str):
        try:
            v = r.get(key.encode())
            return v.decode() if v else None
        except Exception:
            return None

    return {
        "news": {
            "last_poll": _get("scheduler:news:last_poll"),
            "last_item": _get("scheduler:news:last_item"),
            "last_submit": _get("scheduler:news:last_submit"),
            "last_error": _get("scheduler:news:last_error"),
        },
        "daily": {
            "last_run": _get("scheduler:daily:last_run"),
            "last_error": _get("scheduler:daily:last_error"),
        },
        "autopilot": {
            "last_run": _get("scheduler:autopilot:last_run"),
            "last_error": _get("scheduler:autopilot:last_error"),
        },
    }

def _unwrap_plan(blob: dict) -> dict:
    plan = blob.get("proposed_plan") or {}

    # If /plan stored a wrapper that contains "proposed_plan": {...}
    inner = plan.get("proposed_plan")
    if isinstance(inner, dict) and ("actions" in inner or "type" in inner):
        return inner

    # Otherwise it's already flat
    return plan

@app.post("/execute/{pending_id}")
def execute(pending_id: str):
    data = r.get(pending_id.encode())
    if not data:
        return {"error": "not found"}

    blob = json.loads(data.decode())
    if blob["status"] == "DRY_RUN":
        return {"error": "dry run only; resend with dry_run=false to execute"}
    if blob["status"] != "APPROVED":
        return {"error": f"not approved (status={blob['status']})"}

    plan = _unwrap_plan(blob)
    plan_type = plan.get("type") or "desktop"
    if plan_type not in ("desktop", "trading", "notify_only"):
        blob["status"] = "DENIED"
        r.set(pending_id.encode(), json.dumps(blob).encode())
        return {"error": f"Unsupported plan type: {plan_type}"}

    # "notify_only" plans are informational (no actions). Mark executed.
    if plan_type == "notify_only":
        blob["status"] = "EXECUTED"
        r.set(pending_id.encode(), json.dumps(blob).encode())
        return {"ok": True, "results": [], "note": "notify_only: no actions"}

    results = []
    for act in plan.get("actions", []):
        results.append(execute_action(act))

        if act.get("name") == "mcp_call":
            server = act.get("server")
            tool = act.get("tool")
            args = act.get("args") or {}
            try:
                validate_mcp_call(settings.REPO_PATH, server, tool, args)
                res = _mcp.call_tool(server, tool, args)
                results.append(f"mcp_call {server}:{tool} OK")
                blob.setdefault("mcp_results", []).append(
                    {"server": server, "tool": tool, "result": res}
                )
            except MCPPolicyError as pe:
                raise RuntimeError(f"Rejected by MCP policy: {pe}")
            except Exception as e:
                raise
            continue

        if act.get("name") == "shell_exec":
            cmd = act.get("cmd") or ""
            res = run_shell(
                settings.REPO_PATH, cmd, timeout_seconds=int(act.get("timeout_seconds", 60))
            )
            results.append(f"shell_exec rc={res['returncode']}")
            blob.setdefault("shell_results", []).append({"cmd": cmd, "result": res})
            continue

        if act.get("name") == "fs_read":
            path = act.get("path") or ""
            res = fs_read(settings.REPO_PATH, path)
            results.append("fs_read OK")
            blob.setdefault("fs_reads", []).append(res)
            continue

        if act.get("name") == "fs_write":
            path = act.get("path") or ""
            content = act.get("content") or ""
            res = fs_write(settings.REPO_PATH, path, content)
            results.append("fs_write OK")
            blob.setdefault("fs_writes", []).append(res)
            continue

        if act.get("name") == "web_fetch":
            url = act.get("url") or ""
            res = fetch_url(url)
            results.append("web_fetch OK")
            blob.setdefault("web_fetches", []).append(
                {
                    "url": url,
                    "status": res.get("status"),
                    "truncated": res.get("truncated"),
                }
            )
            # store content separately to avoid bloating telegram
            blob.setdefault("web_pages", []).append(res)
            continue

        if act.get("name") == "paper_trade":
            from .trading import apply_paper_trade

            ticker = act.get("ticker") or ""
            side = act.get("side") or ""
            qty = act.get("qty") or 0
            price = act.get("price") or 0
            if act.get("requires_quote") and not act.get("price_confirmed"):
                results.append(
                    "paper_trade DENIED: requires_quote=true. Re-plan with a real quote price and price_confirmed=true."
                )
                blob.setdefault("trade_errors", []).append({"ticker": ticker, "error": "requires_quote"})
                continue
            res = apply_paper_trade(
                r,
                ticker=ticker,
                side=side,
                qty=qty,
                price=price,
                start_cash=settings.PAPER_START_CASH,
            )
            results.append("paper_trade OK" if res.get("ok") else f"paper_trade ERROR: {res.get('error')}")
            blob.setdefault("paper_trades", []).append(res)
            continue

        if act.get("name") == "alpaca_order":
            # Real order via Alpaca Trading API (still behind your approval gate)
            if settings.TRADING_BROKER.lower() != "alpaca":
                results.append("alpaca_order DENIED: TRADING_BROKER is not alpaca")
                blob.setdefault("trade_errors", []).append({"broker": "alpaca", "error": "broker_disabled"})
                continue
            # Prevent accidental live trades: require explicit confirmation flags
            broker_mode = (act.get("broker_mode") or ("paper" if settings.ALPACA_PAPER else "live")).lower()
            if broker_mode not in ("paper", "live"):
                results.append("alpaca_order DENIED: broker_mode must be paper|live")
                blob.setdefault("trade_errors", []).append({"broker": "alpaca", "error": "bad_broker_mode"})
                continue
            if broker_mode == "live":
                if not act.get("confirm_live_trade"):
                    results.append("alpaca_order DENIED: missing confirm_live_trade=true")
                    blob.setdefault("trade_errors", []).append({"broker": "alpaca", "error": "live_not_confirmed"})
                    continue
                # Also ensure env is configured for live or explicitly overridden
                if settings.ALPACA_PAPER:
                    results.append("alpaca_order DENIED: ALPACA_PAPER=1 but broker_mode=live")
                    blob.setdefault("trade_errors", []).append({"broker": "alpaca", "error": "mode_mismatch"})
                    continue
            if broker_mode == "paper" and not settings.ALPACA_PAPER:
                results.append("alpaca_order DENIED: ALPACA_PAPER=0 but broker_mode=paper")
                blob.setdefault("trade_errors", []).append({"broker": "alpaca", "error": "mode_mismatch"})
                continue

            from .brokers.alpaca import place_order, AlpacaError

            try:
                order = place_order(
                    api_key=settings.ALPACA_API_KEY,
                    api_secret=settings.ALPACA_API_SECRET,
                    paper=bool(settings.ALPACA_PAPER),
                    base_url=(settings.ALPACA_BASE_URL or None),
                    symbol=act.get("symbol") or act.get("ticker") or "",
                    side=(act.get("side") or "").lower(),
                    qty=act.get("qty"),
                    notional=act.get("notional"),
                    order_type=act.get("order_type") or act.get("type") or "market",
                    time_in_force=act.get("time_in_force") or "day",
                    limit_price=act.get("limit_price"),
                    stop_price=act.get("stop_price"),
                    extended_hours=bool(act.get("extended_hours", False)),
                    client_order_id=act.get("client_order_id"),
                    order_class=act.get("order_class"),
                    take_profit_limit_price=act.get("take_profit_limit_price")
                    or (act.get("take_profit") or {}).get("limit_price"),
                    stop_loss_stop_price=act.get("stop_loss_stop_price")
                    or (act.get("stop_loss") or {}).get("stop_price"),
                    stop_loss_limit_price=act.get("stop_loss_limit_price")
                    or (act.get("stop_loss") or {}).get("limit_price"),
                )
                results.append(
                    f"alpaca_order OK id={order.get('id', '')} status={order.get('status', '')}"
                )
                blob.setdefault("alpaca_orders", []).append(order)
            except AlpacaError as e:
                results.append(f"alpaca_order ERROR: {str(e)[:200]}")
                blob.setdefault("trade_errors", []).append({"broker": "alpaca", "error": str(e)})
            continue

        results.append(execute_action(act))

    blob["status"] = "EXECUTED"
    blob["execution_results"] = results
    r.set(pending_id.encode(), json.dumps(blob).encode())
    telegram_send(f"Executed plan for {pending_id}:\n" + "\n".join(results))
    return {"ok": True, "results": results}


@app.post("/inbound/twilio")
async def inbound_twilio(request: Request):
    # Twilio sends form-encoded fields: Body, From, etc.
    form = await request.form()
    body = (form.get("Body") or "").strip()
    from_number = (form.get("From") or "").strip()

    # If APPROVER_PHONE is set, only accept requests from that number.
    if settings.APPROVER_PHONE and from_number and from_number != settings.APPROVER_PHONE:
        return {"ok": True}

    upper = body.upper().strip()
    parts = upper.split()

    # A) Approval replies: YES CODE / NO CODE
    if len(parts) >= 2 and parts[0] in {"YES", "NO"}:
        decision, code = parts[0], parts[1]
        for k in r.scan_iter(match=b"pending:*", count=500):
            blob = json.loads(r.get(k).decode())
            if blob.get("approval_code", "").upper() != code:
                continue
            if blob["status"] != "WAITING_HUMAN":
                break
            if decision == "YES":
                blob["status"] = "APPROVED"
                r.set(k, json.dumps(blob).encode())
                twilio_send_sms(f"Approved. Executing {blob['pending_id']}", from_number)
                execute(blob["pending_id"])
            else:
                blob["status"] = "DENIED"
                r.set(k, json.dumps(blob).encode())
                twilio_send_sms(f"Denied {blob['pending_id']}", from_number)
            break
        return {"ok": True}

    # B) Prompting: PLAN [RAGMODE] :: <request> | SHOT | TYPE: ... | HOTKEY: ... | CLICK: x,y
    try:
        rag_mode, action_request, proposed_plan = parse_sms_to_plan(body)
    except Exception:
        twilio_send_sms(
            "Invalid format. Use: PLAN [RAGMODE] :: <request> | SHOT | TYPE: text | HOTKEY: ctrl+shift+p | CLICK: x,y",
            from_number,
        )
        return {"ok": True}

    # Reuse the /plan handler logic
    class _Tmp:
        def __init__(self, action_request, proposed_plan, rag_mode):
            self.action_request = action_request
            self.proposed_plan = proposed_plan
            self.rag_mode = rag_mode

    resp = plan(_Tmp(action_request, proposed_plan, rag_mode))  # type: ignore

    status = resp.get("status")
    code = resp.get("approval_code")
    pid = resp.get("pending_id")

    if status == "WAITING_HUMAN":
        twilio_send_sms(
            f"Council approved (pending human). Reply YES {code} or NO {code}. Pending: {pid}",
            from_number,
        )
    else:
        twilio_send_sms(
            f"Council rejected. Pending: {pid}. You can query http://localhost:7070/status/{pid} locally for details.",
            from_number,
        )

    return {"ok": True}


@app.post("/approve/telegram")
async def approve_telegram(request: Request):
    update = await request.json()
    msg = update.get("message", {}) or {}
    text = (msg.get("text") or "").strip().upper()
    chat = msg.get("chat", {}) or {}
    chat_id = str(chat.get("id", ""))

    # If TELEGRAM_CHAT_ID is set, only accept from that chat.
    if settings.TELEGRAM_CHAT_ID and chat_id != str(settings.TELEGRAM_CHAT_ID):
        return {"ok": True}

    parts = text.split()
    if len(parts) < 2:
        return {"ok": True}

    decision, code = parts[0], parts[1]

    # Find pending item by scanning. For larger usage, store code->pending mapping.
    for k in r.scan_iter(match=b"pending:*", count=500):
        blob = json.loads(r.get(k).decode())
        if blob.get("approval_code", "").upper() != code:
            continue
        if blob["status"] != "WAITING_HUMAN":
            return {"ok": True}

        if decision == "YES":
            blob["status"] = "APPROVED"
            r.set(k, json.dumps(blob).encode())
            telegram_send(f"Approved. Executing: {blob['pending_id']}")
            res = execute(blob["pending_id"])
            try:
                if isinstance(res, dict) and res.get("error"):
                    telegram_send(f"Execute failed for {blob['pending_id']}: {res['error']}")
            except Exception:
                pass
        elif decision == "NO":
            blob["status"] = "DENIED"
            r.set(k, json.dumps(blob).encode())
            telegram_send(f"Denied: {blob['pending_id']}")
        break

    return {"ok": True}


@app.get("/mcp/tools")
def mcp_tools():
    try:
        return {"tools": _mcp.list_tools(), "allowlisted_tools": sorted(list(_mcp.allowlisted_tools))}
    except Exception as e:
        return {"tools": {}, "error": str(e)}


@app.post("/mcp/sync")
def mcp_sync():
    """
    Fetch tools from MCP servers and store a snapshot in Redis for audit + quick UI.
    """
    snap = {
        "timestamp": time.time(),
        "tools": _mcp.list_tools(),
        "allowlisted_tools": sorted(list(_mcp.allowlisted_tools)),
    }
    r.set(b"mcp:tools_snapshot", json.dumps(snap, ensure_ascii=False).encode("utf-8"))
    return snap


# =====================
# Optional SaaS endpoints
# =====================


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _bearer_email(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1]
    data = decode_jwt(token)
    if not data:
        return None
    return str(data.get("sub") or "") or None


@app.post("/saas/register")
def saas_register(req: RegisterRequest):
    if not getattr(settings, "SAAS_ENABLED", 0):
        return {"error": "SAAS_ENABLED=0"}
    init_db()
    email = req.email.strip().lower()
    if not email or "@" not in email:
        return {"error": "invalid email"}
    if len(req.password) < 8:
        return {"error": "password must be >= 8 chars"}
    if get_user_by_email(email):
        return {"error": "user exists"}
    u = create_user(
        email=email,
        password_hash=hash_password(req.password),
        created_at=int(time.time()),
    )
    token = create_jwt(email)
    return {"ok": True, "token": token, "user": {"email": u.get("email"), "plan": u.get("plan")}}


@app.post("/saas/login")
def saas_login(req: LoginRequest):
    if not getattr(settings, "SAAS_ENABLED", 0):
        return {"error": "SAAS_ENABLED=0"}
    init_db()
    email = req.email.strip().lower()
    u = get_user_by_email(email)
    if not u:
        return {"error": "invalid credentials"}
    if not verify_password(req.password, u.get("password_hash") or ""):
        return {"error": "invalid credentials"}
    token = create_jwt(email)
    return {"ok": True, "token": token, "user": {"email": u.get("email"), "plan": u.get("plan")}}


@app.get("/saas/me")
def saas_me(request: Request):
    if not getattr(settings, "SAAS_ENABLED", 0):
        return {"error": "SAAS_ENABLED=0"}
    email = _bearer_email(request)
    if not email:
        return {"error": "unauthorized"}
    u = get_user_by_email(email)
    if not u:
        return {"error": "not found"}
    return {
        "ok": True,
        "user": {
            "email": u.get("email"),
            "plan": u.get("plan"),
            "created_at": u.get("created_at"),
        },
    }


@app.post("/saas/stripe/webhook")
async def saas_stripe_webhook(request: Request):
    if not getattr(settings, "SAAS_ENABLED", 0):
        return {"error": "SAAS_ENABLED=0"}
    init_db()
    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    return handle_stripe_webhook(raw, headers)