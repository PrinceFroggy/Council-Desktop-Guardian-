from typing import Dict, Any
import pyautogui

pyautogui.FAILSAFE = True  # move mouse to upper-left corner to abort

ALLOWLIST = {"screenshot", "move_mouse", "click", "type_text", "hotkey", "mcp_call", "shell_exec", "fs_read", "fs_write", "web_fetch"}

def execute_action(action: Dict[str, Any]) -> str:
    name = action.get("name")
    if name not in ALLOWLIST:
        raise ValueError(f"Action '{name}' not allowlisted.")

    if name == "screenshot":
        path = action.get("path", "screenshot.png")
        img = pyautogui.screenshot()
        img.save(path)
        return f"saved screenshot to {path}"

    if name == "move_mouse":
        x, y = int(action["x"]), int(action["y"])
        duration = float(action.get("duration", 0.2))
        pyautogui.moveTo(x, y, duration=duration)
        return f"moved mouse to ({x},{y})"

    if name == "click":
        x, y = action.get("x"), action.get("y")
        button = action.get("button", "left")
        clicks = int(action.get("clicks", 1))
        interval = float(action.get("interval", 0.1))
        if x is not None and y is not None:
            pyautogui.click(int(x), int(y), clicks=clicks, interval=interval, button=button)
        else:
            pyautogui.click(clicks=clicks, interval=interval, button=button)
        return "clicked"

    if name == "type_text":
        text = action.get("text", "")
        interval = float(action.get("interval", 0.02))
        pyautogui.typewrite(text, interval=interval)
        return "typed text"

    if name == "hotkey":
        keys = action.get("keys", [])
        if not keys:
            raise ValueError("hotkey requires keys array")
        pyautogui.hotkey(*keys)
        return f"hotkey {keys}"

    if name in {"mcp_call","shell_exec","fs_read","fs_write","web_fetch"}:
        raise ValueError(f"{name} is executed by server executor")

    raise ValueError("unknown action")
