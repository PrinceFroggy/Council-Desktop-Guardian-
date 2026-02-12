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
providers = load_providers()
rag = RAG(r)
ensure_vector_index(r, rag.dim)
council = Council(providers)

# MCP registry (optional)
_mcp = MCPRegistry(config_path=os.path.join(os.path.dirname(__file__), 'mcp_servers.json'))
try:
    _mcp.load()
except Exception:
    pass

# Start daily research + reflection (Telegram)
try:
    start_scheduler(rag, r, providers, council)
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
  # {"type":"desktop","actions":[...]} etc.

def _preview_actions(plan: dict) -> list[str]:
    actions = (plan or {}).get("actions", []) or []
    out = []
    for i, act in enumerate(actions):
        name = act.get("name")
        if name == "type_text":
            txt = (act.get("text") or "")
            out.append(f"{i+1}. type_text: {txt[:60]}{'...' if len(txt)>60 else ''}")
        elif name == "hotkey":
            out.append(f"{i+1}. hotkey: {act.get('keys')}")
        elif name == "click":
            out.append(f"{i+1}. click: x={act.get('x')} y={act.get('y')} button={act.get('button','left')}")
        elif name == "move_mouse":
            out.append(f"{i+1}. move_mouse: x={act.get('x')} y={act.get('y')} duration={act.get('duration',0.2)}")
        elif name == "screenshot":
            out.append(f"{i+1}. screenshot: path={act.get('path','screenshot.png')}")
        elif name == "mcp_call":
            out.append(f"{i+1}. mcp_call: {act.get('server')}:{act.get('tool')} args={act.get('args')}")
        elif name == "shell_exec":
            out.append(f"{i+1}. shell_exec: {act.get('cmd')}")
        elif name == "fs_read":
            out.append(f"{i+1}. fs_read: path={act.get('path')}")
        elif name == "fs_write":
            out.append(f"{i+1}. fs_write: path={act.get('path')} bytes≈{len((act.get('content') or '').encode('utf-8'))}")
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
    ctx_obj = get_context(rag, r, providers["ollama"], "llama3.1:8b", req.action_request, req.rag_mode)
    # normalize to list of chunks for council (best effort)
    ctx = ctx_obj.get("chunks") or []
    if not ctx and ctx_obj.get("mode") == "agentic":
        # flatten agentic bundles
        for b in ctx_obj.get("bundles", []):
            ctx.extend(b.get("chunks", []))
    if ctx_obj.get("mode") == "cag" and ctx_obj.get("cached"):
        # if cached council response exists, return it directly
        return ctx_obj["cached"]


    provider_plan = [
        ("ollama", "qwen2.5-coder:7b"),
        ("ollama", "llama3.1:8b"),
        ("ollama", "qwen2.5-coder:7b"),
        ("ollama", "llama3.1:8b"),
    ]

    verdict = council.review(
        action_request=req.action_request,
        rag_context=ctx,
        proposed_plan=req.proposed_plan,
        provider_plan=provider_plan
    )

    pending_id = f"pending:{int(time.time())}:{uuid.uuid4().hex[:6]}"
    code = _approval_code()

    blob = {
        "pending_id": pending_id,
        "approval_code": code,
        "created_at": time.time(),
        "status": ("DRY_RUN" if (bool(getattr(req, "dry_run", False)) and verdict["final"].get("verdict") == "YES") else ("WAITING_HUMAN" if verdict["final"].get("verdict") == "YES" else "REJECTED_BY_COUNCIL")),
        "rag": ctx_obj,
        "verdict": verdict,
        "proposed_plan": req.proposed_plan,
        "dry_run": bool(getattr(req, "dry_run", False)),
        "execution_preview": _preview_actions(req.proposed_plan),
        "action_request": req.action_request,
    }
    r.set(pending_id.encode(), json.dumps(blob).encode())

    if req.rag_mode.lower() == "cag":
        # cache the full response object (so repeated prompts behave consistently)
        try:
            cag_set(r, prompt=req.action_request, rag_mode="cag", response_obj={"pending_id": pending_id, "status": blob["status"], "approval_code": code, "verdict": verdict, "rag": ctx_obj})
        except Exception:
            pass

    caller = "unknown"
    try:
        # If you later add Request injection, you'll read headers.
        # For now, caller stays "unknown".
        caller = request.headers.get("X-Caller", "unknown")
    except Exception:
        pass

    if blob["status"] == "WAITING_HUMAN":
        msg = verdict["final"].get("message_to_human") or json.dumps(verdict["final"], ensure_ascii=False)
        telegram_send(
            f"[{caller}] Council approved (pending human).\n"
            f"Approval code: {code}\n"
            f"Pending: {pending_id}\n\n"
            f"{msg}\n\n"
            f"Reply: YES {code} or NO {code}"
        )

    elif blob["status"] == "DRY_RUN":
        preview = "\n".join(blob.get("execution_preview") or []) or "(no actions)"
        msg = verdict["final"].get("message_to_human") or ""
        telegram_send(
            f"[{caller}] Dry run preview (no execution).\n"
            f"Pending: {pending_id}\n\n"
            f"{msg}\n\n"
            f"Planned actions:\n{preview}\n\n"
            f"If you want to execute, resend with dry_run=false."
        )

    elif blob["status"] == "REJECTED_BY_COUNCIL":
        # NEW: Send rejection details to Telegram so you see why it failed.
        final = verdict.get("final") or {}
        reasons = final.get("reasons") or []
        required = final.get("required_changes") or []
        msg = final.get("message_to_human") or ""

        reasons_txt = "\n".join([f"- {r}" for r in reasons]) or "(no reasons)"
        required_txt = "\n".join([f"- {r}" for r in required]) or "(none)"

        telegram_send(
            f"[{caller}] Council REJECTED the request.\n"
            f"Pending: {pending_id}\n"
            f"Approval code: {code}\n\n"
            f"Reasons:\n{reasons_txt}\n\n"
            f"Required changes:\n{required_txt}\n\n"
            f"{msg}"
        )

    return {"pending_id": pending_id, "status": blob["status"], "approval_code": code, "verdict": verdict, "execution_preview": blob.get("execution_preview")}

