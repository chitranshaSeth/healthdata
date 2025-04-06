from flask import Flask, render_template, request, jsonify
import time
import math
import datetime
import finnhub
import pandas as pd
import numpy as np
from threading import Thread, Lock
from collections import defaultdict
from scipy import stats
from sklearn.linear_model import LinearRegression
from websocket import WebSocketApp
import json
import functools
from time import sleep
import random
import os

app = Flask(__name__)

# Finnhub API key - replace with your actual key
FINNHUB_API_KEY = 'your_api_key_here'  # Replace this with your actual Finnhub API key
finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)

# API request tracking and caching
class APITracker:
    def __init__(self):
        self.total_requests = 0
        self.requests_today = 0
        self.last_reset = datetime.datetime.now().date()
        self.requests_per_symbol = {}
        self.last_request_time = time.time()
        self.base_delay = 1  # Finnhub has better rate limits
        self.max_retries = 3
        self.cache = {}
        self.cache_duration = 60  # Cache duration in seconds
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
    
    def track_request(self, symbol):
        current_time = time.time()
        
        # Reset per-minute counter if a minute has passed
        if current_time - self.minute_start >= 60:
            self.requests_per_minute = 0
            self.minute_start = current_time
        
        # Check if we need to reset daily counter
        current_date = datetime.datetime.now().date()
        if current_date > self.last_reset:
            self.requests_today = 0
            self.last_reset = current_date
        
        # Update counters
        self.total_requests += 1
        self.requests_today += 1
        self.requests_per_minute += 1
        
        # Update per-symbol counter
        if symbol not in self.requests_per_symbol:
            self.requests_per_symbol[symbol] = 0
        self.requests_per_symbol[symbol] += 1
        
        # Update last request time
        self.last_request_time = current_time
    
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
    
    def get_stats(self):
        return {
            'total_requests': self.total_requests,
            'requests_today': self.requests_today,
            'requests_per_symbol': self.requests_per_symbol,
            'last_reset': self.last_reset.strftime('%Y-%m-%d'),
            'requests_per_minute': self.requests_per_minute
        }

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

