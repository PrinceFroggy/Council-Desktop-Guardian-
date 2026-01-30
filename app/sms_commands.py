import re
from typing import Dict, Any, List, Tuple

RAG_MODES = {"NAIVE","ADVANCED","GRAPHRAG","AGENTIC","FINETUNE","CAG"}

def parse_sms_to_plan(body: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    SMS format:
      PLAN [RAGMODE] :: <action_request> | SHOT | TYPE: <text> | HOTKEY: ctrl+shift+p | CLICK: x,y

    Examples:
      PLAN ADVANCED :: Take a screenshot and type hello | SHOT | TYPE: hello
      PLAN :: Take screenshot | SHOT

    If no actions specified, defaults to SHOT (safe).
    """
    raw = (body or "").strip()
    parts = [p.strip() for p in raw.split("|")]
    header = parts[0] if parts else raw

    m = re.match(r"^PLAN(?:\s+(\w+))?\s*::\s*(.+)$", header, flags=re.IGNORECASE)
    if not m:
        raise ValueError("SMS must start with: PLAN [RAGMODE] :: <request>")

    mode = (m.group(1) or "NAIVE").upper()
    if mode not in RAG_MODES:
        mode = "NAIVE"

    action_request = m.group(2).strip()

    actions: List[Dict[str, Any]] = []
    for a in parts[1:]:
        if not a:
            continue
        if re.match(r"^SHOT$", a, flags=re.IGNORECASE):
            actions.append({"name":"screenshot", "path":"screenshot.png"})
            continue
        m2 = re.match(r"^TYPE\s*:\s*(.+)$", a, flags=re.IGNORECASE)
        if m2:
            actions.append({"name":"type_text", "text": m2.group(1), "interval": 0.02})
            continue
        m3 = re.match(r"^HOTKEY\s*:\s*(.+)$", a, flags=re.IGNORECASE)
        if m3:
            keys = [k.strip().lower() for k in m3.group(1).split("+") if k.strip()]
            actions.append({"name":"hotkey", "keys": keys})
            continue
        m4 = re.match(r"^CLICK\s*:\s*(\d+)\s*,\s*(\d+)$", a, flags=re.IGNORECASE)
        if m4:
            actions.append({"name":"click", "x": int(m4.group(1)), "y": int(m4.group(2))})
            continue

    if not actions:
        actions = [{"name":"screenshot", "path":"screenshot.png"}]

    plan = {"type":"desktop", "actions": actions}
    return mode.lower(), action_request, plan
