#!/usr/bin/env bash
# Launches d-ai-trader in live Schwab mode (single-buy pilot configuration)
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_live_trading.sh [--port PORT] [--model MODEL] [--cadence MINUTES] [--no-stream] [--stream] [--one-trade|--multi-trade]

This wrapper sets the environment for live Schwab execution and then delegates to
start_d_ai_trader.sh. Defaults are tuned for the initial pilot (single buy).

  --port       Dashboard port (default: 8080)
  --model      OpenAI model (default: gpt-4o)
  --cadence    Minutes between intraday runs (default: 15)
      --stream     Launch Schwab streaming helper (default: on)
      --no-stream  Disable streaming helper
  --one-trade    Enforce single live buy per cycle (default)
  --multi-trade  Allow multiple buys per cycle (disables safeguard)
  --help         Show this help
USAGE
}

PORT=8080
MODEL="gpt-4o"
CADENCE=15
ENABLE_STREAM=1

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/dai"

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
    -p|--port) PORT="$2"; shift 2 ;;
    -m|--model) MODEL="$2"; shift 2 ;;
    -c|--cadence) CADENCE="$2"; shift 2 ;;
    --stream) ENABLE_STREAM=1; shift ;;
    --no-stream) ENABLE_STREAM=0; shift ;;
    --one-trade) ONE_TRADE_MODE=1; shift ;;
    --multi-trade) ONE_TRADE_MODE=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
else
  for candidate in "/opt/homebrew/bin/python3.11" "/opt/homebrew/bin/python3.10" python3.11 python3.10 python3; do
    if [[ -x "${candidate}" && "${candidate}" == /* ]]; then
      PYTHON_BIN="${candidate}"
      break
    elif command -v "${candidate}" >/dev/null 2>&1; then
      PYTHON_BIN="${candidate}"
      break
    fi
  done
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "❌ Unable to locate a Python 3 interpreter (need >= 3.10)"
  exit 1
fi

if [[ -n "${CONDA_PREFIX:-}" ]]; then
  echo "⚠️  Detected active Conda environment (${CONDA_PREFIX}). Launch script will create its own venv using ${PYTHON_BIN}."
fi

PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
PY_MAJOR=$(echo "${PY_VERSION}" | cut -d. -f1)
PY_MINOR=$(echo "${PY_VERSION}" | cut -d. -f2)
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
  echo "❌ ${PYTHON_BIN} is Python ${PY_VERSION}. Please install Python 3.10+ (e.g., python3.10 or python3.11) and set PYTHON_BIN."
  exit 1
fi

RECREATE_VENV=0
if [[ ! -d "${VENV_DIR}" ]]; then
  RECREATE_VENV=1
elif [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  RECREATE_VENV=1
else
  VENV_VERSION="$("${VENV_DIR}/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
  VENV_MAJOR=$(echo "${VENV_VERSION}" | cut -d. -f1)
  VENV_MINOR=$(echo "${VENV_VERSION}" | cut -d. -f2)
  if (( VENV_MAJOR < 3 || (VENV_MAJOR == 3 && VENV_MINOR < 10) )); then
    echo "⚠️  Existing virtualenv uses Python ${VENV_VERSION}; rebuilding with ${PYTHON_BIN} ..."
    RECREATE_VENV=1
  fi
fi

if (( RECREATE_VENV )); then
  rm -rf "${VENV_DIR}"
  echo "📦 Creating virtualenv at ${VENV_DIR} using ${PYTHON_BIN} ..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
  REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"
  REQUIREMENTS_STAMP="${VENV_DIR}/.requirements-stamp"
  if [[ ! -f "${REQUIREMENTS_STAMP}" || "${REQUIREMENTS_FILE}" -nt "${REQUIREMENTS_STAMP}" ]]; then
    echo "📦 Installing dependencies from requirements.txt ..."
    pip install -q -r "${REQUIREMENTS_FILE}"
    touch "${REQUIREMENTS_STAMP}"
  fi
fi

export DAI_SCHWAB_LIVE_VIEW=0
export DAI_SCHWAB_READONLY=0
export DAI_DISABLE_AUTOMATION=0
export DAI_SCHWAB_INTERACTIVE="${DAI_SCHWAB_INTERACTIVE:-0}"
export DAI_SCHWAB_MANUAL_FLOW="${DAI_SCHWAB_MANUAL_FLOW:-0}"
export DAI_MAX_TRADES="${DAI_MAX_TRADES:-1}"
export DAI_ONE_TRADE_MODE="${ONE_TRADE_MODE}"
export DAI_CADENCE_MINUTES="${CADENCE}"
export TRADING_MODE="real_world"

echo "========================================"
echo "D-AI-Trader Live Pilot (One-Buy Limit)"
echo "========================================"
echo "Dashboard Port:    ${PORT}"
echo "AI Model:          ${MODEL}"
echo "Cadence:           Every ${CADENCE} minutes"
echo "Max Trades:        ${DAI_MAX_TRADES}"
echo "One-Trade Mode:    $([[ "${DAI_ONE_TRADE_MODE}" == "1" ]] && echo ON || echo OFF)"
echo "Schwab Mode:       LIVE (READ-ONLY=${DAI_SCHWAB_READONLY})"
if (( ENABLE_STREAM )); then
  echo "Streaming helper:  ENABLED (schwab_streaming.py)"
else
  echo "Streaming helper:  DISABLED"
fi
echo "========================================"
echo ""
echo "NOTE: Ensure market hours and Schwab credentials are ready."
if [[ "${DAI_ONE_TRADE_MODE}" == "1" ]]; then
  echo "      One-Trade Mode ON: at most one live buy per cycle."
else
  echo "      One-Trade Mode OFF: AI may execute multiple buys (respecting other limits)."
fi
echo ""

cleanup() {
  if [[ -n "${STREAM_PID:-}" ]]; then
    kill "${STREAM_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if (( ENABLE_STREAM )); then
  echo "▶️  Starting Schwab streaming helper (Level I quotes + account activity)..."
  SCRIPT_DIR="$(dirname "$0")"
  python "${SCRIPT_DIR}/run_schwab_streaming.py" >/tmp/dai_schwab_stream.log 2>&1 &
  STREAM_PID=$!
  echo "   Logs: tail -f /tmp/dai_schwab_stream.log"
fi

"$(dirname "$0")/start_d_ai_trader.sh" -p "${PORT}" -m "${MODEL}" -t real_world -c "${CADENCE}"
