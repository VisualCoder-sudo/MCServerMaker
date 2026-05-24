#!/bin/bash
# ─────────────────────────────────────────────
#  MCServerMaker — Launcher Script (Linux)
#  Usage: ./run.sh
#  All code written by Funnystudios (VisualCoder-sudo) aka (CodeBuilder)
#  https://github.com/VisualCoder-sudo
# ─────────────────────────────────────────────

set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is not installed."
    exit 1
fi

# 1. Ensure python3-venv is available
if ! python3 -m venv --help &>/dev/null; then
    echo "↓ Attempting to install python3-venv..."
    sudo apt install -y python3-venv python3-full
fi

# 2. Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "↪ Creating virtual environment..."
    python3 -m venv venv
fi

# 3. Ensure pip is available in the venv
if ! ./venv/bin/python3 -m pip --version &>/dev/null; then
    echo "↓ Installing pip into virtual environment..."
    if ! python3 -m pip --version &>/dev/null; then
        sudo apt install -y python3-pip
    fi
    python3 -m pip install --upgrade pip setuptools wheel
    python3 -m pip install --upgrade --target ./venv/lib/python3.12/site-packages pip
fi

# 4. Install / update dependencies
echo "↓ Checking dependencies..."
./venv/bin/python3 -m pip install -q -r requirements.txt

# 5. Launch the app
echo "↪ Starting MCServerMaker..."
exec ./venv/bin/python3 main.py
