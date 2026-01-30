# Tray Client (macOS menu bar + Windows tray)

This tray app lets you send a prompt from your desktop to the Guardian API (`/plan`) without using curl.

## Install (outside Docker)

If you run the Guardian in Docker, you can still run the tray on your host machine:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python client_tray/tray.py
```

## macOS permissions
If you want the Guardian to execute desktop actions (PyAutoGUI), you must grant Accessibility permissions
to the process that actually runs PyAutoGUI (typically your Python/Docker host).

Tip: For best results on macOS, run Guardian locally (not inside Docker) when doing desktop control.

## MCP Tool Helper

The tray UI can fetch MCP tools from the Guardian (`/mcp/tools`) and insert an `mcp_call` action into your plan JSON.
