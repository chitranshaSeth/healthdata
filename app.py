from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime

app = Flask(__name__)

# Finnhub API key
FINNHUB_API_KEY = 'cvo9p8hr01qppf5bp6cgcvo9p8hr01qppf5bp6d0'

def format_market_cap(market_cap):
    if not market_cap or market_cap == 'N/A':
        return 'N/A'
    # Convert to billions for readability
    market_cap_b = market_cap / 1000000000
    return f'${market_cap_b:.2f}B'

def format_volume(volume):
    if not volume or volume == 'N/A':
        return 'N/A'
    return '{:,}'.format(volume)

def get_stock_info(symbol):
    try:
        headers = {'X-Finnhub-Token': FINNHUB_API_KEY}
        base_url = 'https://finnhub.io/api/v1'
        
        # Get quote
        quote_url = f'{base_url}/quote?symbol={symbol}'
        quote_response = requests.get(quote_url, headers=headers)
        quote_data = quote_response.json()
        
        if quote_response.status_code != 200:
            return {'error': 'API error. Please try again later.'}
            
        # Get company profile
        profile_url = f'{base_url}/stock/profile2?symbol={symbol}'
        profile_response = requests.get(profile_url, headers=headers)
        profile_data = profile_response.json()
        
        if not quote_data or quote_data.get('c', 0) == 0:
            return {'error': 'No data found for this symbol. Please check if the symbol is correct.'}
            
        current_price = quote_data.get('c', 0)
        prev_close = quote_data.get('pc', 0)
        change_percent = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
        
        return {
            'symbol': symbol,
            'name': profile_data.get('name', symbol),
            'price': f'${current_price:.2f}',
            'change': f'{change_percent:+.2f}%',
            'volume': format_volume(quote_data.get('t', 'N/A')),
            'market_cap': format_market_cap(profile_data.get('marketCapitalization', 'N/A')),
            'high_day': f'${quote_data.get("h", 0):.2f}',
            'low_day': f'${quote_data.get("l", 0):.2f}',
            'error': None
        }
    except requests.exceptions.RequestException as e:
        return {'error': 'Network error. Please check your internet connection.'}
    except Exception as e:
        return {'error': f'Error fetching stock information: {str(e)}'}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_stock', methods=['POST'])
def get_stock():
    query = request.form.get('query', '').strip().upper()
    if not query:
        return jsonify({'error': 'Please enter a stock symbol'})
    
    result = get_stock_info(query)
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
