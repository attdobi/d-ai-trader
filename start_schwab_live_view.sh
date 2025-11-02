#!/usr/bin/env bash
# Launch the dashboard in Schwab live-view-only mode (read-only, no trades)
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_schwab_live_view.sh [-p PORT] [--no-stream] [--stream]

  -p, --port   Dashboard port (default: 8080)
      --stream     Launch Schwab streaming helper (default: on)
      --no-stream  Disable streaming helper
  --help       Show this help message

This script starts the Flask dashboard with Schwab integration enabled in
read-only mode. No automation or trade execution is launched.
USAGE
}

PORT="${PORT:-8080}"
ENABLE_STREAM=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port) PORT="$2"; shift 2 ;;
    --stream) ENABLE_STREAM=1; shift ;;
    --no-stream) ENABLE_STREAM=0; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/dai"

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
  else
    echo "📦 Dependencies up to date (skipping pip install)"
  fi
fi

export DAI_PROJECT_ROOT="${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
export DAI_PORT="${PORT}"
# Force live mode for Schwab read-only view so API is enabled
export TRADING_MODE="live"
export DAI_SCHWAB_LIVE_VIEW=1
export DAI_SCHWAB_READONLY=1
export DAI_DISABLE_AUTOMATION=1
export DAI_GPT_MODEL="${DAI_GPT_MODEL:-gpt-4o}"
export DAI_DISABLE_UC="${DAI_DISABLE_UC:-1}"
export CURRENT_CONFIG_HASH="${CURRENT_CONFIG_HASH:-SCHWAB_LIVE_VIEW}"
# Ensure trading mode is lower-case for downstream imports
export TRADING_MODE="$(echo "${TRADING_MODE}" | tr '[:upper:]' '[:lower:]')"

echo "========================================"
echo "Schwab Live View (Read-Only)"
echo "========================================"
echo "Dashboard Port:    ${PORT}"
echo "Trading Mode:      ${TRADING_MODE} (automation disabled)"
echo "Schwab Mode:       READ-ONLY"
echo "Config Hash:       ${CURRENT_CONFIG_HASH}"
echo "========================================"
echo ""
echo "🌐 Dashboard URL: http://localhost:${PORT}"
echo ""
echo "🚫 No trades will be executed in this mode."
if (( ENABLE_STREAM )); then
  echo "🔄 Streaming:       ENABLED (schwab_streaming.py)"
else
  echo "🔄 Streaming:       DISABLED"
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
  python "${PROJECT_ROOT}/run_schwab_streaming.py" >/tmp/dai_schwab_stream.log 2>&1 &
  STREAM_PID=$!
  echo "   Logs: tail -f /tmp/dai_schwab_stream.log"
fi

python "${PROJECT_ROOT}/dashboard_server.py"
