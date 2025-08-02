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

## 📁 Project Structure

```
├── main.py                 # News scraping and AI analysis
├── decider_agent.py        # Trading decision engine
├── dashboard_server.py     # Web dashboard and API endpoints
├── config.py              # Database configuration and AI setup
├── templates/             # HTML templates for web interface
│   ├── dashboard.html     # Main dashboard with profit tracking
│   ├── trades.html        # Trading history view
│   ├── summaries.html     # News analysis summaries
│   └── tabs.html          # Base template
└── screenshots/           # Captured screenshots from news sites
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

### 1. Collect Financial News
```bash
python3 main.py
```
- Scrapes financial news from 5 major sources
- Uses AI to analyze sentiment and extract trading insights
- Stores analysis in database for decision making

### 2. Make Trading Decisions
```bash
python3 decider_agent.py
```
- Analyzes latest news summaries
- Generates buy/sell recommendations using AI
- Executes trades and updates portfolio
- Records portfolio snapshots for performance tracking

### 3. Monitor Performance
```bash
python3 dashboard_server.py
```
- Starts web dashboard at `http://localhost:5000`
- View real-time portfolio performance
- Monitor profit/loss trends
- Analyze trading history and news impact

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