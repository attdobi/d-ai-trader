#!/bin/bash

# D-AI-Trader Comprehensive Startup Script
# This script starts both the trading automation system and the dashboard

# Default values
DEFAULT_PORT=8080
DEFAULT_MODEL="gpt-4.1"
DEFAULT_PROMPT_VERSION="auto"
DEFAULT_TRADING_MODE="simulation"

# Function to display usage information
show_usage() {
    echo "Usage: ./start_d_ai_trader.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -p, --port PORT           Set dashboard port (default: $DEFAULT_PORT)"
    echo "  -m, --model MODEL         Set AI model (default: $DEFAULT_MODEL)"
    echo "                            Available: gpt-4.1, gpt-4.1-mini, o3, o3-mini, gpt-5, gpt-5-mini"
    echo "  -v, --prompt-version VER  Set prompt version (default: $DEFAULT_PROMPT_VERSION)"
    echo "                            Use 'auto' for latest prompts or specific version like 'v4'"
    echo "  -t, --trading-mode MODE   Set trading mode (default: $DEFAULT_TRADING_MODE)"
    echo "                            'simulation' for safe testing, 'real_world' for actual trades"
    echo "  -h, --help               Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./start_d_ai_trader.sh                                         # Use all defaults"
    echo "  ./start_d_ai_trader.sh -p 8081 -m o3 -v v4                    # Custom settings"
    echo "  ./start_d_ai_trader.sh --port 9000 --model gpt-5 -t real_world # Real trading"
    echo "  ./start_d_ai_trader.sh -m gpt-5-mini -v v3 -t simulation      # Performance test"
}

# Parse command line arguments
PORT=$DEFAULT_PORT
MODEL=$DEFAULT_MODEL
PROMPT_VERSION=$DEFAULT_PROMPT_VERSION
TRADING_MODE=$DEFAULT_TRADING_MODE

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -v|--prompt-version)
            PROMPT_VERSION="$2"
            shift 2
            ;;
        -t|--trading-mode)
            TRADING_MODE="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate port
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "Error: Invalid port number '$PORT'. Must be between 1 and 65535."
    exit 1
fi

# Validate model
VALID_MODELS=("gpt-4.1" "gpt-4.1-mini" "o3" "o3-mini" "gpt-5" "gpt-5-mini")
if [[ ! " ${VALID_MODELS[@]} " =~ " ${MODEL} " ]]; then
    echo "Error: Invalid model '$MODEL'."
    echo "Valid models are: ${VALID_MODELS[*]}"
    exit 1
fi

# Validate trading mode
VALID_TRADING_MODES=("simulation" "real_world")
if [[ ! " ${VALID_TRADING_MODES[@]} " =~ " ${TRADING_MODE} " ]]; then
    echo "Error: Invalid trading mode '$TRADING_MODE'."
    echo "Valid trading modes are: ${VALID_TRADING_MODES[*]}"
    exit 1
fi

# Display configuration
echo "========================================"
echo "D-AI-Trader Startup Configuration"
echo "========================================"
echo "Dashboard Port:    $PORT"
echo "AI Model:          $MODEL"
echo "Prompt Version:    $PROMPT_VERSION"
echo "Trading Mode:      $TRADING_MODE"
echo "========================================"

# Check if virtual environment exists
if [ ! -d "dai" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv dai
fi

# Activate virtual environment
echo "Activating virtual environment..."
source dai/bin/activate

# Install/upgrade dependencies
echo "Installing/upgrading dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Check if database is accessible
echo "Checking database connection..."
python -c "
from config import engine
from sqlalchemy import text
try:
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    print('✅ Database connection successful')
except Exception as e:
    print(f'❌ Database connection failed: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "Database connection failed. Please check your database configuration."
    exit 1
fi

# Create a startup Python script with the configuration
cat > startup_config.py << EOF
#!/usr/bin/env python3
"""
Startup configuration script for D-AI-Trader
This script configures the system with the provided parameters and starts both components
"""
import os
import sys
import threading
import time

def configure_and_start():
    """Configure the system with startup parameters and start components"""
    from config import config_manager

    # Configure system using the new streamlined configuration manager
    config_hash = config_manager.configure_from_startup_params(
        model="$MODEL",
        prompt_version="$PROMPT_VERSION",
        trading_mode="$TRADING_MODE"
    )

    print(f"   - Dashboard Port: $PORT")

    def start_dashboard():
        """Start the dashboard server"""
        print("🌐 Starting dashboard server...")

        # Import and configure dashboard
        import dashboard_server

        # Set the port for the dashboard
        dashboard_server.app.run(debug=False, port=$PORT, host='0.0.0.0', threaded=True)

    def start_automation():
        """Start the automation system"""
        print("🤖 Starting D-AI-Trader automation system...")

        # Small delay to let dashboard start first
        time.sleep(2)

        # Import and start the main automation system
        import d_ai_trader
        orchestrator = d_ai_trader.DAITraderOrchestrator()
        orchestrator.run()

    def main():
        """Main startup function"""
        print("🚀 Starting D-AI-Trader Comprehensive System...")

        try:
            # Start dashboard in a separate thread
            dashboard_thread = threading.Thread(target=start_dashboard, daemon=False)
            dashboard_thread.start()

            # Give dashboard time to start
            time.sleep(3)
            print(f"✅ Dashboard started on http://localhost:$PORT")

            # Start automation system in main thread
            start_automation()

        except KeyboardInterrupt:
            print("\n🛑 Shutting down D-AI-Trader system...")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Error starting system: {e}")
            sys.exit(1)

    if __name__ == "__main__":
        main()

configure_and_start()
EOF

# Make the startup config executable
chmod +x startup_config.py

echo ""
echo "🚀 Starting D-AI-Trader system..."
echo "📊 Dashboard will be available at: http://localhost:$PORT"
echo "🤖 Automation system will start after dashboard initialization"
echo ""
echo "Press Ctrl+C to stop the system"
echo ""

# Start the configured system
python startup_config.py

# Cleanup on exit
echo "🧹 Cleaning up temporary files..."
rm -f startup_config.py

echo "✅ D-AI-Trader system stopped."