# setup_database.py
"""
Database setup script for Blue Iris Alert Handler
Run this once to create the database table and test connectivity.
"""

import os
from dotenv import load_dotenv
from alert_helper import OnePasswordHelper
from database_helper import DatabaseLogger, DatabaseConfig

def main():
    print("🔧 Setting up Blue Iris Alert Handler Database...")
    
    # Load environment
    load_dotenv()
    
    try:
        # Load secrets from 1Password
        print("📋 Loading database credentials from 1Password...")
        secrets = OnePasswordHelper.get_item_json("SecretsMGMT", "bi_alert_handler_secrets")
        
        # Create database config
        db_config = DatabaseConfig(
            host=OnePasswordHelper.get_field(secrets, "DB_HOST"),
            port=int(OnePasswordHelper.get_field(secrets, "DB_PORT", "5432")),
            database=OnePasswordHelper.get_field(secrets, "DB_DATABASE"),
            username=OnePasswordHelper.get_field(secrets, "DB_USERNAME"),
            password=OnePasswordHelper.get_field(secrets, "DB_PASSWORD")
        )
        
        print(f"🔗 Connecting to database: {db_config.host}:{db_config.port}/{db_config.database}")
        
        # Create database logger and test connection
        db_logger = DatabaseLogger(
            db_config, 
            debug_log=lambda msg: print(f"[DEBUG] {msg}"),
            log=lambda msg: print(f"[INFO] {msg}")
        )
        
        # Test connection
        db_logger.connect()
        print("✅ Database connection successful!")
        
        # Create table
        print("📊 Creating alert_logs table...")
        db_logger.ensure_table_exists()
        print("✅ Table created/verified successfully!")
        
        # Test basic operations
        print("🧪 Testing database operations...")
        
        # Get recent alerts (should return empty list for new setup)
        recent_alerts = db_logger.get_recent_alerts(limit=5)
        print(f"📈 Found {len(recent_alerts)} recent alerts in database")
        
        # Get stats
        stats = db_logger.get_alert_stats(days=7)
        print(f"📊 Last 7 days stats: {stats}")
        
        # Clean up
        db_logger.disconnect()
        print("✅ Database setup completed successfully!")
        
        print("\n🎉 Database is ready for Blue Iris Alert Handler!")
        print("The script will now log all n8n webhook data to the 'alert_logs' table.")
        
    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        print("\nPlease check:")
        print("1. Database server is running and accessible")
        print("2. Database credentials in 1Password are correct") 
        print("3. Database user has CREATE TABLE permissions")
        print("4. Network connectivity to database server")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())