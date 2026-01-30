import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import pystray
from PIL import Image, ImageDraw

DEFAULT_API = "http://localhost:7070"

DEFAULT_PLAN = {
    "type": "desktop",
    "actions": [
        {"name": "screenshot", "path": "screenshot.png"}
    ]
}

RAG_MODES = ["naive", "advanced", "graphrag", "agentic", "finetune", "cag"]

def make_icon():
    img = Image.new("RGB", (64, 64), "black")
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 56, 56], outline="white", width=2)
    d.text((18, 22), "AI", fill="white")
    return img

class App:
    def __init__(self):
        self.api_base = DEFAULT_API

    def open_window(self):
        root = tk.Tk()
        root.title("Council Desktop Guardian — Send Prompt")
        root.geometry("820x820")

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Guardian API Base URL").pack(anchor="w")
        api_var = tk.StringVar(value=self.api_base)
        ttk.Entry(frm, textvariable=api_var).pack(fill="x")

        ttk.Label(frm, text="RAG Mode").pack(anchor="w", pady=(10,0))
        rag_var = tk.StringVar(value="advanced")
        ttk.Combobox(frm, textvariable=rag_var, values=RAG_MODES, state="readonly").pack(fill="x")

        dry_run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Dry run (preview only, no execution)", variable=dry_run_var).pack(anchor="w", pady=(6,0))

        ttk.Label(frm, text="Action Request (your prompt)").pack(anchor="w", pady=(10,0))
        prompt = tk.Text(frm, height=7)
        prompt.pack(fill="x")
        prompt.insert("1.0", "Take a screenshot and then type 'Hello from the council' in the focused field.")

        ttk.Label(frm, text="Proposed Plan (JSON) — executed only after council + your YES").pack(anchor="w", pady=(10,0))
        plan_box = tk.Text(frm, height=16)
        plan_box.pack(fill="both", expand=True)
        plan_box.insert("1.0", json.dumps(DEFAULT_PLAN, indent=2))

        # MCP tool helper UI
        mcp_frame = ttk.LabelFrame(frm, text="MCP Tool Helper (optional)", padding=8)
        mcp_frame.pack(fill="x", pady=(10,0))

        ttk.Label(mcp_frame, text="Server").grid(row=0, column=0, sticky="w")
        server_var = tk.StringVar(value="")
        server_combo = ttk.Combobox(mcp_frame, textvariable=server_var, values=[], state="readonly", width=40)
        server_combo.grid(row=0, column=1, sticky="we", padx=6)

        ttk.Label(mcp_frame, text="Tool").grid(row=1, column=0, sticky="w", pady=(6,0))
        tool_var = tk.StringVar(value="")
        tool_combo = ttk.Combobox(mcp_frame, textvariable=tool_var, values=[], state="readonly", width=60)
        tool_combo.grid(row=1, column=1, sticky="we", padx=6, pady=(6,0))

        ttk.Label(mcp_frame, text="Args (JSON)").grid(row=2, column=0, sticky="nw", pady=(6,0))
        args_box = tk.Text(mcp_frame, height=4)
        args_box.grid(row=2, column=1, sticky="we", padx=6, pady=(6,0))
        args_box.insert("1.0", json.dumps({"path":"README.md"}, indent=2))

        mcp_frame.columnconfigure(1, weight=1)

        status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=status, foreground="blue").pack(anchor="w", pady=(8,0))

        def _get_api():
            self.api_base = api_var.get().strip().rstrip("/")
            return self.api_base

        def refresh_mcp():
            api = _get_api()
            status.set("Fetching MCP tools...")
            def worker():
                try:
                    # sync snapshot first (optional)
                    try:
                        requests.post(api + "/mcp/sync", timeout=30)
                    except Exception:
                        pass
                    r = requests.get(api + "/mcp/tools", timeout=30)
                    r.raise_for_status()
                    data = r.json()
                    tools = data.get("tools") or {}
                    servers = sorted(list(tools.keys()))
                except Exception as e:
                    root.after(0, lambda: status.set(f"MCP error: {e}"))
                    return

                def apply():
                    server_combo["values"] = servers
                    if servers:
                        server_var.set(servers[0])
                        tool_combo["values"] = tools.get(servers[0], [])
                        if tools.get(servers[0]):
                            tool_var.set(tools[servers[0]][0])
                    status.set("MCP tools loaded.")
                root.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        def on_server_change(_evt=None):
            api = _get_api()
            try:
                r = requests.get(api + "/mcp/tools", timeout=10)
                data = r.json()
                tools = data.get("tools") or {}
                sv = server_var.get()
                tool_combo["values"] = tools.get(sv, [])
                if tools.get(sv):
                    tool_var.set(tools[sv][0])
            except Exception:
                pass

        server_combo.bind("<<ComboboxSelected>>", on_server_change)

        def add_mcp_action():
            try:
                plan_obj = json.loads(plan_box.get("1.0", "end").strip())
            except Exception as e:
                messagebox.showerror("Invalid Plan JSON", str(e))
                return
            try:
                args_obj = json.loads(args_box.get("1.0", "end").strip())
            except Exception as e:
                messagebox.showerror("Invalid Args JSON", str(e))
                return
            act = {
                "name": "mcp_call",
                "server": server_var.get(),
                "tool": tool_var.get(),
                "args": args_obj
            }
            plan_obj.setdefault("actions", [])
            plan_obj["actions"].insert(0, act)  # put first by default
            plan_box.delete("1.0", "end")
            plan_box.insert("1.0", json.dumps(plan_obj, indent=2))
            messagebox.showinfo("Added", "Inserted mcp_call action into plan (first action).")

        def do_send():
            api = _get_api()
            try:
                plan_obj = json.loads(plan_box.get("1.0", "end").strip())
            except Exception as e:
                messagebox.showerror("Invalid JSON", f"Proposed plan JSON is invalid:\n{e}")
                return

            payload = {
                "action_request": prompt.get("1.0", "end").strip(),
                "proposed_plan": plan_obj,
                "rag_mode": rag_var.get().strip(),
                "dry_run": bool(dry_run_var.get())
            }

            status.set("Sending to council...")
            def worker():
                try:
                    r = requests.post(api + "/plan", json=payload, timeout=120)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    root.after(0, lambda: status.set(f"Error: {e}"))
                    return

                msg = (
                    f"Status: {data.get('status')}\n"
                    f"Pending: {data.get('pending_id')}\n"
                    f"Approval code: {data.get('approval_code')}\n\n"
                    f"If Telegram/SMS is configured, you will be prompted to reply YES/NO."
                )
                root.after(0, lambda: messagebox.showinfo("Council Response", msg))
                root.after(0, lambda: status.set("Done."))
            threading.Thread(target=worker, daemon=True).start()

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(10,0))
        ttk.Button(btn_row, text="Send to Council (/plan)", command=do_send).pack(side="left")
        ttk.Button(btn_row, text="Close", command=root.destroy).pack(side="right")

        mcp_btns = ttk.Frame(mcp_frame)
        mcp_btns.grid(row=3, column=1, sticky="e", pady=(8,0))
        ttk.Button(mcp_btns, text="Refresh MCP tools", command=refresh_mcp).pack(side="left", padx=4)
        ttk.Button(mcp_btns, text="Add mcp_call action", command=add_mcp_action).pack(side="left", padx=4)

        root.mainloop()

    def run(self):
        icon = pystray.Icon(
            "CouncilGuardian",
            make_icon(),
            "Council Guardian",
            menu=pystray.Menu(
                pystray.MenuItem("Send Prompt…", lambda: threading.Thread(target=self.open_window, daemon=True).start()),
                pystray.MenuItem("Quit", lambda: icon.stop()),
            ),
        )
        icon.run()

if __name__ == "__main__":
    App().run()
