# check_database.py
"""
Simple script to check the database and show recent alert logs.
Usage: python check_database.py [number_of_alerts]
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from alert_helper import OnePasswordHelper
from database_helper import DatabaseLogger, DatabaseConfig

def format_alert(alert):
    """Format an alert record for display."""
    created_at = alert.get('created_at', 'Unknown')
    if isinstance(created_at, datetime):
        created_at = created_at.strftime('%Y-%m-%d %H:%M:%S')
    
    camera = alert.get('camera', 'Unknown')
    timestamp = alert.get('timestamp', 'Unknown')
    alert_handle = alert.get('alert_handle', 'Unknown')
    success = "✅" if alert.get('success') else "❌"
    jpeg_count = alert.get('jpeg_count', 0)
    
    print(f"  {success} {created_at}")
    print(f"     Camera: {camera}")
    print(f"     Alert Time: {timestamp}")
    print(f"     Handle: {alert_handle}")
    print(f"     JPEGs: {jpeg_count}")
    if alert.get('error_message'):
        print(f"     Error: {alert.get('error_message')}")
    print()

def parse_limit_argument():
    """Parse command line argument for number of alerts to show."""
    limit = 5  # default
    
    if len(sys.argv) > 1:
        try:
            requested_limit = int(sys.argv[1])
            if 1 <= requested_limit <= 100:
                limit = requested_limit
            else:
                print(f"⚠️ Limit must be between 1 and 100. Using default: {limit}")
        except ValueError:
            print(f"⚠️ Invalid argument '{sys.argv[1]}'. Using default: {limit}")
    
    return limit

def main():
    limit = parse_limit_argument()
    
    print(f"🔍 Checking Blue Iris Alert Database (showing last {limit} alerts)...")
    
    # Load environment
    load_dotenv()
    
    try:
        # Load secrets from 1Password
        print("📋 Loading database credentials...")
        secrets = OnePasswordHelper.get_item_json("SecretsMGMT", "bi_alert_handler_secrets")
        
        # Create database config
        db_config = DatabaseConfig(
            host=OnePasswordHelper.get_field(secrets, "DB_HOST"),
            database=OnePasswordHelper.get_field(secrets, "DB_DATABASE"),
            username=OnePasswordHelper.get_field(secrets, "DB_USERNAME"),
            password=OnePasswordHelper.get_field(secrets, "DB_PASSWORD"),
            port=int(OnePasswordHelper.get_field(secrets, "DB_PORT", "5432"))
        )
        
        print(f"🔗 Connecting to: {db_config.host}:{db_config.port}/{db_config.database}")
        
        # Create database logger
        db_logger = DatabaseLogger(db_config)
        
        # Test connection
        db_logger.connect()
        print("✅ Database connection successful!")
        
        # Get recent alerts
        print(f"\n📊 Last {limit} Alert Logs:")
        print("=" * 50)
        recent_alerts = db_logger.get_recent_alerts(limit=limit)
        
        if not recent_alerts:
            print("📭 No alerts found in database")
        else:
            for i, alert in enumerate(recent_alerts, 1):
                print(f"Alert #{i}:")
                format_alert(alert)
        
        # Get stats
        print("📈 Last 7 Days Statistics:")
        print("=" * 30)
        stats = db_logger.get_alert_stats(days=7)
        
        if stats:
            total = stats.get('total_alerts', 0)
            successful = stats.get('successful_alerts', 0)
            failed = stats.get('failed_alerts', 0)
            cameras = stats.get('unique_cameras', 0)
            
            print(f"Total Alerts: {total}")
            print(f"Successful: {successful}")
            print(f"Failed: {failed}")
            print(f"Unique Cameras: {cameras}")
            
            if total > 0:
                success_rate = (successful / total) * 100
                print(f"Success Rate: {success_rate:.1f}%")
        else:
            print("No statistics available")
        
        # Clean up
        db_logger.disconnect()
        print("\n✅ Database check completed!")
        
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())