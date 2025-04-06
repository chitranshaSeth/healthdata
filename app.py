from flask import Flask, render_template, request, jsonify
import time
import datetime
import finnhub
from threading import Thread, Lock
from collections import defaultdict
import json
import random
import os

app = Flask(__name__)

# Finnhub API key
FINNHUB_API_KEY = 'cvp16ohr01qihjtrhc90cvp16ohr01qihjtrhc9g'
finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

# API request tracking and caching
class APITracker:
    def __init__(self):
        self.cache = {}
        self.cache_duration = 60  # Cache duration in seconds
        self.last_request_time = time.time()
        self.base_delay = 1  # Finnhub has better rate limits
        self.max_retries = 3
        self.requests_per_minute = 0
        self.minute_start = time.time()
        self.max_requests_per_minute = 60  # Finnhub allows 60 requests per minute
        
    def _should_use_cache(self, symbol):
        if symbol in self.cache:
            cache_time, _ = self.cache[symbol]
            if time.time() - cache_time < self.cache_duration:
                return True
        return False
    
    def get_cached_data(self, symbol):
        if self._should_use_cache(symbol):
            return self.cache[symbol][1]
        return None
    
    def update_cache(self, symbol, data):
        self.cache[symbol] = (time.time(), data)
    
    def get_delay_status(self):
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        # Check rate limits
        if self.requests_per_minute >= self.max_requests_per_minute:
            return True, 60 - (current_time - self.minute_start)
        
        if time_since_last_request < self.base_delay:
            delay_needed = self.base_delay - time_since_last_request
            return True, delay_needed
        
        return False, 0

    def handle_request_with_retry(self, symbol, request_func):
        # Check cache first
        cached_data = self.get_cached_data(symbol)
        if cached_data:
            print(f"Using cached data for {symbol}")
            return cached_data
        
        for attempt in range(self.max_retries):
            try:
                # Check rate limits
                needs_delay, delay_time = self.get_delay_status()
                if needs_delay:
                    print(f"Rate limit reached, waiting {delay_time:.1f} seconds...")
                    time.sleep(delay_time)
                
                # Make the request
                print(f"Attempting request for {symbol} (attempt {attempt + 1}/{self.max_retries})")
                data = request_func()
                
                # Cache successful response
                self.update_cache(symbol, data)
                return data
                
            except Exception as e:
                error_str = str(e)
                print(f"Error on attempt {attempt + 1}: {error_str}")
                
                if "Too Many Requests" in error_str:
                    # Exponential backoff with additional random delay
                    wait_time = (self.base_delay * (2 ** attempt)) + (random.random() * 2)
                    print(f"Rate limit exceeded. Waiting {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                    
                elif attempt == self.max_retries - 1:
                    # On last attempt, raise the error
                    raise Exception(f"Failed to fetch data after {self.max_retries} retries: {error_str}")
                
                else:
                    # For other errors, use shorter delay
                    wait_time = self.base_delay + (random.random() * 1)
                    print(f"Error occurred. Waiting {wait_time:.1f} seconds...")
                    time.sleep(wait_time)

# Initialize tracker
api_tracker = APITracker()

class StockMonitor:
    def __init__(self):
        self.monitored_stocks = {}
        self.lock = Lock()
        self.websockets = {}
        self.update_interval = 60  # Update every minute
        self._start_monitoring()
    
    def _start_monitoring(self):
        def update_loop():
            while True:
                with self.lock:
                    for symbol in list(self.monitored_stocks.keys()):
                        try:
                            def fetch_latest_data():
                                # Get quote data from Finnhub
                                quote = finnhub_client.quote(symbol)
                                if not quote or 'c' not in quote:
                                    raise Exception(f"{symbol}: No price data found")
                                return quote
                            
                            # Use the retry mechanism
                            quote_data = api_tracker.handle_request_with_retry(symbol, fetch_latest_data)
                            
                            if quote_data and 'c' in quote_data:
                                current_price = quote_data['c']
                                timestamp = time.time()
                                
                                self.monitored_stocks[symbol] = {
                                    'price': current_price,
                                    'last_update': timestamp
                                }
                                
                                # Notify websocket clients
                                self._notify_clients(symbol)
                                
                        except Exception as e:
                            print(f"Error updating {symbol}: {str(e)}")
                        
                        # Use base delay between stocks
                        time.sleep(api_tracker.base_delay)
                
                # Sleep until next update interval
                time.sleep(self.update_interval)
        
        Thread(target=update_loop, daemon=True).start()
    
    def _notify_clients(self, symbol):
        if symbol in self.websockets:
            data = self.get_stock_data(symbol)
            message = json.dumps({
                'type': 'price_update',
                'data': data
            })
            for ws in self.websockets[symbol]:
                try:
                    ws.send(message)
                except Exception as e:
                    print(f"Error sending websocket message: {str(e)}")
    
    def add_stock(self, symbol):
        with self.lock:
            if symbol not in self.monitored_stocks:
                self.monitored_stocks[symbol] = {'price': None, 'last_update': None}
    
    def get_stock_data(self, symbol):
        with self.lock:
            return self.monitored_stocks.get(symbol, {})

    def compare_stocks(self, symbols):
        """Compare multiple stocks based on various metrics."""
        comparison = {}
        
        for symbol in symbols:
            try:
                # Get stock data using existing method
                stock_data = get_stock_info(symbol)
                
                if 'error' in stock_data:
                    comparison[symbol] = {'error': stock_data['error']}
                    continue
                
                # Extract key metrics for comparison
                metrics = {
                    'current_price': stock_data.get('current_price'),
                    'company_profile': stock_data.get('company_profile')
                }
                
                comparison[symbol] = metrics
                
            except Exception as e:
                comparison[symbol] = {'error': str(e)}
        
        return comparison

# Initialize monitors
stock_monitor = StockMonitor()

def get_historical_data(symbol, resolution='D', from_time=None, to_time=None):
    """
    Fetch historical stock data from Finnhub
    resolution: Supported resolution includes: 1, 5, 15, 30, 60, D, W, M
    from_time: UNIX timestamp
    to_time: UNIX timestamp
    """
    if not from_time:
        # Default to 1 year of data
        from_time = int(time.time() - 365 * 24 * 60 * 60)
    if not to_time:
        to_time = int(time.time())
    
    try:
        def fetch_historical():
            return finnhub_client.stock_candles(symbol, resolution, from_time, to_time)
        
        # Use the retry mechanism
        candles = api_tracker.handle_request_with_retry(f"{symbol}_hist", fetch_historical)
        
        if candles['s'] == 'no_data':
            return None
            
        # Process the data
        historical_data = {
            'timestamps': candles['t'],
            'opens': candles['o'],
            'highs': candles['h'],
            'lows': candles['l'],
            'closes': candles['c'],
            'volumes': candles['v']
        }
        
        return historical_data
    except Exception as e:
        print(f"Error fetching historical data for {symbol}: {str(e)}")
        return None

def get_stock_info(symbol):
    try:
        symbol = symbol.upper()
        print(f"\nFetching data for {symbol}...")
        
        def fetch_stock_data():
            # Get quote data from Finnhub
            quote = finnhub_client.quote(symbol)
            if not quote or 'c' not in quote:
                raise Exception("No quote data available")
            
            current_price = quote['c']
            print(f"Successfully got quote for {symbol}: {current_price}")
            
            # Get company profile
            try:
                profile = finnhub_client.company_profile2(symbol=symbol)
                print(f"Successfully got company profile for {symbol}")
            except Exception as e:
                print(f"Error getting company profile: {str(e)}")
                profile = None
            
            return {
                'price': current_price,
                'quote': quote,  # Include full quote data
                'profile': profile
            }
        
        # Use the retry mechanism with our improved error handling
        stock_data = api_tracker.handle_request_with_retry(symbol, fetch_stock_data)
        
        # Get historical data
        historical_data = get_historical_data(symbol)
        
        response = {
            'symbol': symbol,
            'current_price': stock_data['price'],
            'last_update': time.time(),
            'quote': stock_data['quote'],  # Include quote data for price changes
            'historical_data': historical_data  # Add historical data
        }
        
        # Add company profile if available
        if stock_data.get('profile'):
            response['company_profile'] = stock_data['profile']
        
        return response
        
    except Exception as e:
        error_msg = f"Error fetching data for {symbol}: {str(e)}"
        print(error_msg)
        return {'error': error_msg}

# WebSocket route for real-time updates
@app.route('/ws')
def websocket():
    if request.environ.get('wsgi.websocket'):
        ws = request.environ['wsgi.websocket']
        symbol = request.args.get('symbol')
        if symbol:
            symbol = symbol.upper()
            if symbol not in stock_monitor.websockets:
                stock_monitor.websockets[symbol] = set()
            stock_monitor.websockets[symbol].add(ws)
            try:
                while True:
                    message = ws.receive()
                    if message is None:
                        break
            finally:
                stock_monitor.websockets[symbol].remove(ws)
    return ''

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_stock/<symbol>')
def get_stock(symbol):
    try:
        # Check if we need to delay the request
        needs_delay, delay_time = api_tracker.get_delay_status()
        if needs_delay:
            return jsonify({
                'delay': True,
                'delay_seconds': round(delay_time, 1),
                'message': f'Please wait {round(delay_time, 1)} seconds before making another request.'
            })
        
        stock_info = get_stock_info(symbol)
        return jsonify(stock_info)
        
    except Exception as e:
        return jsonify({'error': f'Error fetching stock information: {str(e)}'})

@app.route('/compare_stocks')
def compare_stocks():
    try:
        # Get symbols from query parameters (comma-separated)
        symbols_param = request.args.get('symbols', '')
        if not symbols_param:
            return jsonify({'error': 'No symbols provided'})
        
        # Split and clean symbols
        symbols = [s.strip().upper() for s in symbols_param.split(',')]
        if len(symbols) < 2:
            return jsonify({'error': 'Please provide at least 2 symbols to compare'})
        if len(symbols) > 5:
            return jsonify({'error': 'Maximum 5 symbols can be compared at once'})
        
        # Check rate limits
        needs_delay, delay_time = api_tracker.get_delay_status()
        if needs_delay:
            return jsonify({
                'delay': True,
                'delay_seconds': round(delay_time, 1),
                'message': f'Please wait {round(delay_time, 1)} seconds before making another request.'
            })
        
        # Get comparison data
        comparison_data = stock_monitor.compare_stocks(symbols)
        
        response = {
            'comparison': comparison_data
        }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({'error': f'Error comparing stocks: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True, port=5001)
