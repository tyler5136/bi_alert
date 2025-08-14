# app.py - Flask web application for Blue Iris Alert Logs
import sys
import os
from pathlib import Path

# Import configuration
try:
    from config import Config
except ImportError:
    print("⚠️ config.py not found, using default configuration")
    class Config:
        MODULES_PATH = Path(__file__).parent.parent
        DEBUG = False
        HOST = '0.0.0.0'
        PORT = 5050
        DEFAULT_ALERT_LIMIT = 50
        MAX_ALERT_LIMIT = 200
        VAULT_NAME = "SecretsMGMT"
        SECRETS_ITEM = "bi_alert_handler_secrets"

# Add modules directory to Python path for imports
sys.path.insert(0, str(Config.MODULES_PATH))

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from datetime import datetime
from dotenv import load_dotenv

# Import from configured modules directory
try:
    from alert_helper import OnePasswordHelper
    from database_helper import DatabaseLogger, DatabaseConfig
except ImportError as e:
    print(f"❌ Failed to import required modules from {Config.MODULES_PATH}")
    print(f"Error: {e}")
    print("\nTroubleshooting:")
    print("1. Make sure alert_helper.py and database_helper.py exist in the modules directory")
    print("2. Check the MODULES_PATH path in config.py")
    print("3. Verify the directory structure is correct")
    if hasattr(Config, 'validate_paths'):
        issues = Config.validate_paths()
        if issues:
            print("\nPath Issues Found:")
            for issue in issues:
                print(f"   - {issue}")
    sys.exit(1)

# Load environment from multiple possible locations
if hasattr(Config, 'get_env_search_paths'):
    env_paths = Config.get_env_search_paths()
else:
    env_paths = [
        Path(__file__).parent / ".env",
        Config.MODULES_PATH / ".env",
        Path.cwd() / ".env"
    ]

env_loaded = False
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        print(f"✅ Loaded environment from: {env_path}")
        env_loaded = True
        break

if not env_loaded:
    print("⚠️ No .env file found in expected locations")
    print(f"Searched: {[str(p) for p in env_paths]}")

app = Flask(__name__)
app.config['DEBUG'] = Config.DEBUG
socketio = SocketIO(app)

# Global database logger
db_logger = None

def init_database():
    """Initialize database connection."""
    global db_logger
    try:
        print("🔗 Initializing database connection...")
        
        # Load secrets from 1Password
        secrets = OnePasswordHelper.get_item_json(Config.VAULT_NAME, Config.SECRETS_ITEM)
        
        # Create database config
        db_config = DatabaseConfig(
            host=OnePasswordHelper.get_field(secrets, "DB_HOST"),
            database=OnePasswordHelper.get_field(secrets, "DB_DATABASE"),
            username=OnePasswordHelper.get_field(secrets, "DB_USERNAME"),
            password=OnePasswordHelper.get_field(secrets, "DB_PASSWORD"),
            port=int(OnePasswordHelper.get_field(secrets, "DB_PORT", "5432"))
        )
        
        print(f"🔗 Connecting to: {db_config.host}:{db_config.port}/{db_config.database}")
        
        db_logger = DatabaseLogger(db_config)
        db_logger.connect()
        print("✅ Database connected for web app")
        return True
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        print("Check your 1Password credentials and database connectivity")
        return False

@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    """Dashboard page."""
    return render_template('dashboard.html')

def format_alert_for_json(alert):
    """Helper function to format an alert dictionary for JSON serialization."""
    created_at = alert.get('created_at')
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()

    return {
        'id': alert.get('id'),
        'camera': alert.get('camera'),
        'timestamp': alert.get('timestamp'),
        'alert_handle': alert.get('alert_handle'),
        'gif_url': alert.get('gif_url'),
        'jpeg_urls': alert.get('jpeg_urls', []),
        'jpeg_count': alert.get('jpeg_count', 0),
        'success': alert.get('success', False),
        'error_message': alert.get('error_message'),
        'debug_mode': alert.get('debug_mode', False),
        'created_at': created_at
    }


@app.route('/api/alerts')
def get_alerts():
    """API endpoint to get alert logs."""
    try:
        limit = request.args.get('limit', Config.DEFAULT_ALERT_LIMIT, type=int)
        limit = min(max(1, limit), Config.MAX_ALERT_LIMIT)
        
        if not db_logger:
            return jsonify({'error': 'Database not connected'}), 500
        
        alerts = db_logger.get_recent_alerts(limit=limit)
        
        # Format alerts for JSON response
        formatted_alerts = [format_alert_for_json(alert) for alert in alerts]
        return jsonify({'alerts': formatted_alerts})
    
    except Exception as e:
        print(f"❌ API Error (get_alerts): {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """API endpoint to get statistics."""
    try:
        if not db_logger:
            return jsonify({'error': 'Database not connected'}), 500
        
        stats = db_logger.get_alert_stats(days=7)
        return jsonify(stats)
    
    except Exception as e:
        print(f"❌ API Error (get_stats): {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/notify', methods=['POST'])
def notify():
    """
    Endpoint to be called by the alert handler when a new alert is created.
    It broadcasts the new alert data to all connected clients.
    """
    if not db_logger:
        return jsonify({'error': 'Database not connected'}), 500

    # For now, just fetch the latest alert from the database.
    # In the future, this could take an alert_id from the request body.
    alerts = db_logger.get_recent_alerts(limit=1)
    if not alerts:
        return jsonify({'status': 'no new alerts found'}), 200

    new_alert = alerts[0]

    # Format the alert for JSON response
    formatted_alert = format_alert_for_json(new_alert)

    # Broadcast the new alert to all clients
    socketio.emit('new_alert', formatted_alert)

    return jsonify({'status': 'notification sent'})

@app.route('/api/health')
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'database_connected': db_logger is not None,
        'modules_path': str(Config.MODULES_PATH),
        'app_path': str(Path(__file__).parent),
        'config_valid': len(Config.validate_paths()) == 0 if hasattr(Config, 'validate_paths') else True
    })

if __name__ == '__main__':
    print("🚀 Starting Blue Iris Alert Logs Web Interface...")
    
    # Print configuration info
    if hasattr(Config, 'print_config_info'):
        Config.print_config_info()
    else:
        print(f"📂 Modules directory: {Config.MODULES_PATH}")
        print(f"📂 App directory: {Path(__file__).parent}")
    
    if init_database():
        print(f"🌐 Starting web server on http://localhost:{Config.PORT}")
        print(f"🌐 Also accessible on http://{Config.HOST}:{Config.PORT} (all interfaces)")
        socketio.run(app, debug=Config.DEBUG, host=Config.HOST, port=Config.PORT)
    else:
        print("❌ Failed to start - database connection required")
        print("\nTroubleshooting:")
        print("1. Make sure your database is running")
        print("2. Verify 1Password credentials are correct")
        print("3. Run setup_database.py first if needed")
        print("4. Check that alert_helper.py and database_helper.py exist in the correct location")