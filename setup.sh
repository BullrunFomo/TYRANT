#!/usr/bin/env bash
# TYRANT//BOT — One-shot setup script
set -e

echo ""
echo "  ████████╗██╗   ██╗██████╗  █████╗ ███╗   ██╗████████╗"
echo "  ╚══██╔══╝╚██╗ ██╔╝██╔══██╗██╔══██╗████╗  ██║╚══██╔══╝"
echo "     ██║    ╚████╔╝ ██████╔╝███████║██╔██╗ ██║   ██║   "
echo "     ██║     ╚██╔╝  ██╔══██╗██╔══██║██║╚██╗██║   ██║   "
echo "     ██║      ██║   ██║  ██║██║  ██║██║ ╚████║   ██║   "
echo "     ╚═╝      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   "
echo ""
echo "  KnowYourMeme → pump.fun launcher  v1.0"
echo "────────────────────────────────────────────"
echo ""

python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "  [✓] Python $python_version"

if [ ! -d ".venv" ]; then
    echo "  [→] Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "  [✓] Virtual environment activated"

echo "  [→] Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "  [✓] Dependencies installed"

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
echo "  1. Edit .env — set SOLANA_PRIVATE_KEY + RPC URL"
echo "  2. Keep DRY_RUN=true (default) or SIMULATE=true to test safely"
echo "  3. Run: python -m pulse.web_main"
echo "  4. Open http://localhost:8000"
echo ""
