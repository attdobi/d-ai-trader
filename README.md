# AI-Powered Trading System with Profit Tracking

An intelligent trading system that uses AI agents to analyze financial news from multiple sources, make trading decisions, and track portfolio performance with comprehensive profit/loss monitoring.

## 🚀 Features

### Core Trading System
- **Multi-Source News Analysis**: Scrapes financial news from CNN Money, CNBC, Bloomberg, Fox Business, and Yahoo Finance
- **AI-Powered Decision Making**: Uses OpenAI GPT-4 to analyze news sentiment and generate trading recommendations
- **Automated Trade Execution**: Executes buy/sell decisions based on AI analysis
- **Real-Time Price Updates**: Automatically updates stock prices and portfolio values

### Advanced Profit Tracking
- **Cumulative Gain/Loss Tracking**: Properly tracks profits/losses across multiple trades of the same stock
- **Portfolio Performance Metrics**: Real-time calculation of total P&L, percentage gains, and portfolio value
- **Historical Performance**: Time-series tracking of portfolio performance over time
- **Visual Analytics**: Interactive charts showing profit/loss trends and portfolio evolution

### Dashboard & Visualization
- **Real-Time Dashboard**: Web interface displaying current holdings, cash balance, and performance metrics
- **Interactive Charts**: Portfolio value and profit/loss visualization over time
- **Trade History**: Complete record of all trading decisions and their outcomes
- **News Summaries**: Display of analyzed financial news that influenced trading decisions
- **Feedback Dashboard**: AI-powered performance analysis and agent improvement insights

### 🧠 AI Feedback & Learning System
- **Outcome Tracking**: Automatically records and categorizes trade results (significant profit, moderate profit, break-even, moderate loss, significant loss)
- **Performance Analysis**: AI-powered analysis of trading patterns and success factors
- **Agent Improvement**: Dynamic feedback to summarizer and decider agents based on trading performance
- **Continuous Learning**: System improves over time by learning from both successful and unsuccessful trades
- **Pattern Recognition**: Identifies what news patterns and trading strategies work best

## 📁 Project Structure

```
├── main.py                    # News scraping and AI analysis
├── decider_agent.py           # Trading decision engine
├── feedback_agent.py          # AI feedback and learning system
├── dashboard_server.py        # Web dashboard and API endpoints
├── config.py                  # Database configuration and AI setup
├── run_feedback_analysis.py   # Manual feedback analysis tool
├── test_feedback_system.py    # Feedback system demonstration
├── FEEDBACK_SYSTEM.md         # Comprehensive feedback system documentation
├── templates/                 # HTML templates for web interface
│   ├── dashboard.html         # Main dashboard with profit tracking
│   ├── feedback_dashboard.html # AI feedback and performance analysis
│   ├── trades.html            # Trading history view
│   ├── summaries.html         # News analysis summaries
│   └── tabs.html              # Base template
└── screenshots/               # Captured screenshots from news sites
```

## ⚡ Quick Start

Want to see the feedback system in action? Run this demo (no setup required):
```bash
python3 test_feedback_system.py
```

## 🔧 Installation & Setup

### Prerequisites
- Python 3.8+
- PostgreSQL
- Chrome/Chromium browser (for web scraping)

### Database Setup
```bash
# Install PostgreSQL
sudo apt update && sudo apt install postgresql postgresql-contrib

# Start PostgreSQL service
sudo service postgresql start

# Create database and user
sudo -u postgres createuser -s adobi
sudo -u postgres createdb adobi
```

### Python Dependencies
```bash
pip install sqlalchemy psycopg2-binary flask yfinance pandas python-dotenv openai selenium undetected-chromedriver beautifulsoup4 chromedriver-autoinstaller
```

### Configuration
1. Set your OpenAI API key in `config.py`
2. Ensure database connection string is correct: `postgresql://adobi@localhost/adobi`

## 🎯 Usage

### Complete Trading Workflow

#### Step 1: Collect Financial News
```bash
python3 main.py
```
- Scrapes financial news from 5 major sources (CNN, CNBC, Bloomberg, Fox Business, Yahoo Finance)
- Uses AI to analyze sentiment and extract trading insights
- Stores analysis in database for decision making

