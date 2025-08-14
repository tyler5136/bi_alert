# app.py - Flask web application for Blue Iris Alert Logs
import sys
import os
import json
from pathlib import Path
from functools import wraps
from datetime import datetime

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

from flask import Flask, render_template, jsonify, request, g, redirect, url_for, abort
from flask_socketio import SocketIO
from flask_oidc import OpenIDConnect
from dotenv import load_dotenv

# Import from configured modules directory
try:
    from alert_helper import OnePasswordHelper
    from database_helper import DatabaseLogger, DatabaseConfig
except ImportError as e:
    print(f"❌ Failed to import required modules from {Config.MODULES_PATH}")
    print(f"Error: {e}")
    sys.exit(1)

# --- App Initialization ---

# Create Flask app instance
app = Flask(__name__)
app.config.from_object(Config)

# Load environment from multiple possible locations
# This logic is kept from the original file, slightly adapted
env_paths = getattr(Config, 'get_env_search_paths', lambda: [
    Path(__file__).parent / ".env",
    Config.MODULES_PATH / ".env",
    Path.cwd() / ".env"
])()
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        print(f"✅ Loaded environment from: {env_path}")
        break

# --- OIDC Initialization ---

def create_oidc_secrets_file():
    """Fetches secrets from 1Password and creates client_secrets.json."""
    try:
        print("🤫 Fetching OIDC secrets from 1Password...")
        secrets = OnePasswordHelper.get_item_json(Config.VAULT_NAME, Config.SECRETS_ITEM)

        domain = OnePasswordHelper.get_field(secrets, "AUTHENTIK_DOMAIN")
        slug = OnePasswordHelper.get_field(secrets, "AUTHENTIK_SLUG")
        client_id = OnePasswordHelper.get_field(secrets, "OIDC_CLIENT_ID")
        client_secret = OnePasswordHelper.get_field(secrets, "OIDC_CLIENT_SECRET")

        if not all([domain, slug, client_id, client_secret]):
            print("⚠️ Could not find all required OIDC fields in 1Password.")
            print("   Required: AUTHENTIK_DOMAIN, AUTHENTIK_SLUG, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET")
            return False

        secrets_content = {
            "web": {
                "issuer": f"{domain}/application/o/{slug}/",
                "auth_uri": f"{domain}/application/o/authorize/",
                "client_id": client_id,
                "client_secret": client_secret,
                "token_uri": f"{domain}/application/o/token/",
                "userinfo_uri": f"{domain}/application/o/userinfo/",
                "redirect_uris": [f"http://localhost:{Config.PORT}{Config.OIDC_CALLBACK_ROUTE}"]
            }
        }

        secrets_file_path = app.config["OIDC_CLIENT_SECRETS_FILE"]
        with open(secrets_file_path, 'w') as f:
            json.dump(secrets_content, f, indent=2)

        print(f"✅ OIDC client_secrets.json created successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to create OIDC secrets file: {e}")
        return False

# Create secrets file at module load time
oidc_secrets_created = create_oidc_secrets_file()

# Initialize OIDC or a dummy object if secrets are missing
if oidc_secrets_created:
    oidc = OpenIDConnect(app)
    print("✅ OIDC extension initialized")
else:
    print("🔴 FATAL: OIDC client secrets could not be created. Authentication is disabled.")
    class DummyOIDC:
        def __init__(self):
            self.user_loggedin = False

        def require_login(self, f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                print("⛔️ Access denied: OIDC not configured.")
                abort(503, "Authentication service is not available.")
            return decorated_function

        def user_getfield(self, field):
            return None

        def logout(self):
            pass # No-op for dummy object

    oidc = DummyOIDC()

# --- SocketIO and Database Initialization ---

socketio = SocketIO(app)
db_logger = None

def init_database():
    """Initialize database connection."""
    global db_logger
    try:
        print("🔗 Initializing database connection...")
        secrets = OnePasswordHelper.get_item_json(Config.VAULT_NAME, Config.SECRETS_ITEM)
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
        return False

# --- Routes and Request Handlers ---

@app.before_request
def before_request():
    """Set user info in g before each request if authenticated."""
    if oidc and oidc.user_loggedin:
        g.user = oidc.user_getfield('preferred_username')
    else:
        g.user = None

@app.route('/')
def index():
    """Main page."""
    return render_template('index.html', user=g.user)

@app.route('/dashboard')
@oidc.require_login
def dashboard():
    """Dashboard page."""
    return render_template('dashboard.html', user=g.user)

@app.route('/login')
@oidc.require_login
def login():
    """Login page (triggers OIDC)."""
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    """Logout page."""
    oidc.logout()
    return redirect(url_for('index'))

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
        if not db_logger: return jsonify({'error': 'Database not connected'}), 500
        alerts = db_logger.get_recent_alerts(limit=limit)
        formatted_alerts = [format_alert_for_json(alert) for alert in alerts]
        return jsonify({'alerts': formatted_alerts})
    except Exception as e:
        print(f"❌ API Error (get_alerts): {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """API endpoint to get statistics."""
    try:
        if not db_logger: return jsonify({'error': 'Database not connected'}), 500
        stats = db_logger.get_alert_stats(days=7)
        return jsonify(stats)
    except Exception as e:
        print(f"❌ API Error (get_stats): {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/notify', methods=['POST'])
def notify():
    """Endpoint for new alert notifications."""
    if not db_logger: return jsonify({'error': 'Database not connected'}), 500
    alerts = db_logger.get_recent_alerts(limit=1)
    if not alerts: return jsonify({'status': 'no new alerts found'}), 200
    new_alert = alerts[0]
    formatted_alert = format_alert_for_json(new_alert)
    socketio.emit('new_alert', formatted_alert)
    return jsonify({'status': 'notification sent'})

@app.route('/api/health')
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'database_connected': db_logger is not None,
        'oidc_initialized': not isinstance(oidc, DummyOIDC),
        'modules_path': str(Config.MODULES_PATH),
        'app_path': str(Path(__file__).parent),
        'config_valid': len(Config.validate_paths()) == 0 if hasattr(Config, 'validate_paths') else True
    })

# --- Main Execution ---

if __name__ == '__main__':
    print("🚀 Starting Blue Iris Alert Logs Web Interface...")
    
    if hasattr(Config, 'print_config_info'):
        Config.print_config_info()
    
    # Initialize the database
    if not init_database():
        print("❌ Aborting startup: Database connection failed.")
        sys.exit(1)

    print(f"🌐 Starting web server on http://localhost:{Config.PORT}")
    print(f"🌐 Also accessible on http://{Config.HOST}:{Config.PORT} (all interfaces)")
    socketio.run(app, debug=Config.DEBUG, host=Config.HOST, port=Config.PORT)