#!/usr/bin/env bash
# Schwab live pilot launcher (single-trade automation)
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_schwab_one_trade.sh [--port PORT] [--model MODEL] [--cadence MINUTES] [--one-trade|--multi-trade]

This script mirrors start_schwab_readonly.sh but enables trading automation with a
single-trade cap (DAI_MAX_TRADES=1). It refreshes Schwab tokens when necessary,
validates access, launches the streaming maintainer, and then runs the full
automation/dashboard stack in live mode.
USAGE
}

PORT=8081
MODEL="gpt-4o"
CADENCE=15

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/dai"
TOKEN_FILE="${PROJECT_ROOT}/schwab_tokens.json"

ENV_FILE="${PROJECT_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ENV_FILE}"
  set +a
fi

ONE_TRADE_MODE="${DAI_ONE_TRADE_MODE:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port|-p) PORT="$2"; shift 2 ;;
    --model|-m) MODEL="$2"; shift 2 ;;
    --cadence|-c) CADENCE="$2"; shift 2 ;;
    --one-trade) ONE_TRADE_MODE=1; shift ;;
    --multi-trade) ONE_TRADE_MODE=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

# --- venv bootstrap (copied from start_schwab_readonly.sh) ---
if [[ -n "${PYTHON_BIN:-}" ]]; then :; else
  for candidate in "/opt/homebrew/bin/python3.11" "/opt/homebrew/bin/python3.10" python3.11 python3.10 python3; do
    if [[ -x "${candidate}" && "${candidate}" == /* ]]; then
      PYTHON_BIN="${candidate}"; break
    elif command -v "${candidate}" >/dev/null 2>&1; then
      PYTHON_BIN="${candidate}"; break
    fi
  done
fi
if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "❌ Unable to locate a Python 3 interpreter (need >= 3.10)"; exit 1
fi

PY_VERSION="$(${PYTHON_BIN} -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
PY_MAJOR=$(echo "${PY_VERSION}" | cut -d. -f1)
PY_MINOR=$(echo "${PY_VERSION}" | cut -d. -f2)
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
  echo "❌ ${PYTHON_BIN} is Python ${PY_VERSION}. Install Python 3.10+."; exit 1
fi

RECREATE_VENV=0
if [[ ! -d "${VENV_DIR}" ]]; then
  RECREATE_VENV=1
elif [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  RECREATE_VENV=1
fi
if (( RECREATE_VENV )); then
  rm -rf "${VENV_DIR}"
  echo "📦 Creating virtualenv at ${VENV_DIR} ..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
  REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"
  REQUIREMENTS_STAMP="${VENV_DIR}/.requirements-stamp"
  if [[ ! -f "${REQUIREMENTS_STAMP}" || "${REQUIREMENTS_FILE}" -nt "${REQUIREMENTS_STAMP}" ]]; then
    pip install -q -r "${REQUIREMENTS_FILE}"
    touch "${REQUIREMENTS_STAMP}"
  fi
fi

# Export live-trading environment (same pattern as read-only script, but automation on)
export TRADING_MODE="real_world"
export DAI_SCHWAB_LIVE_VIEW=0
export DAI_SCHWAB_READONLY=0
export DAI_DISABLE_AUTOMATION=0
export DAI_SCHWAB_INTERACTIVE="${DAI_SCHWAB_INTERACTIVE:-0}"
export DAI_SCHWAB_MANUAL_FLOW="${DAI_SCHWAB_MANUAL_FLOW:-0}"
export DAI_MAX_TRADES="${DAI_MAX_TRADES:-1}"
export DAI_ONE_TRADE_MODE="${ONE_TRADE_MODE}"
export DAI_CADENCE_MINUTES="${CADENCE}"
export DAI_PORT="${PORT}"
export DAI_GPT_MODEL="${MODEL}"
export SCHWAB_TOKEN_FILE="${TOKEN_FILE}"

refresh_tokens() {
  echo "🔐 Refreshing Schwab tokens ..."
  rm -f "${TOKEN_FILE}"
  python "${PROJECT_ROOT}/schwab_manual_auth.py" --save
}

validate_tokens() {
  python - <<'PY'
import sys
from schwab_client import schwab_client

ok = schwab_client.authenticate()
if not ok:
    sys.exit(1)
try:
    response = schwab_client.client.get_account_numbers()
    status = getattr(response, "status_code", None)
    if status != 200:
        sys.exit(1)
    data = response.json()
    if not data:
        sys.exit(1)
except Exception:
    sys.exit(1)

sys.exit(0)
PY
}

REFRESH=1
if [[ -f "${TOKEN_FILE}" ]]; then
  AGE=$(( $(date +%s) - $(stat -f %m "${TOKEN_FILE}" 2>/dev/null || stat -c %Y "${TOKEN_FILE}") ))
  if (( AGE < 432000 )); then
    REFRESH=0
  fi
fi

if (( REFRESH )); then
  refresh_tokens
fi

if ! validate_tokens; then
  refresh_tokens
  if ! validate_tokens; then
    echo "❌ Unable to authenticate with Schwab after token refresh. Exiting." >&2
    exit 1
  fi
fi

cleanup() {
  if [[ -n "${STREAM_PID:-}" ]]; then
    kill "${STREAM_PID}" 2>/dev/null || true
  fi
  if [[ -n "${DASH_PID:-}" ]]; then
    kill "${DASH_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "▶️  Starting Schwab streaming helper ..."
python "${PROJECT_ROOT}/run_schwab_streaming.py" >/tmp/dai_schwab_stream.log 2>&1 &
STREAM_PID=$!
echo "   Logs: tail -f /tmp/dai_schwab_stream.log"

echo "========================================"
echo "Schwab Live Pilot (One-Buy Limit)"
echo "========================================"
echo "Port: ${PORT}"
echo "Model: ${MODEL}"
echo "Cadence: ${CADENCE} minutes"
echo "Max Trades: ${DAI_MAX_TRADES}"
echo "One-Trade Mode: $([[ "${DAI_ONE_TRADE_MODE}" == "1" ]] && echo ON || echo OFF)"
echo "========================================"

echo "🌐 Starting dashboard server on http://localhost:${PORT} ..."
FLASK_DEBUG=0 FLASK_ENV=production python "${PROJECT_ROOT}/dashboard_server.py" >/tmp/dai_dashboard.log 2>&1 &
DASH_PID=$!
echo "   Logs: tail -f /tmp/dai_dashboard.log"
echo "✅ Dashboard launched — you can open http://localhost:${PORT} now."

echo "Running single trading cycle (summaries ➜ decision ➜ trade)..."
python - <<'PY'
import sys

from config import set_trading_mode, get_trading_mode

# Ensure config reflects live trading mode for this run
set_trading_mode("real_world")

from schwab_client import schwab_client
from trading_interface import trading_interface
from d_ai_trader import DAITraderOrchestrator

mode = get_trading_mode()

# Keep legacy singletons aligned with the selected trading mode
trading_interface.trading_mode = mode
schwab_client.trading_mode = mode

if not trading_interface.schwab_enabled:
    print("🔁 Re-authenticating Schwab client for live trading...")
    trading_interface.schwab_enabled = schwab_client.authenticate()

if not trading_interface.schwab_enabled:
    print("❌ Unable to authenticate Schwab client for live trading", file=sys.stderr)
    sys.exit(1)

print("📡 Refreshing Schwab snapshot before trading cycle...")
snapshot = trading_interface.sync_schwab_positions(persist=True)
if snapshot.get("status") != "success":
    print(f"⚠️  Schwab sync before run failed: {snapshot.get('message') or snapshot.get('error')}")
else:
    print("✅ Schwab holdings synchronized for live baseline")

orchestrator = DAITraderOrchestrator()

print("📰 Running summarizer agents...")
orchestrator.run_summarizer_agents()

print("🤖 Running decider agent (single cycle)...")
orchestrator.run_decider_agent()

try:
    print("🔄 Syncing Schwab holdings for dashboard display...")
    trading_interface.sync_schwab_positions(persist=True)
except Exception as exc:
    print(f"⚠️  Schwab holdings sync failed: {exc}", file=sys.stderr)
PY

echo ""
echo "✅ Single trading cycle complete. Dashboard remains live at http://localhost:${PORT}"
echo "   Press Ctrl+C to stop streaming and the dashboard."

wait "${DASH_PID}"
