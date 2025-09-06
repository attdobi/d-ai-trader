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
        model="gpt-5-mini",
        prompt_version="v0",
        trading_mode="simulation"
    )

    print(f"   - Dashboard Port: 8083")

    def start_dashboard():
        """Start the dashboard server"""
        print("🌐 Starting dashboard server...")

        # Import and configure dashboard
        import dashboard_server

        # Set the port for the dashboard
        dashboard_server.app.run(debug=False, port=8083, host='0.0.0.0', threaded=True)

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
            print(f"✅ Dashboard started on http://localhost:8083")

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
