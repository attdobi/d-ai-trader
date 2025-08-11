# Setup Dependencies Guide

This guide explains how to set up the dependencies that are not included in the git repository to keep it lightweight.

## Required Dependencies

### 1. Virtual Environment
The `dai/` folder (virtual environment) is not included in the repository. It will be automatically created when you run:

```bash
./start_d_ai_trader.sh
```

This script will:
- Create a virtual environment in `dai/`
- Install all Python dependencies from `requirements.txt`
- Set up the complete environment

### 2. Chrome Driver
The Chrome driver files (`138/chromedriver` and similar) are automatically downloaded by `chromedriver-autoinstaller` when the system runs. No manual installation needed.

### 3. Screenshots and Test Data
- `screenshots/` - Generated during agent runs (not tracked in git)
- `tests/` - Generated test data (not tracked in git)

## What's Excluded from Git

The following large files/folders are excluded via `.gitignore`:

- **Virtual environment**: `dai/` (~370MB)
- **Chrome drivers**: `138/`, `chromedriver*` (~15MB)
- **Screenshots**: `screenshots/` (~186MB)
- **Test data**: `tests/` (~14MB)
- **Cache files**: `__pycache__/`, `*.pyc`
- **Log files**: `*.log`

## Setup Commands

```bash
# Clone the repository
git clone <your-repo-url>
cd d-ai-trader

# Run the setup script (creates virtual env and installs dependencies)
./start_d_ai_trader.sh

# Or manually:
python3 -m venv dai
source dai/bin/activate
pip install -r requirements.txt
```

## Environment Configuration

Copy `env_template.txt` to `.env` and configure your API keys:

```bash
cp env_template.txt .env
# Edit .env with your actual API keys and settings
```

The repository now stays lightweight while maintaining full functionality!
