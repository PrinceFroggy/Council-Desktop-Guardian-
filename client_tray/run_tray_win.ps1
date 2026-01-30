Set-Location (Split-Path $MyInvocation.MyCommand.Path) | Out-Null
Set-Location ".." | Out-Null

py -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py client_tray\tray.py
