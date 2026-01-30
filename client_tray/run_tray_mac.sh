#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv || true
source .venv/bin/activate
pip install -r requirements.txt
python client_tray/tray.py
