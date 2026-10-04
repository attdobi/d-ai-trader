#!/usr/bin/env bash
# Robust launcher for d-ai-trader (dashboard + automation)
# Usage:
#   ./start_d_ai_trader.sh -p 8080 -m gpt-5.6-terra -t simulation
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: start_d_ai_trader.sh [-p PORT] [-m MODEL] [-t TRADING_MODE] [-c CADENCE] [-H HASH] [-s SEED] [-b HOST]

  -p, --port            Dashboard port (default: 8080)
  -m, --model           Global AI model (default: gpt-5.6-terra); the per-agent
                        DAI_MODEL_* keys in .env still decide each agent's model.
                        GPT-5.6 family (Aug 2026 — all vision-capable):
                          • gpt-5.6-sol   (alias: sol)   - flagship, $5/$30 per 1M
                          • gpt-5.6-terra (alias: terra) - mid tier, $2/$12 (default)
                          • gpt-5.6-luna  (alias: luna)  - budget, $0.20/$1.20
                          • bare "gpt-5.6" → Sol (matches OpenAI's alias)

                        GPT-5 reasoning models:
                          • gpt-5.5 / gpt-5.4 / gpt-5.2 / gpt-5.1 / gpt-5
                          • Append a reasoning-effort suffix to set the
                            effort for summarizer/decider/feedback agents:
                              -m gpt-5.5-low
                              -m gpt-5.5-med
                              -m gpt-5.6-sol-high
                              -m gpt-5.6-terra-xhigh
                              -m gpt-5.6-sol-max   (max: GPT-5.6 only)

                        Older models (gpt-4o, gpt-4o-mini, gpt-4.1) are still accepted.
                        Note: o1/o3 models NOT supported
  -t, --trading-mode    simulation | real_world (default: simulation)
  -c, --cadence         Minutes between cycles after the 9:30 AM ET bell, weekdays until
                        5:25 PM ET (default: 180)
                        Examples:
                          • 180 - Every 3 hours (default, swing/settled funds pacing)
                          • 120 - Every 2 hours (the live run)
                          • 60  - Every hour (active monitoring)
  -H, --config-hash     Force a specific configuration hash for this run
  -b, --bind            Dashboard bind address (default: 0.0.0.0 = reachable from the local
                        network at http://<this-mac's-IP>:PORT; use 127.0.0.1 for local-only)
  -s, --policy-seed     Where a NEW config's v0 policy comes from (default: default)
                          • default - the code defaults (agents/*/policy-graph/baseline/v0)
                          • latest  - the shipped active policy graph
                                      (agents/*/policy-graph/latest, the version the repo
                                      was pushed with — start from the learned rules)
                        Only applies the first time a config hash is seeded.
  -v, -P                Deprecated: still accept a value, which is ignored (the active
                        prompt version comes from the database and the Policy Graph tab)
  --help                Show this help

Schedule (ET): market-open cycle at the 9:30 bell (trades at 9:30:05), then every
CADENCE minutes until 5:25 PM on weekdays (decisions after 4:00 PM are recorded,
not executed); weekly feedback Thursday 8:30 PM.
USAGE
}

PORT=8080
MODEL="gpt-5.6-terra"
TRADING_MODE="${TRADING_MODE:-simulation}"
CADENCE_MINUTES=180
CONFIG_HASH_OVERRIDE=""
POLICY_SEED="${DAI_POLICY_SEED:-default}"
BIND_HOST="${DAI_BIND_HOST:-0.0.0.0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port) PORT="$2"; shift 2;;
    -m|--model) MODEL="$2"; shift 2;;
    -v|--prompt-version) echo "⚠️  $1 is deprecated and ignored (the active prompt version comes from the database)"; shift 2;;
    -t|--trading-mode) TRADING_MODE="$2"; shift 2;;
    -c|--cadence) CADENCE_MINUTES="$2"; shift 2;;
    -P|--prompt-profile) echo "⚠️  $1 is deprecated and ignored (no code reads a prompt profile)"; shift 2;;
    -H|--config-hash) CONFIG_HASH_OVERRIDE="$2"; shift 2;;
    -s|--policy-seed) POLICY_SEED="$2"; shift 2;;
    -b|--bind) BIND_HOST="$2"; shift 2;;
    --help|-h) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 1;;
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

# Create venv if missing or wrong interpreter
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

# Activate venv
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

# Ensure dependencies (only when requirements.txt changes)
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