#### Step 2: Make Trading Decisions 
```bash
python3 decider_agent.py
```
- Analyzes latest news summaries
- **Uses previous feedback** to improve decisions automatically
- Generates buy/sell recommendations using AI
- Executes trades and updates portfolio
- **Automatically records sell outcomes** for feedback system
- Records portfolio snapshots for performance tracking

#### Step 3: Start Dashboard (One Time Setup)
```bash
python3 dashboard_server.py
```
- Starts web dashboard at `http://localhost:8080`
- Access main dashboard at: `http://localhost:8080`
- Access feedback analysis at: `http://localhost:8080/feedback`

#### Repeat Steps 1-2 for Continuous Trading
The system automatically:
- ✅ Records trade outcomes
- ✅ Analyzes performance patterns  
- ✅ Generates AI feedback
- ✅ Improves future decisions

### 4. View Feedback & Performance Analysis

#### Option A: Web Dashboard (Recommended)
```bash
# Start the dashboard server (if not already running)
python3 dashboard_server.py

# Then visit: http://localhost:8080/feedback
```

#### Option B: Command Line Analysis
```bash
# Run comprehensive feedback analysis in terminal
python3 run_feedback_analysis.py

# Demonstrate feedback system with sample data
python3 test_feedback_system.py
```

#### What the Feedback System Provides:
- 📊 **Success Rate Analysis**: Percentage of profitable trades over different time periods
- 📈 **Performance Trends**: Charts showing improvement over time
- 🎯 **AI Insights**: Specific recommendations for improving trading strategy
- 🔍 **Pattern Recognition**: What news patterns lead to successful trades
- 📝 **Agent Guidance**: Automatic feedback to improve future decisions

> **Note**: The feedback system works automatically! Every time you run trading decisions (`decider_agent.py`), outcomes are recorded and analyzed. The agents automatically learn and improve from this data.

## 🔄 How to Generate and View Feedback

### Automatic Feedback (Recommended)
The feedback system runs automatically when you execute normal trading:

1. **Generate Trading Data**: Run `python3 main.py` then `python3 decider_agent.py` multiple times
2. **View Feedback**: Visit `http://localhost:8080/feedback` in your browser

### Manual Feedback Analysis
Force feedback analysis at any time:
```bash
# Analyze recent trading performance
python3 run_feedback_analysis.py
```

### Demo Mode (No Database Required)
See how the feedback system works with sample data:
```bash
# Run interactive demonstration
python3 test_feedback_system.py
```

### What Triggers Feedback Generation?
- ✅ **Sell Transactions**: Every sell automatically records outcome
- ✅ **Periodic Analysis**: 30% chance of running analysis each trading cycle
- ✅ **Manual Analysis**: Run `run_feedback_analysis.py` anytime
- ✅ **Dashboard Access**: Real-time feedback available at `/feedback` endpoint

## 📊 Dashboard Features

### Portfolio Overview
- **Total Portfolio Value**: Current market value of all holdings + cash
- **Cash Balance**: Available cash for trading
- **Total Invested**: Cumulative amount invested across all trades
- **Total P&L**: Unrealized gains/losses with percentage change

### Holdings Table
- Individual stock positions with shares, purchase price, current price
- Gain/loss per holding with color-coded indicators
- Reasoning behind each purchase decision

### Interactive Charts
1. **Account Value Over Time**: Portfolio value progression
2. **Profit/Loss Chart**: Dual-axis chart showing:
   - Dollar gains/losses (left axis)
   - Percentage gains (right axis)
   - Color-coded gains (green) and losses (red)

### API Endpoints
- `/api/holdings` - Current portfolio holdings
- `/api/portfolio-history` - Historical portfolio performance
- `/api/profit-loss` - Profit/loss breakdown by holding
- `/api/history` - Account value history
- `/api/feedback` - Feedback analysis and performance metrics
- `/api/trade_outcomes` - Recent trade outcomes and categorization

### 🧠 Feedback Dashboard Features
- **Performance Metrics**: Success rate, average profit, trade count across different time periods (7d, 14d, 30d)
- **AI Insights**: Generated recommendations for improving trading strategy and news analysis
- **Trade Outcomes Table**: Color-coded table of recent trades categorized by performance level
- **Agent Feedback**: Specific guidance for summarizer and decider agents based on trading results
- **Trend Analysis**: Interactive charts showing performance trends with success rates and profit margins
- **System Status**: Real-time indicators of feedback system components

