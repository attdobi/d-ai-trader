#!/usr/bin/env python3
"""
Startup configuration script for D-AI-Trader
This script configures the system with the provided parameters and starts both components
"""
import os
import sys
import threading
import time
import subprocess

def configure_system():
    """Configure the system with startup parameters"""
    from config import set_gpt_model, set_prompt_version_mode
    
    # Set the AI model
    set_gpt_model("gpt-4.1")
    
    # Set prompt version configuration
    prompt_version = "auto"
    if prompt_version.lower() == "auto":
        set_prompt_version_mode("auto")
    else:
        set_prompt_version_mode("fixed", prompt_version)
    
    print(f"✅ System configured with:")
    print(f"   - AI Model: gpt-4.1")
    print(f"   - Prompt Version: auto")
    print(f"   - Dashboard Port: 8080")

def start_dashboard():
    """Start the dashboard server"""
    print("🌐 Starting dashboard server...")
    
    # Import and configure dashboard
    import dashboard_server
    
    # Set the port for the dashboard
    dashboard_server.app.run(debug=False, port=8080, host='0.0.0.0', threaded=True)

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
    
    # Configure the system
    configure_system()
    
    try:
        # Start dashboard in a separate thread
        dashboard_thread = threading.Thread(target=start_dashboard, daemon=False)
        dashboard_thread.start()
        
        # Give dashboard time to start
        time.sleep(3)
        print(f"✅ Dashboard started on http://localhost:8080")
        
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
