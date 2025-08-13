# populate_database_from_logs.py
"""
Script to parse Blue Iris alert handler log files and retroactively populate the database.
This will extract all alert runs (including debug) and insert them into the alert_logs table,
avoiding duplicates based on alert handle.
"""

import os
import re
import glob
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from alert_helper import OnePasswordHelper
from database_helper import DatabaseLogger, DatabaseConfig

class LogParser:
    """Parses Blue Iris alert handler log files."""
    
    def __init__(self):
        self.debug_run_pattern = re.compile(r'🐛 Debug mode: using artifact values with verbose logging')
        self.alert_pattern = re.compile(r'📩 Received alert:\s*\n.*├─ Alert Handle: (.+?)\s*\n.*├─ Camera: (.+?)\s*\n.*└─ Timestamp: (.+?)$', re.MULTILINE)
        self.gif_url_pattern = re.compile(r'✅ Main GIF uploaded: (https://minio\.tsmithit\.net/bialerts/alerts/.+?)$', re.MULTILINE)
        self.jpeg_url_pattern = re.compile(r'✅ Mid-frame JPEG uploaded: (https://minio\.tsmithit\.net/bialerts/alert_frames/.+?)$', re.MULTILINE)
        self.success_pattern = re.compile(r'✅ Process completed$', re.MULTILINE)
        self.execution_start_pattern = re.compile(r'🐛 ========== SCRIPT EXECUTION START ==========')
        self.webhook_success_pattern = re.compile(r'📨 Webhook sent: 200')
        self.failed_pattern = re.compile(r'❌ Failed: (.+?)$', re.MULTILINE)
    
    def extract_run_blocks(self, log_content):
        """Split log content into individual run blocks."""
        # Split by script execution start markers
        blocks = re.split(r'🐛 ========== SCRIPT EXECUTION START ==========', log_content)
        
        # Remove empty first block and add the marker back to each block
        run_blocks = []
        for i, block in enumerate(blocks[1:], 1):  # Skip first empty block
            full_block = '🐛 ========== SCRIPT EXECUTION START ==========\n' + block
            run_blocks.append(full_block)
        
        return run_blocks
    
    def extract_date_from_filename(self, filename):
        """Extract date from log filename like 'log2025-08-09.txt'."""
        try:
            # Extract date pattern from filename
            match = re.search(r'log(\d{4}-\d{2}-\d{2})\.txt', filename)
            if match:
                date_str = match.group(1)
                return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
        return datetime.now().date()
    
    def parse_timestamp(self, timestamp_str, log_filename=None):
        """Parse Blue Iris timestamp string to datetime object."""
        timestamp_str = timestamp_str.strip()
        
        # List of possible timestamp formats Blue Iris might use
        formats = [
            # Full date with AM/PM (space before AM/PM)
            '%m/%d/%Y %I:%M:%S %p',
            # Full date with AM/PM (no space before AM/PM)  
            '%m/%d/%Y %I:%M:%S%p',
            # Full date 24-hour format
            '%m/%d/%Y %H:%M:%S',
            # Time only with AM/PM (we'll use log file date)
            '%I:%M:%S %p',
            # Time only 24-hour format (we'll use log file date)
            '%H:%M:%S'
        ]
        
        for fmt in formats:
            try:
                parsed_dt = datetime.strptime(timestamp_str, fmt)
                
                # If it's time-only format (no date), use log file date
                if fmt in ['%I:%M:%S %p', '%H:%M:%S']:
                    # Use date from log filename if available, otherwise current date
                    if log_filename:
                        log_date = self.extract_date_from_filename(log_filename)
                    else:
                        log_date = datetime.now().date()
                    
                    parsed_dt = datetime.combine(log_date, parsed_dt.time())
                
                return parsed_dt
                
            except ValueError:
                continue
        
        # If none of the formats worked, log the warning
        print(f"   ⚠️  Warning: Could not parse timestamp '{timestamp_str}' with any known format")
        return None
    
    def parse_run_block(self, block, log_filename=None):
        """Parse a single run block and extract alert data."""
        # Check if this is a debug run
        is_debug = bool(self.debug_run_pattern.search(block))
        
        # Extract basic alert info
        alert_match = self.alert_pattern.search(block)
        if not alert_match:
            return None
        
        alert_handle = alert_match.group(1).strip()
        camera = alert_match.group(2).strip()
        timestamp_str = alert_match.group(3).strip()
        
        # Parse the Blue Iris timestamp to use as the actual alert time
        alert_timestamp = self.parse_timestamp(timestamp_str, log_filename)
        if not alert_timestamp:
            return None
        
        # Check if the run was successful
        success = bool(self.success_pattern.search(block) and self.webhook_success_pattern.search(block))
        
        # Extract error message if failed
        error_message = None
        if not success:
            error_match = self.failed_pattern.search(block)
            if error_match:
                error_message = error_match.group(1).strip()
        
        # Extract GIF URL
        gif_url = ""
        gif_match = self.gif_url_pattern.search(block)
        if gif_match:
            gif_url = gif_match.group(1).strip()
        
        # Extract JPEG URLs
        jpeg_urls = []
        jpeg_matches = self.jpeg_url_pattern.findall(block)
        if jpeg_matches:
            jpeg_urls = [url.strip() for url in jpeg_matches]
        
        return {
            'camera': camera,
            'timestamp': timestamp_str,  # Keep original string for database
            'alert_handle': alert_handle,
            'gif_url': gif_url,
            'jpeg_urls': jpeg_urls,
            'success': success,
            'error_message': error_message,
            'debug_mode': is_debug,
            'alert_datetime': alert_timestamp  # Use this for database created_at
        }
    
    def parse_log_file(self, file_path):
        """Parse a single log file and return all alert runs."""
        print(f"📖 Parsing {file_path}...")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"❌ Failed to read {file_path}: {e}")
            return []
        
        # Extract run blocks
        blocks = self.extract_run_blocks(content)
        print(f"   Found {len(blocks)} run blocks")
        
        # Get filename for date extraction
        filename = os.path.basename(file_path)
        
        # Parse each block
        alerts = []
        invalid_runs_skipped = 0
        
        for i, block in enumerate(blocks, 1):
            alert_data = self.parse_run_block(block, filename)
            if alert_data is None:
                invalid_runs_skipped += 1
                continue
            
            alerts.append(alert_data)
        
        debug_count = sum(1 for a in alerts if a['debug_mode'])
        regular_count = len(alerts) - debug_count
        
        print(f"   ✅ Extracted {len(alerts)} valid alerts ({regular_count} regular, {debug_count} debug)")
        if invalid_runs_skipped > 0:
            print(f"   ⚠️  Skipped {invalid_runs_skipped} invalid runs")
        
        return alerts