## 🧠 AI Analysis Process

### News Analysis
1. **Web Scraping**: Captures screenshots and HTML from financial news sites
2. **AI Processing**: GPT-4 analyzes both visual and text content
3. **Sentiment Extraction**: Identifies market sentiment and actionable insights
4. **Summary Generation**: Creates structured summaries with headlines and insights

### Trading Decisions
1. **Data Aggregation**: Combines all news analysis from current run
2. **Portfolio Context**: Considers current holdings and cash balance
3. **Risk Management**: Enforces position limits and cash reserves
4. **Decision Generation**: AI creates specific buy/sell recommendations with reasoning

## 💰 Profit Tracking Implementation

### Cumulative Gain/Loss Logic
The system properly tracks profits/losses across multiple trades:

```python
# For multiple purchases of same stock:
new_shares = existing_shares + additional_shares
new_total_invested = existing_investment + new_purchase_amount
new_avg_price = new_total_invested / new_shares
unrealized_pnl = (new_shares × current_price) - new_total_invested
```

### Portfolio Metrics
- **Total Invested**: Sum of all purchase amounts (cost basis)
- **Current Value**: Market value of all holdings
- **Unrealized P&L**: Difference between current value and total invested
- **Percentage Gain**: (Unrealized P&L / Total Invested) × 100

### Historical Tracking
Portfolio snapshots are automatically recorded:
- After each trading session
- During price updates
- Stored with timestamp for trend analysis

## 🔒 Risk Management

### Trading Limits
- **Maximum Funds**: $10,000 total allocation
- **Cash Reserve**: Always maintain $100 minimum
- **Position Limits**: Maximum 5 active trades
- **Whole Shares**: Only trades whole share quantities

### Error Handling
- Graceful handling of API failures
- Retry logic for network issues
- Fallback mechanisms for price data
- Comprehensive logging for debugging

## 📈 Performance Analytics

### Real-Time Metrics
- Live portfolio valuation
- Instant profit/loss calculations
- Performance percentage tracking
- Individual holding analytics

### Historical Analysis
- Time-series portfolio performance
- Trade decision outcomes
- News impact correlation
- Trend identification

## 🛠️ Technical Architecture

### Database Schema
- **holdings**: Current portfolio positions with cumulative tracking
- **portfolio_history**: Time-series portfolio snapshots
- **trade_decisions**: AI trading recommendations and outcomes
- **summaries**: Financial news analysis and insights

### Technology Stack
- **Backend**: Python, SQLAlchemy, PostgreSQL
- **Frontend**: Flask, Chart.js, HTML/CSS/JavaScript
- **AI**: OpenAI GPT-4 for analysis and decision making
- **Data**: yfinance for market data, Selenium for web scraping

### Security & Authentication
- PostgreSQL peer authentication
- Secure API key management
- Input validation and SQL injection prevention

## 📝 Configuration Options

### Trading Parameters
```python
MAX_TRADES = 5          # Maximum concurrent positions
MAX_FUNDS = 10000       # Total available capital
MIN_BUFFER = 100        # Minimum cash reserve
```

### Update Intervals
```python
REFRESH_INTERVAL_MINUTES = 10  # Price update frequency
```

## 🚨 Important Notes

1. **Educational Purpose**: This system is for educational and research purposes
2. **Risk Warning**: Trading involves financial risk - use with caution
3. **API Costs**: Monitor OpenAI API usage to control costs
4. **Market Hours**: Consider market hours for price updates
5. **Demo Mode**: Test with small amounts before full deployment

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Add tests for new functionality
5. Submit a pull request

## 📄 License

This project is for educational purposes. Please ensure compliance with relevant financial regulations and API terms of service.

## 🔗 Dependencies

- **SQLAlchemy**: Database ORM
- **Flask**: Web framework
- **yfinance**: Stock market data
- **OpenAI**: AI analysis
- **Selenium**: Web scraping
- **Chart.js**: Data visualization
- **PostgreSQL**: Database storage

---

**⚠️ Disclaimer**: This software is for educational purposes only. Trading involves significant financial risk. Always do your own research and consider consulting with financial professionals before making investment decisions.