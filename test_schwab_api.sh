#!/usr/bin/env bash
# Safe Schwab API Read-Only Test
# This script ONLY reads account data - NO TRADES will be executed
#
# Usage:
#   ./test_schwab_api.sh
#
# This will:
# - Connect to Schwab API (read-only)
# - Display account balance and holdings on Schwab tab
# - NOT execute any trades (safety locked)

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/dai"

# Create venv if missing
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "📦 Creating virtualenv at ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
fi

# Activate venv
source "${VENV_DIR}/bin/activate"

# Ensure dependencies
if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
  pip install -q -r "${PROJECT_ROOT}/requirements.txt"
fi

# Export runtime env
export DAI_PROJECT_ROOT="${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
export DAI_PORT="8080"

# CRITICAL SAFETY FLAGS
export TRADING_MODE="simulation"           # Force simulation mode
export DAI_SCHWAB_READONLY="1"            # Read-only flag (NO TRADES)
export DAI_DISABLE_UC="1"

echo "========================================"
echo "🔒 SCHWAB API READ-ONLY TEST MODE"
echo "========================================"
echo "Port:              8080"
echo "Trading Mode:      SIMULATION (safety locked)"
echo "Schwab Access:     READ-ONLY (no trades)"
echo ""
echo "⚠️  SAFETY FEATURES ENABLED:"
echo "   ✅ Trading mode forced to 'simulation'"
echo "   ✅ DAI_SCHWAB_READONLY=1 (prevents all trades)"
echo "   ✅ No automation running (dashboard only)"
echo "========================================"
echo ""
echo "🌐 Dashboard URL: http://localhost:8080"
echo ""
echo "📋 NEXT STEPS:"
echo "   1. Open http://localhost:8080/schwab"
echo "   2. Verify account balance matches your Schwab account"
echo "   3. Verify holdings are correct"
echo "   4. If everything looks good, you can enable live trading"
echo ""
echo "⚠️  This script ONLY runs the dashboard - NO trading automation"
echo "⚠️  NO TRADES will be executed under any circumstances"
echo ""

# Start ONLY the dashboard (no automation)
python "${PROJECT_ROOT}/dashboard_server.py"

