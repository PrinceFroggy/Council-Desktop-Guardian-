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
from .llm_providers import build_providers
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

load_dotenv()

app = FastAPI()

r = get_redis(settings.REDIS_URL)
providers = build_providers(settings.OLLAMA_HOST)
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
    start_scheduler(providers["ollama"], "llama3.1:8b")
except Exception:
    pass

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
def plan(req: PlanRequest):
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

    if blob["status"] == "WAITING_HUMAN":
        msg = verdict["final"].get("message_to_human") or json.dumps(verdict["final"], ensure_ascii=False)
        telegram_send(
            f"Council approved (pending human).\nApproval code: {code}\nPending: {pending_id}\n\n{msg}\n\nReply: YES {code} or NO {code}"
        )
    elif blob["status"] == "DRY_RUN":
        preview = "\n".join(blob.get("execution_preview") or [])
        telegram_send(
            f"Dry run preview (no execution).\nPending: {pending_id}\n\nPlanned actions:\n{preview}\n\nIf you want to execute, resend the same request with dry_run=false."
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
    if plan.get("type") != "desktop":
        blob["status"] = "DENIED"
        r.set(pending_id.encode(), json.dumps(blob).encode())
        return {"error": "Only desktop plans are wired in this template."}

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
