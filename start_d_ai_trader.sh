#!/usr/bin/env bash
# Robust launcher for d-ai-trader (dashboard + automation)
# Usage:
#   ./start_d_ai_trader.sh -p 8080 -m gpt-4o-mini -v auto -t simulation
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_d_ai_trader.sh [-p PORT] [-m MODEL] [-v PROMPT_VERSION] [-t TRADING_MODE] [-c CADENCE]

  -p, --port            Dashboard port (default: 8080)
  -m, --model           AI model (default: gpt-4o)
                        RECOMMENDED (GPT-4 series):
                          • gpt-4o          - BEST for trading (reliable, fast)
                          • gpt-4o-mini     - Good for testing (cheap)
                          • gpt-4-turbo     - "GPT-4.1" equivalent (older)
                        
                        EXPERIMENTAL (GPT-5 reasoning models):
                          • gpt-5 / gpt-5-mini - ⚠️  May hit token limits
                            (Uses tokens for "thinking" - needs 8000+ tokens)
                            NOT recommended for production yet
                        
                        Note: o1/o3 models NOT supported
  -v, --prompt-version  Prompt version strategy: auto | vN (default: auto)
  -t, --trading-mode    simulation | real_world (default: simulation)
  -c, --cadence         How often to run (in minutes, default: 60)
                        Examples:
                          • 15  - Every 15 minutes (aggressive day trading)
                          • 30  - Every 30 minutes (active trading)
                          • 60  - Every hour (default, conservative)
  --help                Show this help

Tips:
  • To run Selenium with stock Chrome (recommended on macOS), keep UC disabled:
      export DAI_DISABLE_UC=1
  • For day trading, use: -c 15 (runs every 15 minutes during market hours)
USAGE
}

PORT=8080
MODEL="gpt-4o"
PROMPT_VERSION="auto"
TRADING_MODE="simulation"
CADENCE_MINUTES=60

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port) PORT="$2"; shift 2;;
    -m|--model) MODEL="$2"; shift 2;;
    -v|--prompt-version) PROMPT_VERSION="$2"; shift 2;;
    -t|--trading-mode) TRADING_MODE="$2"; shift 2;;
    -c|--cadence) CADENCE_MINUTES="$2"; shift 2;;
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
export DAI_CADENCE_MINUTES="${CADENCE_MINUTES}"

echo "========================================"
echo "D-AI-Trader Startup Configuration"
echo "========================================"
echo "Dashboard Port:    ${PORT}"
echo "AI Model:          ${MODEL}"
echo "Prompt Version:    ${PROMPT_VERSION}"
echo "Trading Mode:      ${TRADING_MODE}"
echo "Run Cadence:       Every ${CADENCE_MINUTES} minutes"
if [[ "${DAI_DISABLE_UC}" == "1" ]]; then
  echo "UC Shim:           DISABLED"
else
  echo "UC Shim:           ENABLED (DAI_ENABLE_UC=${DAI_ENABLE_UC:-0})"
fi
echo "========================================"
echo ""
echo "🌐 Dashboard URL: http://localhost:${PORT}"
echo ""
echo "📊 DAY TRADING SCHEDULE:"
echo "   🔔 Opening Bell: 6:25 AM PT (analyzes news, trades at 6:30:05 AM PT)"
echo "   📈 Intraday:     Every ${CADENCE_MINUTES} min (6:35 AM - 1:00 PM PT)"
echo "   📊 Feedback:     1:30 PM PT (daily performance analysis)"
echo ""

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