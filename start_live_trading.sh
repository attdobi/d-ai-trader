#!/usr/bin/env bash
# Launches d-ai-trader in live Schwab mode (single-buy pilot configuration)
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_live_trading.sh [--port PORT] [--model MODEL] [--cadence MINUTES]

This wrapper sets the environment for live Schwab execution and then delegates to
start_d_ai_trader.sh. Defaults are tuned for the initial pilot (single buy).

  --port       Dashboard port (default: 8080)
  --model      OpenAI model (default: gpt-4o)
  --cadence    Minutes between intraday runs (default: 15)
  --help       Show this help
USAGE
}

PORT=8080
MODEL="gpt-4o"
CADENCE=15

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --cadence) CADENCE="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

export DAI_SCHWAB_LIVE_VIEW=0
export DAI_SCHWAB_READONLY=0
export DAI_DISABLE_AUTOMATION=0
export DAI_SCHWAB_INTERACTIVE="${DAI_SCHWAB_INTERACTIVE:-0}"
export DAI_SCHWAB_MANUAL_FLOW="${DAI_SCHWAB_MANUAL_FLOW:-0}"
export DAI_MAX_TRADES="${DAI_MAX_TRADES:-1}"
export DAI_CADENCE_MINUTES="${CADENCE}"

echo "========================================"
echo "D-AI-Trader Live Pilot (One-Buy Limit)"
echo "========================================"
echo "Dashboard Port:    ${PORT}"
echo "AI Model:          ${MODEL}"
echo "Cadence:           Every ${CADENCE} minutes"
echo "Max Trades:        ${DAI_MAX_TRADES}"
echo "Schwab Mode:       LIVE (READ-ONLY=${DAI_SCHWAB_READONLY})"
echo "========================================"
echo ""
echo "NOTE: Ensure market hours and Schwab credentials are ready."
echo "      The system will execute at most one buy decision per cycle."
echo ""

"$(dirname "$0")/start_d_ai_trader.sh" -p "${PORT}" -m "${MODEL}" -t live -c "${CADENCE}"
