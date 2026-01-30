import os
import re
import subprocess
from typing import Dict, Any, List, Tuple

class DangerousToolError(Exception):
    pass

# NOTE: This is intentionally NOT "unrestricted".
# It requires:
#  - ENABLE_DANGEROUS_TOOLS=1
#  - human approval already granted by YES <code>
#  - command validation (blocks obviously destructive/exfil patterns)

BLOCK_PATTERNS = [
    r"(?i)\brm\b\s+-rf\b",
    r"(?i)\bmkfs\b",
    r"(?i)\bformat\b\s+",
    r"(?i)\bshutdown\b",
    r"(?i)\breboot\b",
    r"(?i)\bsudo\b",
    r"(?i)curl\b.*\|\s*bash",
    r"(?i)wget\b.*\|\s*bash",
    r"(?i)powershell\b.*iex\b",
    r"(?i)Invoke-Expression",
    r"(?i)nc\b|netcat\b",
]

def _enabled() -> bool:
    return os.getenv("ENABLE_DANGEROUS_TOOLS", "0") == "1"

def validate_shell_command(cmd: str) -> None:
    if not _enabled():
        raise DangerousToolError("Dangerous tools are disabled. Set ENABLE_DANGEROUS_TOOLS=1 to enable.")
    c = cmd.strip()
    if not c:
        raise DangerousToolError("Empty command")
    for pat in BLOCK_PATTERNS:
        if re.search(pat, c):
            raise DangerousToolError("Command rejected by safety block pattern")

def run_shell(repo_path: str, cmd: str, timeout_seconds: int = 60) -> Dict[str, Any]:
    validate_shell_command(cmd)
    p = subprocess.run(
        cmd,
        cwd=repo_path,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return {
        "returncode": p.returncode,
        "stdout": p.stdout[-8000:],
        "stderr": p.stderr[-8000:],
    }

def validate_fs_path(repo_path: str, path: str) -> str:
    if not _enabled():
        raise DangerousToolError("Dangerous tools are disabled. Set ENABLE_DANGEROUS_TOOLS=1 to enable.")
    # Allow absolute paths ONLY if explicitly enabled (still not recommended).
    allow_abs = os.getenv("ALLOW_ABSOLUTE_PATHS", "0") == "1"
    if os.path.isabs(path) and not allow_abs:
        raise DangerousToolError("Absolute paths disabled. Set ALLOW_ABSOLUTE_PATHS=1 if you really need it.")
    # Normalize + basic traversal block
    norm = os.path.normpath(path)
    if ".." in norm.replace("\\", "/").split("/"):
        raise DangerousToolError("Path traversal rejected ('..').")
    # If relative, treat relative to repo root
    if not os.path.isabs(norm):
        norm = os.path.normpath(os.path.join(repo_path, norm))
    return norm

def fs_read(repo_path: str, path: str, max_bytes: int = 2_000_000) -> Dict[str, Any]:
    p = validate_fs_path(repo_path, path)
    with open(p, "rb") as f:
        data = f.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    return {"path": p, "truncated": truncated, "content": text}

def fs_write(repo_path: str, path: str, content: str) -> Dict[str, Any]:
    p = validate_fs_path(repo_path, path)
    # Create parent dirs if relative
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": p, "bytes": len(content.encode("utf-8"))}