class TechnicalAnalysis:
    @staticmethod
    def calculate_moving_averages(prices, windows=[20, 50, 200]):
        df = pd.DataFrame(prices, columns=['price'])
        mas = {}
        for window in windows:
            mas[f'MA{window}'] = df['price'].rolling(window=min(window, len(prices))).mean().iloc[-1]
        return mas
    
    @staticmethod
    def calculate_rsi(prices, period=14):
        df = pd.DataFrame(prices, columns=['price'])
        delta = df['price'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    
    @staticmethod
    def calculate_bollinger_bands(prices, window=20):
        df = pd.DataFrame(prices, columns=['price'])
        ma = df['price'].rolling(window=window).mean()
        std = df['price'].rolling(window=window).std()
        upper_band = ma + (std * 2)
        lower_band = ma - (std * 2)
        return {
            'middle': ma.iloc[-1],
            'upper': upper_band.iloc[-1],
            'lower': lower_band.iloc[-1]
        }

    @staticmethod
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        df = pd.DataFrame(prices, columns=['price'])
        exp1 = df['price'].ewm(span=fast, adjust=False).mean()
        exp2 = df['price'].ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return {
            'macd': macd.iloc[-1],
            'signal': signal_line.iloc[-1],
            'histogram': histogram.iloc[-1]
        }
    
    @staticmethod
    def calculate_stochastic(prices, high_prices, low_prices, k_period=14, d_period=3):
        df = pd.DataFrame({
            'close': prices,
            'high': high_prices,
            'low': low_prices
        })
        
        # Calculate %K
        lowest_low = df['low'].rolling(window=k_period).min()
        highest_high = df['high'].rolling(window=k_period).max()
        k = 100 * ((df['close'] - lowest_low) / (highest_high - lowest_low))
        
        # Calculate %D (SMA of %K)
        d = k.rolling(window=d_period).mean()
        
        return {
            'k': k.iloc[-1],
            'd': d.iloc[-1]
        }
    
    @staticmethod
    def analyze_trend(prices, macd_data, rsi_value, stoch_data):
        # Trend analysis based on multiple indicators
        trend = {
            'direction': 'neutral',
            'strength': 'moderate',
            'signals': []
        }
        
        # MACD Analysis
        if macd_data['histogram'] > 0 and macd_data['macd'] > macd_data['signal']:
            trend['signals'].append('MACD bullish')
        elif macd_data['histogram'] < 0 and macd_data['macd'] < macd_data['signal']:
            trend['signals'].append('MACD bearish')
        
        # RSI Analysis
        if rsi_value > 70:
            trend['signals'].append('RSI overbought')
        elif rsi_value < 30:
            trend['signals'].append('RSI oversold')
        
        # Stochastic Analysis
        if stoch_data['k'] > 80 and stoch_data['d'] > 80:
            trend['signals'].append('Stochastic overbought')
        elif stoch_data['k'] < 20 and stoch_data['d'] < 20:
            trend['signals'].append('Stochastic oversold')
        
        # Determine overall trend
        bullish_signals = sum(1 for s in trend['signals'] if 'bullish' in s.lower() or 'oversold' in s.lower())
        bearish_signals = sum(1 for s in trend['signals'] if 'bearish' in s.lower() or 'overbought' in s.lower())
        
        if bullish_signals > bearish_signals:
            trend['direction'] = 'bullish'
            trend['strength'] = 'strong' if bullish_signals >= 2 else 'moderate'
        elif bearish_signals > bullish_signals:
            trend['direction'] = 'bearish'
            trend['strength'] = 'strong' if bearish_signals >= 2 else 'moderate'
        
        return trend

class PricePredictor:
    def __init__(self):
        self.model = LinearRegression()
        
    def prepare_features(self, price_history, holding_years):
        # Convert price history to features
        prices = np.array([p[1] for p in price_history])
        times = np.array([p[0] for p in price_history])
        
        # Calculate returns and volatility
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns) * np.sqrt(252)  # Annualized volatility
        
        # Create time-based features
        time_deltas = times - times[0]
        
        # Technical indicators
        ma_20 = pd.Series(prices).rolling(window=20).mean().iloc[-1]
        ma_50 = pd.Series(prices).rolling(window=50).mean().iloc[-1]
        
        # Combine features
        X = np.column_stack([
            time_deltas,
            prices,
            [volatility] * len(prices),
            [ma_20] * len(prices),
            [ma_50] * len(prices),
            [holding_years] * len(prices)
        ])
        
        return X, prices
    
    def predict_price_range(self, price_history, current_price, holding_years):
        if len(price_history) < 30:  # Need minimum history for reliable prediction
            return None
            
        X, y = self.prepare_features(price_history, holding_years)
        
        # Train model on historical data
        self.model.fit(X[:-1], y[1:])
        
        # Predict future prices
        future_time = X[-1][0] + (holding_years * 365 * 24 * 60 * 60)  # Convert years to seconds
        future_X = np.array([[
            future_time,
            current_price,
            X[-1][2],  # volatility
            X[-1][3],  # ma_20
            X[-1][4],  # ma_50
            holding_years
        ]])
        
        predicted_price = self.model.predict(future_X)[0]
        
        # Calculate confidence interval
        confidence_level = 0.95
        std_error = np.std(y - self.model.predict(X))
        margin_of_error = stats.t.ppf((1 + confidence_level) / 2, len(y) - 2) * std_error
        
        return {
            'predicted_price': predicted_price,
            'lower_bound': predicted_price - margin_of_error,
            'upper_bound': predicted_price + margin_of_error,
            'confidence_level': confidence_level
        }

