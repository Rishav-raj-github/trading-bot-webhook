from flask import Flask, request, jsonify
import hmac
import hashlib
import json
import os
from datetime import datetime
import requests
from binance.client import Client
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment Variables
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'your-webhook-secret')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')
TESTNET_MODE = os.getenv('TESTNET_MODE', 'True').lower() == 'true'

# Initialize Binance Client
if TESTNET_MODE:
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, testnet=True)
else:
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

def verify_webhook_signature(request_data, signature):
    computed_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        request_data.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed_signature, signature)


def parse_tradingview_alert(data):
    try:
        alert_data = json.loads(data) if isinstance(data, str) else data
        return {
            'symbol': alert_data.get('symbol', '').replace('BINANCE:', ''),
            'signal': alert_data.get('signal', 'BUY'),
            'side': alert_data.get('side', 'BUY'),
            'quantity': float(alert_data.get('quantity', 0.001)),
            'price': alert_data.get('price', None),
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error parsing alert: {e}")
        return None

def place_order(symbol, side, quantity, order_type='MARKET', price=None):
    try:
        if not symbol.endswith('USDT'):
            symbol = symbol.upper() + 'USDT'
        
        logger.info(f"Placing {side} order for {symbol}: {quantity}")
        
        if order_type == 'MARKET':
            order = client.order_market(symbol=symbol, side=side, quantity=quantity)
        elif order_type == 'LIMIT' and price:
            order = client.order_limit(symbol=symbol, side=side, timeInForce='GTC', quantity=quantity, price=price)
        else:
            raise ValueError(f"Invalid order type: {order_type}")
        
        return {
            'success': True,
            'order_id': order.get('orderId'),
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'status': order.get('status')
        }
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return {
            'success': False,
            'error': str(e)
        }

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'mode': 'testnet' if TESTNET_MODE else 'live'}), 200


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        raw_data = request.get_data(as_text=True)
        signature = request.headers.get('X-Tradingview-Signature', '')
        if signature and not verify_webhook_signature(raw_data, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({'error': 'Invalid signature'}), 401
        
        alert_data = parse_tradingview_alert(raw_data)
        if not alert_data:
            return jsonify({'error': 'Invalid alert data'}), 400
        
        logger.info(f"Received alert: {alert_data}")
        
        order_result = place_order(
            symbol=alert_data['symbol'],
            side=alert_data['side'],
            quantity=alert_data['quantity'],
            price=alert_data.get('price')
        )
        
        if order_result['success']:
            return jsonify({
                'status': 'success',
                'message': 'Order placed successfully',
                'order': order_result
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to place order',
                'error': order_result.get('error')
            }), 400
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'app': 'Trading Bot Webhook',
        'status': 'running',
        'testnet': TESTNET_MODE,
        'webhook_url': '/webhook',
        'health_check': '/health'
    }), 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