@app.get("/status/{pending_id}")
def status(pending_id: str):
    data = r.get(pending_id.encode())
    if not data:
        return {"error": "not found"}
    return json.loads(data.decode())

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

    plan = blob.get("proposed_plan") or {}
    plan_type = plan.get("type") or "desktop"
    if plan_type not in ("desktop", "trading"):
        blob["status"] = "DENIED"
        r.set(pending_id.encode(), json.dumps(blob).encode())
        return {"error": f"Unsupported plan type: {plan_type}"}

    results = []
    for act in plan.get("actions", []):
        if act.get("name") == "mcp_call":
            server = act.get("server")
            tool = act.get("tool")
            args = act.get("args") or {}
            try:
                validate_mcp_call(settings.REPO_PATH, server, tool, args)
                res = _mcp.call_tool(server, tool, args)
                results.append(f"mcp_call {server}:{tool} OK")
                blob.setdefault("mcp_results", []).append({"server": server, "tool": tool, "result": res})
            except MCPPolicyError as pe:
                raise RuntimeError(f"Rejected by MCP policy: {pe}")
            except Exception as e:
                raise
            continue

        if act.get("name") == "shell_exec":
            cmd = act.get("cmd") or ""
            res = run_shell(settings.REPO_PATH, cmd, timeout_seconds=int(act.get("timeout_seconds", 60)))
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
            blob.setdefault("web_fetches", []).append({
                "url": url,
                "status": res.get("status"),
                "truncated": res.get("truncated"),
            })
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
                results.append("paper_trade DENIED: requires_quote=true. Re-plan with a real quote price and price_confirmed=true.")
                blob.setdefault("trade_errors", []).append({"ticker": ticker, "error": "requires_quote"})
                continue
            res = apply_paper_trade(r, ticker=ticker, side=side, qty=qty, price=price, start_cash=settings.PAPER_START_CASH)
            results.append("paper_trade OK" if res.get("ok") else f"paper_trade ERROR: {res.get('error')}")
            blob.setdefault("paper_trades", []).append(res)
            continue


        if act.get("name") == "alpaca_order":
            # Real order via Alpaca Trading API (still behind your approval gate)
            if settings.TRADING_BROKER.lower() != "alpaca":
                results.append("alpaca_order DENIED: TRADING_BROKER is not alpaca")
                blob.setdefault("trade_errors", []).append({"broker":"alpaca","error":"broker_disabled"})
                continue
            # Prevent accidental live trades: require explicit confirmation flags
            broker_mode = (act.get("broker_mode") or ("paper" if settings.ALPACA_PAPER else "live")).lower()
            if broker_mode not in ("paper","live"):
                results.append("alpaca_order DENIED: broker_mode must be paper|live")
                blob.setdefault("trade_errors", []).append({"broker":"alpaca","error":"bad_broker_mode"})
                continue
            if broker_mode == "live":
                if not act.get("confirm_live_trade"):
                    results.append("alpaca_order DENIED: missing confirm_live_trade=true")
                    blob.setdefault("trade_errors", []).append({"broker":"alpaca","error":"live_not_confirmed"})
                    continue
                # Also ensure env is configured for live or explicitly overridden
                if settings.ALPACA_PAPER:
                    results.append("alpaca_order DENIED: ALPACA_PAPER=1 but broker_mode=live")
                    blob.setdefault("trade_errors", []).append({"broker":"alpaca","error":"mode_mismatch"})
                    continue
            if broker_mode == "paper" and not settings.ALPACA_PAPER:
                results.append("alpaca_order DENIED: ALPACA_PAPER=0 but broker_mode=paper")
                blob.setdefault("trade_errors", []).append({"broker":"alpaca","error":"mode_mismatch"})
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
                    take_profit_limit_price=act.get("take_profit_limit_price") or (act.get("take_profit") or {}).get("limit_price"),
                    stop_loss_stop_price=act.get("stop_loss_stop_price") or (act.get("stop_loss") or {}).get("stop_price"),
                    stop_loss_limit_price=act.get("stop_loss_limit_price") or (act.get("stop_loss") or {}).get("limit_price"),
                )
                results.append(f"alpaca_order OK id={order.get('id', '')} status={order.get('status', '')}")
                blob.setdefault("alpaca_orders", []).append(order)
            except AlpacaError as e:
                results.append(f"alpaca_order ERROR: {str(e)[:200]}")
                blob.setdefault("trade_errors", []).append({"broker":"alpaca","error":str(e)})
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
            if blob.get("approval_code","").upper() != code:
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
            from_number
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
            from_number
        )
    else:
        twilio_send_sms(
            f"Council rejected. Pending: {pid}. You can query http://localhost:7070/status/{pid} locally for details.",
            from_number
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
            execute(blob["pending_id"])
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
        "allowlisted_tools": sorted(list(_mcp.allowlisted_tools))
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
    u = create_user(email=email, password_hash=hash_password(req.password), created_at=int(time.time()))
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
    return {"ok": True, "user": {"email": u.get("email"), "plan": u.get("plan"), "created_at": u.get("created_at")}}


@app.post("/saas/stripe/webhook")
async def saas_stripe_webhook(request: Request):
    if not getattr(settings, "SAAS_ENABLED", 0):
        return {"error": "SAAS_ENABLED=0"}
    init_db()
    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    return handle_stripe_webhook(raw, headers)