def deduplicate_alerts(all_alerts):
    """Remove duplicate alerts based on alert_handle, keeping the first occurrence."""
    seen_handles = set()
    unique_alerts = []
    duplicates_removed = 0
    
    # Sort by timestamp to ensure we keep the earliest occurrence
    sorted_alerts = sorted(all_alerts, key=lambda x: x['alert_datetime'] or datetime.min)
    
    for alert in sorted_alerts:
        handle = alert['alert_handle']
        if handle not in seen_handles:
            seen_handles.add(handle)
            unique_alerts.append(alert)
        else:
            duplicates_removed += 1
    
    return unique_alerts, duplicates_removed


def main():
    print("🚀 Blue Iris Alert Log Parser - Database Population (Including Debug)")
    print("=" * 70)
    
    # Load environment
    load_dotenv()
    
    # Get log files directory from user
    log_dir = input("📂 Enter the path to your log files directory (e.g., C:\\scripts\\logs): ").strip()
    if not log_dir:
        log_dir = r"C:\scripts\logs"
    
    if not os.path.exists(log_dir):
        print(f"❌ Directory not found: {log_dir}")
        return 1
    
    # Find all log files
    log_pattern = os.path.join(log_dir, "log*.txt")
    log_files = glob.glob(log_pattern)
    
    if not log_files:
        print(f"❌ No log files found matching pattern: {log_pattern}")
        return 1
    
    print(f"📋 Found {len(log_files)} log files:")
    for f in sorted(log_files):
        print(f"   - {os.path.basename(f)}")
    
    # Confirm with user
    response = input(f"\n🤔 Process all {len(log_files)} files? (y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("❌ Aborted by user")
        return 0
    
    # Initialize database
    try:
        print("\n🔗 Connecting to database...")
        secrets = OnePasswordHelper.get_item_json("SecretsMGMT", "bi_alert_handler_secrets")
        
        db_config = DatabaseConfig(
            host=OnePasswordHelper.get_field(secrets, "DB_HOST"),
            database=OnePasswordHelper.get_field(secrets, "DB_DATABASE"),
            username=OnePasswordHelper.get_field(secrets, "DB_USERNAME"),
            password=OnePasswordHelper.get_field(secrets, "DB_PASSWORD"),
            port=int(OnePasswordHelper.get_field(secrets, "DB_PORT", "5432"))
        )
        
        db_logger = DatabaseLogger(db_config)
        db_logger.ensure_table_exists()
        print("✅ Database connection established")
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1
    
    # Parse all log files
    parser = LogParser()
    all_alerts = []
    
    print(f"\n📖 Processing log files...")
    for log_file in sorted(log_files):
        alerts = parser.parse_log_file(log_file)
        all_alerts.extend(alerts)
    
    print(f"\n📊 Before deduplication:")
    print(f"   Total alerts found: {len(all_alerts)}")
    
    if len(all_alerts) == 0:
        print("❌ No alerts to process")
        return 0
    
    # Deduplicate based on alert handle
    print(f"\n🔄 Removing duplicates based on alert handle...")
    unique_alerts, duplicates_removed = deduplicate_alerts(all_alerts)
    
    print(f"\n📊 After deduplication:")
    print(f"   Unique alerts: {len(unique_alerts)}")
    print(f"   Duplicates removed: {duplicates_removed}")
    
    # Show breakdown
    successful = sum(1 for a in unique_alerts if a['success'])
    failed = len(unique_alerts) - successful
    debug_count = sum(1 for a in unique_alerts if a['debug_mode'])
    regular_count = len(unique_alerts) - debug_count
    cameras = set(a['camera'] for a in unique_alerts)
    
    print(f"   Successful: {successful}")
    print(f"   Failed: {failed}")
    print(f"   Regular runs: {regular_count}")
    print(f"   Debug runs: {debug_count}")
    print(f"   Unique cameras: {len(cameras)} ({', '.join(sorted(cameras))})")
    
    # Show timestamp range
    timestamps = [a['alert_datetime'] for a in unique_alerts if a['alert_datetime']]
    if timestamps:
        earliest = min(timestamps)
        latest = max(timestamps)
        print(f"   Time range: {earliest.strftime('%Y-%m-%d %H:%M:%S')} to {latest.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Confirm database insertion
    response = input(f"\n💾 Insert all {len(unique_alerts)} unique alerts into database? (y/N): ").strip().lower()
    if response not in ['y', 'yes']:
        print("❌ Database insertion aborted by user")
        return 0
    
    # Insert into database
    print(f"\n💾 Inserting alerts into database using original timestamps...")
    inserted_count = 0
    error_count = 0
    
    for i, alert in enumerate(unique_alerts, 1):
        try:
            # Use the original Blue Iris alert timestamp
            created_at = alert['alert_datetime'] or datetime.now()
            
            # Override the database logger to use our custom timestamp
            db_logger.log_alert(
                camera=alert['camera'],
                timestamp=alert['timestamp'],
                alert_handle=alert['alert_handle'],
                gif_url=alert['gif_url'],
                jpeg_urls=alert['jpeg_urls'],
                success=alert['success'],
                error_message=alert['error_message'],
                debug_mode=alert['debug_mode'],
                created_at=created_at  # Pass custom timestamp
            )
            inserted_count += 1
            
            # Progress indicator
            if i % 10 == 0:
                print(f"   Progress: {i}/{len(unique_alerts)} ({(i/len(unique_alerts)*100):.1f}%)")
                
        except Exception as e:
            error_count += 1
            print(f"   ❌ Failed to insert alert {i} (handle: {alert.get('alert_handle', 'unknown')}): {e}")
    
    # Final results
    print(f"\n🎉 Database population completed!")
    print(f"   ✅ Successfully inserted: {inserted_count}")
    if error_count > 0:
        print(f"   ❌ Errors: {error_count}")
    
    # Show recent entries
    print(f"\n📋 Recent entries in database:")
    try:
        recent = db_logger.get_recent_alerts(limit=10)
        for i, alert in enumerate(recent, 1):
            status = "✅" if alert.get('success') else "❌"
            debug_flag = "🐛" if alert.get('debug_mode') else ""
            created = alert.get('created_at', 'Unknown')
            if isinstance(created, datetime):
                created = created.strftime('%Y-%m-%d %H:%M:%S')
            print(f"   {i}. {status}{debug_flag} {alert.get('camera')} - {created}")
    except Exception as e:
        print(f"   ❌ Failed to query recent entries: {e}")
    
    db_logger.disconnect()
    print(f"\n✅ All done! Your database now contains historical alert data.")
    print(f"   🐛 Debug runs are included and marked with debug_mode=true")
    print(f"   📅 Timestamps match the original Blue Iris alert times")
    print(f"   🔄 Duplicates based on alert handle have been removed")
    print(f"   You can view it in your web interface at http://localhost:5050")
    
    return 0


if __name__ == "__main__":
    exit(main())
    