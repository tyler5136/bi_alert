# database_helper.py
import os
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
import time


@dataclass
class DatabaseConfig:
    host: str
    database: str
    username: str
    password: str
    port: int = 5432
    ssl_mode: str = "prefer"


class DatabaseLogger:
    """Handles PostgreSQL database operations for logging n8n webhook data."""
    
    def __init__(self, config: DatabaseConfig, debug_log=lambda *_: None, log=lambda *_: None):
        self.config = config
        self._debug = debug_log
        self._log = log
        self._connection = None
    
    def connect(self):
        """Establish database connection with retry logic."""
        if self._connection and not self._connection.closed:
            # Test the connection
            try:
                with self._connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                return  # Connection is good
            except:
                self._debug("Existing connection failed test, reconnecting...")
        
        for attempt in range(3):
            try:
                if self._connection:
                    self._connection.close()
                
                self._connection = psycopg2.connect(
                    host=self.config.host,
                    port=self.config.port,
                    database=self.config.database,
                    user=self.config.username,
                    password=self.config.password,
                    sslmode=self.config.ssl_mode,
                    connect_timeout=10,
                    cursor_factory=RealDictCursor
                )
                self._debug(f"Database connection established (attempt {attempt + 1})")
                return
            except Exception as e:
                self._debug(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt == 2:  # Last attempt
                    self._log(f"❌ Database connection failed after 3 attempts: {e}")
                    raise
                time.sleep(2)
    
    def disconnect(self):
        """Close database connection."""
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._debug("Database connection closed")
    
    def ensure_table_exists(self):
        """Create the alert_logs table if it doesn't exist."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS alert_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            
            -- Core n8n webhook data
            camera VARCHAR(100) NOT NULL,
            timestamp VARCHAR(100) NOT NULL,
            alert_handle VARCHAR(255),
            
            -- Media URLs (what we send to n8n)
            gif_url TEXT,
            jpeg_urls TEXT[], -- Array of JPEG URLs
            jpeg_count INTEGER DEFAULT 0,
            
            -- Processing status
            success BOOLEAN DEFAULT FALSE,
            error_message TEXT,
            
            -- Metadata
            debug_mode BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        -- Create indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_alert_logs_camera ON alert_logs(camera);
        CREATE INDEX IF NOT EXISTS idx_alert_logs_created_at ON alert_logs(created_at);
        CREATE INDEX IF NOT EXISTS idx_alert_logs_success ON alert_logs(success);
        """
        
        try:
            self.connect()
            with self._connection.cursor() as cursor:
                cursor.execute(create_table_sql)
                self._connection.commit()
            self._debug("Alert logs table ensured to exist")
        except Exception as e:
            self._log(f"❌ Failed to create table: {e}")
            raise
    
    def log_alert(
        self, 
        camera: str,
        timestamp: str,
        alert_handle: str,
        gif_url: str,
        jpeg_urls: List[str] = None,
        success: bool = True,
        error_message: str = None,
        debug_mode: bool = False
    ) -> str:
        """Log the alert data that was sent to n8n."""
        for attempt in range(3):
            try:
                self.connect()
                log_id = str(uuid.uuid4())
                
                jpeg_urls = jpeg_urls or []
                
                insert_sql = """
                INSERT INTO alert_logs (
                    id, camera, timestamp, alert_handle, gif_url, jpeg_urls, 
                    jpeg_count, success, error_message, debug_mode
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                with self._connection.cursor() as cursor:
                    cursor.execute(insert_sql, (
                        log_id, camera, timestamp, alert_handle, gif_url, 
                        jpeg_urls, len(jpeg_urls), success, error_message, debug_mode
                    ))
                    self._connection.commit()
                
                self._debug(f"Logged alert to database: {log_id}")
                return log_id
            except Exception as e:
                self._debug(f"Database log attempt {attempt + 1} failed: {e}")
                if attempt == 2:  # Last attempt
                    self._log(f"❌ Failed to log alert to database after 3 attempts: {e}")
                    raise
                time.sleep(1)
    
    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alert logs for monitoring/debugging."""
        try:
            self.connect()
            query_sql = """
            SELECT * FROM alert_logs 
            ORDER BY created_at DESC 
            LIMIT %s
            """
            
            with self._connection.cursor() as cursor:
                cursor.execute(query_sql, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            self._log(f"❌ Failed to get recent alerts: {e}")
            return []
    
    def get_alert_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get statistics for recent alerts."""
        try:
            self.connect()
            stats_sql = """
            SELECT 
                COUNT(*) as total_alerts,
                COUNT(*) FILTER (WHERE success = true) as successful_alerts,
                COUNT(*) FILTER (WHERE success = false) as failed_alerts,
                COUNT(DISTINCT camera) as unique_cameras
            FROM alert_logs 
            WHERE created_at >= NOW() - INTERVAL '%s days'
            """
            
            with self._connection.cursor() as cursor:
                cursor.execute(stats_sql, (days,))
                result = cursor.fetchone()
                return dict(result) if result else {}
        except Exception as e:
            self._log(f"❌ Failed to get alert stats: {e}")
            return {}