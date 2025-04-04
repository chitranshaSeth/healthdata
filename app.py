from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
from datetime import datetime

app = Flask(__name__)

def get_stock_info(query):
    try:
        # Try to get stock info directly if it's a ticker symbol
        stock = yf.Ticker(query)
        info = stock.info
        return {
            'symbol': info.get('symbol', 'N/A'),
            'name': info.get('longName', 'N/A'),
            'price': info.get('currentPrice', 'N/A'),
            'change': info.get('regularMarketChangePercent', 'N/A'),
            'volume': info.get('volume', 'N/A'),
            'market_cap': info.get('marketCap', 'N/A'),
            'error': None
        }
    except:
        # If direct lookup fails, try searching
        try:
            # Search for the stock
            search_results = yf.Tickers(query)
            if search_results.tickers:
                # Get the first result
                stock = search_results.tickers[0]
                info = stock.info
                return {
                    'symbol': info.get('symbol', 'N/A'),
                    'name': info.get('longName', 'N/A'),
                    'price': info.get('currentPrice', 'N/A'),
                    'change': info.get('regularMarketChangePercent', 'N/A'),
                    'volume': info.get('volume', 'N/A'),
                    'market_cap': info.get('marketCap', 'N/A'),
                    'error': None
                }
            else:
                return {'error': 'No results found'}
        except:
            return {'error': 'Error fetching stock information'}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_stock', methods=['POST'])
def get_stock():
    query = request.form.get('query', '').strip()
    if not query:
        return jsonify({'error': 'Please enter a stock symbol or company name'})
    
    result = get_stock_info(query)
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
