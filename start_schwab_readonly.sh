#!/usr/bin/env bash
# Combined bootstrap + token refresh + live-view launcher for Schwab read-only mode
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_schwab_readonly.sh [-p PORT]

This script ensures the virtual environment is ready, refreshes Schwab tokens if
needed, runs the streaming/polling helper, and launches the dashboard in
read-only mode.
USAGE
}

PORT=8080
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port) PORT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/dai"
TOKEN_FILE="${PROJECT_ROOT}/schwab_tokens.json"

# --- venv bootstrap (same as start_schwab_live_view) ---
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

# --- token check ---
# --- helper functions ---
refresh_tokens() {
  echo "🔐 Refreshing Schwab tokens ..."
  rm -f "${TOKEN_FILE}"
  python "${PROJECT_ROOT}/schwab_manual_auth.py" --save
}

validate_tokens() {
  python - <<'PY'
import sys
from schwab_client import schwab_client
import json

ok = schwab_client.authenticate()
if not ok:
    sys.exit(1)

try:
    response = schwab_client.client.get_account_numbers()
    status = getattr(response, "status_code", None)
    if status != 200:
        print(f"Schwab get_account_numbers failed (status={status})")
        sys.exit(1)
    data = response.json()
    if not data:
        print("Schwab get_account_numbers returned empty payload")
        sys.exit(1)
except Exception as exc:
    print(f"Schwab validation error: {exc}")
    sys.exit(1)

sys.exit(0)
PY
}

# --- token check ---
REFRESH=1
if [[ -f "${TOKEN_FILE}" ]]; then
  AGE=$(( $(date +%s) - $(stat -f %m "${TOKEN_FILE}" 2>/dev/null || stat -c %Y "${TOKEN_FILE}") ))
  if (( AGE < 432000 )); then  # 5 days
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

# --- start streaming helper ---
cleanup() {
  if [[ -n "${STREAM_PID:-}" ]]; then
    kill "${STREAM_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "▶️  Starting Schwab streaming helper ..."
python "${PROJECT_ROOT}/run_schwab_streaming.py" >/tmp/dai_schwab_stream.log 2>&1 &
STREAM_PID=$!
echo "   Logs: tail -f /tmp/dai_schwab_stream.log"

# --- launch dashboard read-only ---
export TRADING_MODE="real_world"
export DAI_SCHWAB_LIVE_VIEW=1
export DAI_SCHWAB_READONLY=1
export DAI_DISABLE_AUTOMATION=1
export DAI_PORT="${PORT}"
export SCHWAB_TOKEN_FILE="${TOKEN_FILE}"

echo "========================================"
echo "Schwab Read-Only Dashboard"
echo "========================================"
echo "Port: ${PORT}"
echo "========================================"

python "${PROJECT_ROOT}/dashboard_server.py"
