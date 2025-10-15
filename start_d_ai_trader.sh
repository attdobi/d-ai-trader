#!/usr/bin/env bash
# Robust launcher for d-ai-trader (dashboard + automation)
# Usage:
#   ./start_d_ai_trader.sh -p 8080 -m gpt-4o-mini -v auto -t simulation
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_d_ai_trader.sh [-p PORT] [-m MODEL] [-v PROMPT_VERSION] [-t TRADING_MODE]

  -p, --port            Dashboard port (default: 8080)
  -m, --model           AI model (default: gpt-4o-mini)
                        Trading models (support system messages + JSON):
                          • gpt-4o          - Best for real money (most capable)
                          • gpt-4o-mini     - Fast & cheap (good for testing)
                          • gpt-4-turbo     - "GPT-4.1" equivalent (older)
                          • gpt-4           - Original GPT-4
                        Note: o1/o3 reasoning models NOT supported
  -v, --prompt-version  Prompt version strategy: auto | vN (default: auto)
  -t, --trading-mode    simulation | real_world (default: simulation)
  --help                Show this help

Tips:
  • To run Selenium with stock Chrome (recommended on macOS), keep UC disabled:
      export DAI_DISABLE_UC=1
  • Ensure repo root is on PYTHONPATH:
      export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
USAGE
}

PORT=8080
MODEL="gpt-4o-mini"
PROMPT_VERSION="auto"
TRADING_MODE="simulation"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port) PORT="$2"; shift 2;;
    -m|--model) MODEL="$2"; shift 2;;
    -v|--prompt-version) PROMPT_VERSION="$2"; shift 2;;
    -t|--trading-mode) TRADING_MODE="$2"; shift 2;;
    --help|-h) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENV_DIR="${PROJECT_ROOT}/dai"

# Create venv if missing
if [[ ! -d "${VENV_DIR}" ]]; then
  echo "📦 Creating virtualenv at ${VENV_DIR} ..."
  python3 -m venv "${VENV_DIR}"
fi

# Activate venv
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

# Ensure dependencies
if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
  pip install -q -r "${PROJECT_ROOT}/requirements.txt"
fi

# Export runtime env
export DAI_PROJECT_ROOT="${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
# Default: disable UC to use Selenium Manager (stable on macOS)
export DAI_DISABLE_UC="${DAI_DISABLE_UC:-1}"
# Propagate config to the app
export DAI_PORT="${PORT}"
export DAI_GPT_MODEL="${MODEL}"
export DAI_PROMPT_VERSION="${PROMPT_VERSION}"
export TRADING_MODE="${TRADING_MODE}"

echo "========================================"
echo "D-AI-Trader Startup Configuration"
echo "========================================"
echo "Dashboard Port:    ${PORT}"
echo "AI Model:          ${MODEL}"
echo "Prompt Version:    ${PROMPT_VERSION}"
echo "Trading Mode:      ${TRADING_MODE}"
if [[ "${DAI_DISABLE_UC}" == "1" ]]; then
  echo "UC Shim:           DISABLED"
else
  echo "UC Shim:           ENABLED (DAI_ENABLE_UC=${DAI_ENABLE_UC:-0})"
fi
echo "========================================"

# Start the dashboard and automation concurrently.
# Avoid passing CLI flags that may not exist in your local files;
# rely on exported env vars which your code already reads.
python "${PROJECT_ROOT}/dashboard_server.py" &
DASH_PID=$!

python "${PROJECT_ROOT}/d_ai_trader.py" &
AUTO_PID=$!

trap 'echo; echo "🛑 Stopping..."; kill ${DASH_PID} ${AUTO_PID} 2>/dev/null || true' EXIT

echo "🚀 Processes started: dashboard=${DASH_PID} automation=${AUTO_PID}"
wait