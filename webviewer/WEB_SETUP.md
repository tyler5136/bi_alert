# Blue Iris Alert Logs Web Interface

A Flask web application to view your Blue Iris alert logs with GIF preview functionality.

## Directory Structure

Set up your files in this structure:
```
C:\scripts\
├── main.py                    # Your Blue Iris alert handler
├── alert_helper.py            # Helper functions module
├── database_helper.py         # Database operations module
├── .env                       # Environment variables (optional)
└── webviewer\
    ├── app.py                 # Main Flask application
    ├── config.py              # Configuration settings
    ├── web_requirements.txt   # Python dependencies
    └── templates\
        └── index.html         # Web interface template
```

## Setup Instructions

### 1. Install Dependencies
Navigate to the webviewer directory and install requirements:
```bash
cd C:\scripts\webviewer
pip install -r web_requirements.txt
```

### 2. Configure Paths (Optional)
If your scripts are in a different location, edit `config.py`:
```python
# Default (for C:\scripts\webviewer setup):
SCRIPTS_BASE_DIR = Path(__file__).parent.parent

# Alternative examples:
# SCRIPTS_BASE_DIR = Path("C:/scripts")           # Absolute path
# SCRIPTS_BASE_DIR = Path("D:/my_projects")       # Different drive
# SCRIPTS_BASE_DIR = Path.home() / "scripts"     # User directory
```

### 3. Verify Database Setup
Make sure your database is set up and accessible:
```bash
cd C:\scripts
python setup_database.py     # Create database table if needed
python check_database.py     # Verify connectivity and data
```

### 4. Run the Web Application
```bash
cd C:\scripts\webviewer
python app.py
```

The web interface will be available at: **http://localhost:5000**

## Features

### 🎯 **Main Interface**
- **Left Sidebar**: List of recent alerts with status indicators
  - ✅ Success indicator for completed alerts
  - ❌ Failure indicator for failed alerts  
  - Red left border highlights failed alerts
  - Shows camera, time, and alert handle
- **Right Panel**: GIF viewer and alert details
  - Displays alert GIF when an item is selected
  - Shows metadata (camera, timestamp, handle, JPEG count)
  - Provides links to individual JPEG frames
  - Shows error details for failed alerts

### 📊 **Statistics Bar** 
- Real-time 7-day summary at the top
- Shows total alerts, success/failure counts
- Displays unique camera count and success rate

### 🔄 **Auto-Refresh**
- Automatically updates every 30 seconds
- Manual refresh button (🔄) in bottom-right corner
- Real-time data without page reloads

### 📱 **Responsive Design**
- Clean, modern interface
- Works on desktop and tablet devices
- Smooth transitions and hover effects

## Configuration Options

### Web Server Settings (`config.py`)
```python
DEBUG = True          # Enable debug mode
HOST = '0.0.0.0'     # Listen on all network interfaces  
PORT = 5000          # Web server port
```

### Alert Display Settings
```python
DEFAULT_ALERT_LIMIT = 50    # Default number of alerts to show
MAX_ALERT_LIMIT = 200       # Maximum alerts that can be requested
AUTO_REFRESH_INTERVAL = 30  # Auto-refresh interval in seconds
```

### Database Settings
```python
VAULT_NAME = "SecretsMGMT"                    # 1Password vault name
SECRETS_ITEM = "bi_alert_handler_secrets"     # 1Password item name
```

## API Endpoints

The web app provides REST API endpoints:

- **`GET /`** - Main web interface
- **`GET /api/alerts?limit=50`** - Get recent alerts (JSON)
- **`GET /api/stats`** - Get 7-day statistics (JSON)  
- **`GET /api/health`** - Health check and configuration info

### Example API Usage
```bash
# Get last 10 alerts
curl http://localhost:5000/api/alerts?limit=10

# Get statistics
curl http://localhost:5000/api/stats

# Check health/configuration
curl http://localhost:5000/api/health
```

## Network Access

### Local Access Only
Default configuration (localhost only):
```python
HOST = '127.0.0.1'
```

### Network Access
To allow access from other devices on your network:
```python
HOST = '0.0.0.0'  # Listen on all interfaces
```

Then access via: `http://YOUR_SERVER_IP:5000`

## Troubleshooting

### 🔧 **Startup Issues**

**"Failed to import required modules"**
- Check that `alert_helper.py` and `database_helper.py` exist in the scripts directory
- Verify the path in `config.py` is correct
- Ensure you're running from the webviewer directory

**"Database initialization failed"**
- Verify your database server is running
- Check 1Password credentials are correct
- Run `setup_database.py` to create the table
- Test with `check_database.py`

**"No .env file found"**
- This is optional - the app works without it
- Copy your main `.env` file to the webviewer directory if needed

### 📊 **No Data Showing**

**Empty alert list**
- Run your main alert handler to generate test data
- Check database connectivity with `check_database.py`
- Verify alerts exist: `python check_database.py 10`

**GIFs not loading**
- Ensure MinIO server is accessible from your browser
- Check MinIO bucket permissions allow public read access
- Verify GIF URLs are valid and files exist

### 🌐 **Network Issues**

**Can't access from other devices**
- Ensure `HOST = '0.0.0.0'` in `config.py`
- Check Windows Firewall allows port 5000
- Verify devices are on the same network

**Port already in use**
- Change `PORT = 5001` (or another port) in `config.py`
- Or stop the conflicting service using port 5000

### 🔍 **Debugging**

Enable detailed logging by setting `DEBUG = True` in `config.py`, then check the console output when running `python app.py`.

The startup output shows:
- Configuration validation
- Database connection status  
- Path resolution results
- Any import or setup errors

## Security Notes

- **Development only**: This setup is intended for local/internal use
- **No authentication**: Anyone with network access can view alerts
- **Database credentials**: Stored securely in 1Password
- **HTTPS**: Not configured - suitable for internal networks only

For production deployment, consider adding authentication, HTTPS, and proper security headers.

## Advanced Configuration

### Custom Port and Host
```python
# config.py
HOST = '192.168.1.100'  # Specific IP address
PORT = 8080             # Custom port
```

### Different Scripts Location
```python
# config.py  
SCRIPTS_BASE_DIR = Path("D:/security_systems/blue_iris_scripts")
```

### Multiple Environment Files
The app searches for `.env` files in this order:
1. `webviewer/.env` (webviewer directory)
2. `scripts/.env` (main scripts directory)  
3. Current working directory

## Integration

This web interface integrates seamlessly with your existing Blue Iris alert system:

- **Reads from the same database** as your alert handler
- **Uses the same 1Password credentials** for database access
- **Displays the same GIFs and JPEGs** uploaded to MinIO
- **Shows the exact data** sent to your n8n webhooks

No additional configuration required - it automatically uses your existing setup!