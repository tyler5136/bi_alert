# config.py - Configuration for Blue Iris Alert Logs Web Interface
import os
from pathlib import Path

class Config:
    """Configuration settings for the web application."""
    
    # --- Path Configuration ---
    # The webviewer needs to know where to find the shared Python modules
    # (e.g., alert_helper.py, database_helper.py).
    #
    # Set the MODULES_PATH environment variable to the absolute path of the
    # directory containing these modules.
    #
    # If not set, it defaults to the parent directory of this `webviewer` folder.
    MODULES_PATH = Path(os.getenv("MODULES_PATH", Path(__file__).parent.parent)).resolve()
    
    # Flask Configuration
    DEBUG = True
    HOST = '0.0.0.0'  # Listen on all interfaces
    PORT = 5050
    
    # Database Configuration
    DEFAULT_ALERT_LIMIT = 50
    MAX_ALERT_LIMIT = 200
    
    # Auto-refresh Configuration (in seconds)
    AUTO_REFRESH_INTERVAL = 30
    
    # 1Password Configuration
    VAULT_NAME = "SecretsMGMT"
    SECRETS_ITEM = "bi_alert_handler_secrets"
    
    @classmethod
    def get_env_search_paths(cls):
        """Get list of paths to search for .env file."""
        return [
            Path(__file__).parent / ".env",  # webviewer/.env
            cls.MODULES_PATH / ".env",       # modules_path/.env
            Path.cwd() / ".env"              # current working directory
        ]
    
    @classmethod
    def validate_paths(cls):
        """Validate that required paths exist."""
        issues = []
        
        if not cls.MODULES_PATH.exists():
            issues.append(f"Modules directory does not exist: {cls.MODULES_PATH}")
        
        alert_helper = cls.MODULES_PATH / "alert_helper.py"
        if not alert_helper.exists():
            issues.append(f"alert_helper.py not found: {alert_helper}")
        
        database_helper = cls.MODULES_PATH / "database_helper.py"
        if not database_helper.exists():
            issues.append(f"database_helper.py not found: {database_helper}")
        
        return issues
    
    @classmethod
    def print_config_info(cls):
        """Print configuration information for debugging."""
        print("📋 Web Interface Configuration:")
        print(f"   Modules Directory: {cls.MODULES_PATH}")
        print(f"   App Directory:     {Path(__file__).parent}")
        print(f"   Host:              {cls.HOST}:{cls.PORT}")
        print(f"   Debug Mode:        {cls.DEBUG}")
        print(f"   Auto-refresh:      {cls.AUTO_REFRESH_INTERVAL}s")
        
        # Validate paths
        issues = cls.validate_paths()
        if issues:
            print("\n⚠️ Configuration Issues:")
            for issue in issues:
                print(f"   - {issue}")
        else:
            print("✅ All paths validated successfully")