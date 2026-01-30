import json
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

# Minimal MCP stdio JSON-RPC client.
# Safety: MCP calls are only executed if:
#   - tool name is allowlisted in app/mcp_servers.json
#   - council approves
#   - you reply YES (human approval)

class MCPError(Exception):
    pass

class MCPServerProcess:
    def __init__(self, name: str, command: List[str], env: Dict[str, str], timeout_seconds: int = 20):
        self.name = name
        self.command = command
        self.env = env or {}
        self.timeout_seconds = timeout_seconds
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1

    def start(self) -> None:
        if self.proc is not None:
            return
        merged = os.environ.copy()
        merged.update(self.env)
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=merged,
            bufsize=1
        )

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def _send(self, obj: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _recv(self) -> Dict[str, Any]:
        assert self.proc and self.proc.stdout
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except Exception:
                continue
        raise MCPError(f"Timeout waiting for MCP response from {self.name}")

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self.start()
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            resp = self._recv()
            if "error" in resp:
                raise MCPError(str(resp["error"]))
            return resp.get("result")

class MCPRegistry:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.servers: Dict[str, MCPServerProcess] = {}
        self.allowlisted_tools: set[str] = set()

    def load(self) -> None:
        if not os.path.exists(self.config_path):
            return
        cfg = json.loads(open(self.config_path, "r", encoding="utf-8").read())
        self.allowlisted_tools = set(cfg.get("allowlisted_tools", []) or [])
        for s in cfg.get("servers", []) or []:
            if s.get("transport") != "stdio":
                continue
            name = s["name"]
            cmd = s["command"]
            env = s.get("env", {}) or {}
            timeout = int(s.get("timeout_seconds", 20))
            self.servers[name] = MCPServerProcess(name=name, command=cmd, env=env, timeout_seconds=timeout)

    def list_tools(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for name, sp in self.servers.items():
            try:
                res = sp.request("tools/list", {})
                tools: List[str] = []
                if isinstance(res, dict) and isinstance(res.get("tools"), list):
                    for t in res["tools"]:
                        if isinstance(t, dict) and "name" in t:
                            tools.append(str(t["name"]))
                out[name] = tools
            except Exception:
                out[name] = []
        return out

    def call_tool(self, server: str, tool_name: str, args: Dict[str, Any]) -> Any:
        if self.allowlisted_tools and tool_name not in self.allowlisted_tools:
            raise MCPError(f"Tool not allowlisted: {tool_name}")
        if server not in self.servers:
            raise MCPError(f"Unknown MCP server: {server}")
        return self.servers[server].request("tools/call", {"name": tool_name, "arguments": args or {}})