# Export runtime env
export DAI_PROJECT_ROOT="${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
# Normalize trading mode to lower-case for downstream imports
export TRADING_MODE="$(echo "${TRADING_MODE}" | tr '[:upper:]' '[:lower:]')"
# Propagate config to the app
export DAI_PORT="${PORT}"
export DAI_GPT_MODEL="${MODEL}"
export DAI_POLICY_SEED="${POLICY_SEED}"
export DAI_BIND_HOST="${BIND_HOST}"
export TRADING_MODE="${TRADING_MODE}"
export DAI_CADENCE_MINUTES="${CADENCE_MINUTES}"
if [[ -n "${CONFIG_HASH_OVERRIDE}" ]]; then
  export CURRENT_CONFIG_HASH="${CONFIG_HASH_OVERRIDE}"
fi

echo "========================================"
echo "D-AI-Trader Startup Configuration"
echo "========================================"
echo "Dashboard Port:    ${PORT}"
echo "AI Model:          ${MODEL}"
echo "Trading Mode:      ${TRADING_MODE}"
echo "Run Cadence:       Every ${CADENCE_MINUTES} minutes"
if [[ -n "${CONFIG_HASH_OVERRIDE}" ]]; then
  echo "Config Hash:       ${CONFIG_HASH_OVERRIDE} (forced override)"
fi
echo "========================================"
echo ""
echo "🌐 Dashboard URL: http://localhost:${PORT}"
echo ""
echo "📊 SCHEDULE (weekdays, ET; PT is 3 hours earlier):"
echo "   🔔 Opening bell: 9:30 AM ET (summarizes the news, trades at 9:30:05)"
echo "   📈 Cadence:      every ${CADENCE_MINUTES} min after the bell until 5:25 PM ET (after 4:00 PM decisions are recorded, not executed)"
echo "   📊 Feedback:     weekly, Thursday 8:30 PM ET"
echo ""

# Free the dashboard port and the Schwab redirect port (if local) before launch
cleanup_port() {
  local port="$1"
  if [[ -z "${port}" ]]; then
    return
  fi
  if ! command -v lsof >/dev/null 2>&1; then
    echo "⚠️  lsof not available; skipping port cleanup for ${port}"
    return
  fi
  local pids
  # shellcheck disable=SC2207
  pids=($(lsof -ti tcp:"${port}" || true))
  if (( ${#pids[@]} )); then
    echo "🧹 Freeing port ${port} (found ${#pids[@]} process(es))..."
    for pid in "${pids[@]}"; do
      if [[ "${pid}" =~ ^[0-9]+$ ]]; then
        kill "${pid}" 2>/dev/null || true
      fi
    done
    sleep 1
  else
    echo "✅ Port ${port} already free."
  fi
}

resolve_redirect_port() {
  local uri="${SCHWAB_REDIRECT_URI:-https://127.0.0.1:5556/callback}"
  # Only handle local redirects
  if [[ "${uri}" =~ ^https?://(127\.0\.0\.1|localhost)(:([0-9]+))? ]]; then
    local port="${BASH_REMATCH[3]}"
    if [[ -z "${port}" ]]; then
      # Default if omitted: keep legacy default
      port="5556"
    fi
    echo "${port}"
  else
    echo ""
  fi
}

# Ensure requested port is free before launching
echo "🧹 Ensuring port ${PORT} is free ..."
cleanup_port "${PORT}"

redirect_port="$(resolve_redirect_port)"
if [[ -n "${redirect_port}" ]]; then
  echo "🧹 Ensuring Schwab redirect port ${redirect_port} is free ..."
  cleanup_port "${redirect_port}"
fi

echo "🗄️ Initializing database schema ..."
python "${PROJECT_ROOT}/init_database.py"

# Start the dashboard and automation concurrently.
# Avoid passing CLI flags that may not exist in your local files;
# rely on exported env vars which your code already reads.
python "${PROJECT_ROOT}/dashboard_server.py" &
DASH_PID=$!

python "${PROJECT_ROOT}/d_ai_trader.py" &
AUTO_PID=$!

# Keep macOS awake (no idle sleep / App Nap throttling) for as long as the trader
# runs, so the 9:30 ET market-open job and cadence timers fire on schedule instead
# of drifting (App Nap was the likely cause of a ~15-min late open on 2026-06-29).
caffeinate -is -w ${AUTO_PID} &
CAFFEINATE_PID=$!

trap 'echo; echo "🛑 Stopping..."; kill ${DASH_PID} ${AUTO_PID} ${CAFFEINATE_PID} 2>/dev/null || true' EXIT

echo "🚀 Processes started: dashboard=${DASH_PID} automation=${AUTO_PID}"
wait
