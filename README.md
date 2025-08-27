
# Binance RSI Trading Bot

A Python trading bot that uses RSI (Relative Strength Index) strategy on Binance testnet.

## Features

- RSI-based mean-reversion strategy
- Paper trading mode (dry-run) by default
- Binance testnet integration for safe testing
- Risk management with position sizing
- Configurable parameters via environment variables

## Setup Instructions

1. **Get Binance Testnet API Keys**
   - Visit https://testnet.binance.vision/
   - Create an account and generate API keys
   - These are for testing only - no real money involved

2. **Configure Environment Variables**
   - Copy `.env.example` to `.env`
   - Add your testnet API keys to the `.env` file
   - Adjust trading parameters as needed

3. **Run the Bot**
   - Click the Run button to start the bot
   - The bot runs in paper trading mode by default
   - Monitor the console for trading signals and actions

## Environment Variables

- `BINANCE_API_KEY`: Your Binance testnet API key
- `BINANCE_API_SECRET`: Your Binance testnet API secret
- `BOT_SYMBOL`: Trading pair (default: BTC/USDT)
- `BOT_TIMEFRAME`: Candlestick timeframe (default: 15m)
- `BOT_RSI_PERIOD`: RSI calculation period (default: 14)
- `BOT_RSI_OS`: RSI oversold level (default: 30)
- `BOT_RSI_OB`: RSI overbought level (default: 70)
- `BOT_LIVE`: Set to "true" for live trading (default: false)

## Safety Features

- Runs on Binance testnet by default
- Paper trading mode prevents real orders
- Risk management with position sizing
- Stop loss and take profit levels

## Strategy

The bot uses RSI mean-reversion:
- **Buy Signal**: RSI < 30 (oversold)
- **Sell Signal**: RSI > 70 (overbought) 
- **Exit**: RSI crosses above 50 for long positions

**Warning**: This is for educational purposes only. Always test thoroughly before using real funds.
