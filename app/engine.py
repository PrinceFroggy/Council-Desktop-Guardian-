import json
import time
import uuid
from typing import Dict, Any, List

from .rag_modes import get_context
from .notify import telegram_send

def _approval_code(n=8) -> str:
    import random, string
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def _preview_actions(plan: Dict[str, Any]) -> List[str]:
    out = []
    for i, act in enumerate(plan.get("actions", [])):
        name = act.get("name", "?")
        if name == "notify":
            out.append(f"{i+1}. notify: channel={act.get('channel')} message={str(act.get('message',''))[:80]}")
        elif name == "paper_trade":
            out.append(f"{i+1}. paper_trade: {act.get('side')} {act.get('qty')} {act.get('ticker')} @ {act.get('price')}")
        elif name == "mcp_call":
            out.append(f"{i+1}. mcp_call: server={act.get('server')} tool={act.get('tool')}")
        elif name == "web_fetch":
            out.append(f"{i+1}. web_fetch: url={act.get('url')}")
        else:
            out.append(f"{i+1}. {name}: {act}")
    return out

def submit_request(*, rag, r, providers: Dict[str, Any], council, action_request: str, proposed_plan: Dict[str, Any], rag_mode: str = "advanced", dry_run: bool = True) -> Dict[str, Any]:
    """Shared planning pipeline used by background schedulers."""
    ctx_obj = get_context(rag, r, providers["ollama"], "llama3.1:8b", action_request, rag_mode)
    ctx = ctx_obj.get("chunks") or []
    if not ctx and ctx_obj.get("mode") == "agentic":
        for b in ctx_obj.get("bundles", []):
            ctx.extend(b.get("chunks", []))
    if ctx_obj.get("mode") == "cag" and ctx_obj.get("cached"):
        return ctx_obj["cached"]

    provider_plan = [
        ("ollama", "qwen2.5-coder:7b"),
        ("ollama", "llama3.1:8b"),
        ("ollama", "qwen2.5-coder:7b"),
        ("ollama", "llama3.1:8b"),
    ]

    verdict = council.review(
        action_request=action_request,
        rag_context=ctx,
        proposed_plan=proposed_plan,
        provider_plan=provider_plan
    )

    pending_id = f"pending:{int(time.time())}:{uuid.uuid4().hex[:6]}"
    code = _approval_code()

    status = "REJECTED_BY_COUNCIL"
    if bool(dry_run):
        status = "DRY_RUN"
    else:
        if verdict.get("final", {}).get("verdict") == "YES":
            status = "WAITING_HUMAN"

    blob = {
        "pending_id": pending_id,
        "approval_code": code,
        "created_at": time.time(),
        "status": status,
        "rag": ctx_obj,
        "verdict": verdict,
        "proposed_plan": proposed_plan,
        "dry_run": bool(dry_run),
        "execution_preview": _preview_actions(proposed_plan),
        "action_request": action_request,
        "rag_mode": rag_mode,
    }

    r.set(pending_id.encode(), json.dumps(blob).encode("utf-8"))

    # notify if council said YES and not dry-run
    try:
        if status == "WAITING_HUMAN":
            msg = verdict.get("final", {}).get("message_to_human") or json.dumps(verdict.get("final", {}), ensure_ascii=False)
            telegram_send(
                f"Council approved (pending human).\nApproval code: {code}\nPending: {pending_id}\n\n{msg}\n\nReply: YES {code} or NO {code}"
            )
        elif status == "DRY_RUN":
            telegram_send(
                f"[DryRun] News proposal created. Pending: {pending_id}\nCode: {code}\n\nPreview:\n" + "\n".join(blob["execution_preview"])
            )
    except Exception:
        pass

    return {"pending_id": pending_id, "status": status, "approval_code": code, "verdict": verdict, "rag": ctx_obj, "execution_preview": blob.get("execution_preview")}
