import json
import threading
import webbrowser
import os

import rumps
from flask import Flask, request, render_template_string
import requests

DEFAULT_API = "http://localhost:7070"

DEFAULT_PLAN = {
    "type": "desktop",
    "actions": [
        {"name": "screenshot", "path": "screenshot.png"}
    ]
}

RAG_MODES = ["naive", "advanced", "graphrag", "agentic", "finetune", "cag"]

HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Council Desktop Guardian — Send Prompt</title>
  <style>
    body { font-family: -apple-system, system-ui; margin: 18px; }
    h2 { margin: 0 0 14px 0; }
    label { font-weight: 600; display:block; margin-top: 12px; }
    input[type=text], textarea, select { width: 100%; padding: 10px; border-radius: 10px; border: 1px solid #ddd; }
    textarea { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .row { display:flex; gap:12px; }
    .row > div { flex: 1; }
    .btns { margin-top: 14px; display:flex; gap:10px; }
    button { padding: 10px 14px; border-radius: 12px; border: 0; background: #111; color: #fff; cursor: pointer; }
    button.secondary { background: #666; }
    .msg { margin-top: 12px; padding: 10px; border-radius: 12px; background: #f5f5f5; white-space: pre-wrap; }
  </style>
</head>
<body>
  <h2>Council Desktop Guardian — Send Prompt</h2>

  <form method="post" action="/send">
    <label>Guardian API Base URL</label>
    <input type="text" name="api_base" value="{{api_base}}" />

    <div class="row">
      <div>
        <label>RAG Mode</label>
        <select name="rag_mode">
          {% for m in rag_modes %}
            <option value="{{m}}" {% if m==rag_mode %}selected{% endif %}>{{m}}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label>Dry run (preview only, no execution)</label>
        <select name="dry_run">
          <option value="true" {% if dry_run %}selected{% endif %}>true</option>
          <option value="false" {% if not dry_run %}selected{% endif %}>false</option>
        </select>
      </div>
    </div>

    <label>Action Request (your prompt)</label>
    <textarea name="prompt" rows="6">{{prompt}}</textarea>

    <label>Proposed Plan (JSON)</label>
    <textarea name="plan_json" rows="14">{{plan_json}}</textarea>

    <label>MCP Tool Helper (optional)</label>
    <div class="row">
      <div>
        <label>Server</label>
        <input type="text" name="mcp_server" value="{{mcp_server}}" placeholder="(choose via Refresh below)"/>
      </div>
      <div>
        <label>Tool</label>
        <input type="text" name="mcp_tool" value="{{mcp_tool}}" placeholder="(choose via Refresh below)"/>
      </div>
    </div>

    <label>Args (JSON)</label>
    <textarea name="mcp_args" rows="5">{{mcp_args}}</textarea>

    <div class="btns">
      <button type="submit">Send to Council (/plan)</button>
      <button type="button" class="secondary" onclick="window.location='/mcp_refresh'">Refresh MCP tools</button>
      <button type="button" class="secondary" onclick="window.location='/mcp_add'">Add mcp_call action</button>
      <button type="button" class="secondary" onclick="window.location='/close'">Close</button>
    </div>
  </form>

  {% if msg %}
    <div class="msg">{{msg}}</div>
  {% endif %}

  {% if tools %}
    <div class="msg">
MCP tools loaded:
{% for s, arr in tools.items() %}
- {{s}}: {{arr|length}} tools
{% endfor %}
    </div>
  {% endif %}
</body>
</html>
"""

def bool_from_str(v: str) -> bool:
    return str(v).lower().strip() in ("1","true","yes","y","on")

class TrayWebUI:
    """
    A tiny local web UI so we don't need Tk.
    rumps handles tray icon/menu; browser handles the form window.
    """
    def __init__(self):
        self.api_base = os.getenv("API_BASE", DEFAULT_API).rstrip("/")
        self.rag_mode = "advanced"
        self.dry_run = True
        self.prompt = "Take a screenshot and then type 'Hello from the council' in the focused field."
        self.plan_obj = DEFAULT_PLAN.copy()

        self.mcp_server = ""
        self.mcp_tool = ""
        self.mcp_args = {"path": "README.md"}
        self.mcp_tools_cache = {}

        self.app = Flask(__name__)
        self._register_routes()

    def _register_routes(self):
        @self.app.get("/")
        def index():
            return render_template_string(
                HTML,
                api_base=self.api_base,
                rag_modes=RAG_MODES,
                rag_mode=self.rag_mode,
                dry_run=self.dry_run,
                prompt=self.prompt,
                plan_json=json.dumps(self.plan_obj, indent=2),
                mcp_server=self.mcp_server,
                mcp_tool=self.mcp_tool,
                mcp_args=json.dumps(self.mcp_args, indent=2),
                msg="",
                tools=self.mcp_tools_cache,
            )

        @self.app.post("/send")
        def send():
            self.api_base = request.form.get("api_base","").strip().rstrip("/") or DEFAULT_API
            self.rag_mode = request.form.get("rag_mode","advanced").strip()
            self.dry_run = bool_from_str(request.form.get("dry_run","true"))
            self.prompt = request.form.get("prompt","").strip()

            plan_json = request.form.get("plan_json","").strip()
            try:
                self.plan_obj = json.loads(plan_json)
            except Exception as e:
                return render_template_string(HTML, api_base=self.api_base, rag_modes=RAG_MODES, rag_mode=self.rag_mode,
                                              dry_run=self.dry_run, prompt=self.prompt, plan_json=plan_json,
                                              mcp_server=self.mcp_server, mcp_tool=self.mcp_tool,
                                              mcp_args=json.dumps(self.mcp_args, indent=2),
                                              msg=f"Invalid Plan JSON:\n{e}", tools=self.mcp_tools_cache)

            payload = {
                "action_request": self.prompt,
                "proposed_plan": self.plan_obj,
                "rag_mode": self.rag_mode,
                "dry_run": bool(self.dry_run),
            }

            try:
                r = requests.post(self.api_base + "/plan", json=payload, timeout=300)
                r.raise_for_status()
                data = r.json()
                msg = (
                    f"Status: {data.get('status')}\n"
                    f"Pending: {data.get('pending_id')}\n"
                    f"Approval code: {data.get('approval_code')}\n\n"
                    f"If Telegram/SMS is configured, you will be prompted to reply YES/NO."
                )
            except Exception as e:
                msg = f"Error calling /plan:\n{e}"

            return render_template_string(
                HTML,
                api_base=self.api_base,
                rag_modes=RAG_MODES,
                rag_mode=self.rag_mode,
                dry_run=self.dry_run,
                prompt=self.prompt,
                plan_json=json.dumps(self.plan_obj, indent=2),
                mcp_server=self.mcp_server,
                mcp_tool=self.mcp_tool,
                mcp_args=json.dumps(self.mcp_args, indent=2),
                msg=msg,
                tools=self.mcp_tools_cache,
            )

        @self.app.get("/mcp_refresh")
        def mcp_refresh():
            msg = "Fetching MCP tools..."
            try:
                # sync snapshot first (optional)
                try:
                    requests.post(self.api_base + "/mcp/sync", timeout=30)
                except Exception:
                    pass
                r = requests.get(self.api_base + "/mcp/tools", timeout=30)
                r.raise_for_status()
                data = r.json()
                tools = data.get("tools") or {}
                self.mcp_tools_cache = tools

                # pick first server/tool as defaults
                servers = sorted(list(tools.keys()))
                if servers:
                    self.mcp_server = servers[0]
                    if tools.get(self.mcp_server):
                        self.mcp_tool = tools[self.mcp_server][0]
                msg = "MCP tools loaded."
            except Exception as e:
                msg = f"MCP error: {e}"

            return render_template_string(
                HTML,
                api_base=self.api_base,
                rag_modes=RAG_MODES,
                rag_mode=self.rag_mode,
                dry_run=self.dry_run,
                prompt=self.prompt,
                plan_json=json.dumps(self.plan_obj, indent=2),
                mcp_server=self.mcp_server,
                mcp_tool=self.mcp_tool,
                mcp_args=json.dumps(self.mcp_args, indent=2),
                msg=msg,
                tools=self.mcp_tools_cache,
            )

        @self.app.get("/mcp_add")
        def mcp_add():
            msg = ""
            try:
                act = {
                    "name": "mcp_call",
                    "server": self.mcp_server,
                    "tool": self.mcp_tool,
                    "args": self.mcp_args,
                }
                self.plan_obj.setdefault("actions", [])
                self.plan_obj["actions"].insert(0, act)
                msg = "Inserted mcp_call action into plan (first action)."
            except Exception as e:
                msg = f"Failed to add mcp_call: {e}"

            return render_template_string(
                HTML,
                api_base=self.api_base,
                rag_modes=RAG_MODES,
                rag_mode=self.rag_mode,
                dry_run=self.dry_run,
                prompt=self.prompt,
                plan_json=json.dumps(self.plan_obj, indent=2),
                mcp_server=self.mcp_server,
                mcp_tool=self.mcp_tool,
                mcp_args=json.dumps(self.mcp_args, indent=2),
                msg=msg,
                tools=self.mcp_tools_cache,
            )

        @self.app.get("/close")
        def close():
            return "<script>window.close();</script>"

    def serve(self, host="127.0.0.1", port=8799):
        self.app.run(host=host, port=port, debug=False, use_reloader=False)

class CouncilTray(rumps.App):
    def __init__(self):
        super().__init__("Council", quit_button=None)
        self.ui = TrayWebUI()
        self.web_port = int(os.getenv("TRAY_WEB_PORT", "8799"))

        self.menu = [
            rumps.MenuItem("Send Prompt…", callback=self.open_prompt),
            rumps.MenuItem("Open API Docs", callback=self.open_docs),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        # start local web UI in background
        t = threading.Thread(target=self.ui.serve, kwargs={"port": self.web_port}, daemon=True)
        t.start()

    def open_prompt(self, _):
        webbrowser.open(f"http://127.0.0.1:{self.web_port}/")

    def open_docs(self, _):
        webbrowser.open(self.ui.api_base + "/docs")

    def quit_app(self, _):
        rumps.quit_application()

if __name__ == "__main__":
    CouncilTray().run()