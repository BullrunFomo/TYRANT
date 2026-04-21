#!/usr/bin/env bash
# PULSE/NET — One-shot setup script
set -e

echo ""
echo "  ██████╗ ██╗   ██╗██╗     ███████╗███████╗"
echo "  ██╔══██╗██║   ██║██║     ██╔════╝██╔════╝"
echo "  ██████╔╝██║   ██║██║     ███████╗█████╗  "
echo "  ██╔═══╝ ██║   ██║██║     ╚════██║██╔══╝  "
echo "  ██║     ╚██████╔╝███████╗███████║███████╗"
echo "  ╚═╝      ╚═════╝ ╚══════╝╚══════╝╚══════╝"
echo ""
echo "  Weather Market Alpha Engine  v1.0"
echo "────────────────────────────────────────────"
echo ""

# Python version check
python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "  [✓] Python $python_version"

# Virtual environment
if [ ! -d ".venv" ]; then
    echo "  [→] Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "  [✓] Virtual environment activated"

# Install deps
echo "  [→] Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "  [✓] Dependencies installed"

# .env setup
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  [→] Created .env from template — EDIT IT before running!"
else
    echo "  [✓] .env already exists"
fi

echo ""
echo "────────────────────────────────────────────"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit .env — add your PRIVATE_KEY and API credentials"
echo "  2. Set DRY_RUN=true (default) to test without real money"
echo "  3. Run: python -m pulse.main"
echo ""
echo "  Keybindings (in dashboard):"
echo "  q = quit    r = reset circuit    c = clear logs    l = toggle live/dry"
echo ""
