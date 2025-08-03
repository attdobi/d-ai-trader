#!/bin/bash

# D-AI-Trader Startup Script

echo "Starting D-AI-Trader Automation System..."

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
python3 -c "
from config import engine
try:
    with engine.connect() as conn:
        conn.execute('SELECT 1')
    print('Database connection successful')
except Exception as e:
    print(f'Database connection failed: {e}')
    exit(1)
"

# Start the automation system
echo "Starting D-AI-Trader automation system..."
echo "Press Ctrl+C to stop"
python3 d-ai-trader.py 