import os
import re
from typing import Any, Dict, Tuple, List

class MCPPolicyError(Exception):
    pass

def _find_strings(obj: Any) -> List[str]:
    out: List[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_find_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_strings(v))
    return out

def validate_mcp_call(repo_path: str, server: str, tool: str, args: Dict[str, Any]) -> None:
    """
    Conservative, generic safety checks for MCP tool calls.
    You can loosen/tighten per-tool rules later.
    """
    sargs = _find_strings(args)

    # Block obvious injection / shell-ish patterns in args
    bad_tokens = [";","&&","||","`","$(",">", "<"]
    for s in sargs:
        if any(tok in s for tok in bad_tokens):
            raise MCPPolicyError("Rejected: suspicious shell-like tokens in args")

    # Block path traversal in any string argument that looks like a path
    for s in sargs:
        if ".." in s.replace("\\","/"):
            raise MCPPolicyError("Rejected: path traversal '..' in args")

    # If there is a 'path' field, enforce repo-root containment when possible
    p = args.get("path")
    if isinstance(p, str) and p.strip():
        # reject absolute paths by default
        if os.path.isabs(p) or re.match(r"^[A-Za-z]:\\", p):
            raise MCPPolicyError("Rejected: absolute paths are not allowed by default")
        # normalize and ensure within repo
        joined = os.path.normpath(os.path.join(repo_path, p))
        repo_norm = os.path.normpath(repo_path)
        if not joined.startswith(repo_norm):
            raise MCPPolicyError("Rejected: path escapes repo root")

    # Tool-name specific hard blocks (you can customize)
    blocked_tool_patterns = [
        r"(?i)delete",
        r"(?i)rm",
        r"(?i)exec",
        r"(?i)shell",
        r"(?i)network",
        r"(?i)upload",
    ]
    for pat in blocked_tool_patterns:
        if re.search(pat, tool):
            raise MCPPolicyError("Rejected: tool name matches blocked pattern")