class StockMonitor:
    def __init__(self):
        self.monitored_stocks = {}
        self.price_history = defaultdict(list)
        self.technical_analysis = TechnicalAnalysis()
        self.price_predictor = PricePredictor()
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
                                
                                # Update price history
                                self.price_history[symbol].append((timestamp, current_price))
                                # Keep last 24 hours
                                cutoff = timestamp - (24 * 60 * 60)
                                self.price_history[symbol] = [
                                    x for x in self.price_history[symbol] if x[0] > cutoff
                                ]
                                
                                # Calculate technical indicators
                                prices = [p[1] for p in self.price_history[symbol]]
                                if len(prices) >= 14:  # Minimum data points needed for indicators
                                    indicators = {
                                        'moving_averages': self.technical_analysis.calculate_moving_averages(prices),
                                        'rsi': self.technical_analysis.calculate_rsi(prices),
                                        'bollinger_bands': self.technical_analysis.calculate_bollinger_bands(prices),
                                        'macd': self.technical_analysis.calculate_macd(prices),
                                        'stochastic': self.technical_analysis.calculate_stochastic(prices, prices, prices)
                                    }
                                    
                                    self.monitored_stocks[symbol] = {
                                        'price': current_price,
                                        'last_update': timestamp,
                                        'technical_indicators': indicators
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
            data = self.monitored_stocks.get(symbol, {})
            if data and data.get('price'):
                # Add price prediction if we have enough history
                price_history = self.price_history.get(symbol, [])
                if len(price_history) >= 30:
                    prediction = self.price_predictor.predict_price_range(
                        price_history,
                        data['price'],
                        1.0  # Default 1 year prediction
                    )
                    if prediction:
                        data['price_prediction'] = prediction
            return data
    
    def get_price_history(self, symbol):
        with self.lock:
            return self.price_history.get(symbol, [])

# Initialize monitors
stock_monitor = StockMonitor()

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
            
            # Get historical data
            try:
                # Get daily candles for the past month
                end_date = int(time.time())
                start_date = end_date - (30 * 24 * 60 * 60)  # 30 days ago
                candles = finnhub_client.stock_candles(symbol, 'D', start_date, end_date)
                
                if candles and 'c' in candles and len(candles['c']) > 0:
                    print(f"Successfully got historical data for {symbol}")
                    hist_data = {
                        'close': candles['c'],
                        'high': candles['h'],
                        'low': candles['l'],
                        'open': candles['o'],
                        'volume': candles['v'],
                        'timestamp': candles['t']
                    }
                else:
                    print(f"Warning: No historical data available for {symbol}")
                    hist_data = None
            except Exception as e:
                print(f"Error getting historical data: {str(e)}")
                hist_data = None
            
            return {
                'price': current_price,
                'profile': profile,
                'history': hist_data
            }
        
        # Use the retry mechanism with our improved error handling
        stock_data = api_tracker.handle_request_with_retry(symbol, fetch_stock_data)
        
        response = {
            'symbol': symbol,
            'current_price': stock_data['price'],
            'last_update': time.time(),
            'api_stats': api_tracker.get_stats()
        }
        
        # Add company profile if available
        if stock_data.get('profile'):
            response['company_profile'] = stock_data['profile']
        
        # Add technical analysis if we have history
        if stock_data.get('history'):
            hist = stock_data['history']
            prices = hist['close']
            
            if len(prices) >= 14:  # Minimum data points needed
                response['technical_indicators'] = {
                    'moving_averages': TechnicalAnalysis.calculate_moving_averages(prices),
                    'rsi': TechnicalAnalysis.calculate_rsi(prices),
                    'bollinger_bands': TechnicalAnalysis.calculate_bollinger_bands(prices),
                    'macd': TechnicalAnalysis.calculate_macd(prices),
                    'stochastic': TechnicalAnalysis.calculate_stochastic(
                        prices,
                        hist['high'],
                        hist['low']
                    )
                }
        
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
        target_roi = request.args.get('target_roi')
        holding_years = request.args.get('holding_years')
        
        # Check if we need to delay the request
        needs_delay, delay_time = api_tracker.get_delay_status()
        if needs_delay:
            return jsonify({
                'delay': True,
                'delay_seconds': round(delay_time, 1),
                'message': f'Please wait {round(delay_time, 1)} seconds before making another request.'
            })
        
        # Convert target_roi to float if provided, otherwise None
        target_roi = float(target_roi) if target_roi else None
        holding_years = float(holding_years) if holding_years else None
        
        stock_info = get_stock_info(symbol)
        return jsonify(stock_info)
        
    except Exception as e:
        return jsonify({'error': f'Error fetching stock information: {str(e)}'})

@app.route('/api_stats')
def get_api_stats():
    return jsonify(api_tracker.get_stats())

if __name__ == '__main__':
    app.run(debug=True, port=5001)
