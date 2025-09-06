#!/usr/bin/env python3
"""
Centralized Error Handling and Logging System
Provides consistent error handling across all D-AI-Trader components
"""

import logging
import traceback
import json
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import text
from config import engine, get_current_config_hash

class ErrorHandler:
    """Centralized error handling and logging"""

    def __init__(self):
        self.logger = logging.getLogger('d_ai_trader')
        self.logger.setLevel(logging.INFO)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Create file handler
        file_handler = logging.FileHandler('d-ai-trader-errors.log')
        file_handler.setLevel(logging.ERROR)

        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # Add handlers to logger
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def log_error(self, error: Exception, context: Optional[Dict[str, Any]] = None,
                  component: str = "unknown", severity: str = "error"):
        """Log an error with context information"""
        error_info = {
            'component': component,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'timestamp': datetime.now().isoformat(),
            'config_hash': get_current_config_hash(),
            'context': context or {}
        }

        # Log to file
        self.logger.error(f"Error in {component}: {error}", extra={'error_info': error_info})

        # Store in database for dashboard visibility
        self._store_error_in_db(error_info)

        return error_info

    def log_info(self, message: str, component: str = "unknown",
                 context: Optional[Dict[str, Any]] = None):
        """Log an info message"""
        self.logger.info(f"[{component}] {message}", extra={'context': context or {}})

    def log_warning(self, message: str, component: str = "unknown",
                   context: Optional[Dict[str, Any]] = None):
        """Log a warning message"""
        self.logger.warning(f"[{component}] {message}", extra={'context': context or {}})

    def _store_error_in_db(self, error_info: Dict[str, Any]):
        """Store error information in database"""
        try:
            with engine.begin() as conn:
                # Create error logs table if it doesn't exist
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS error_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        component TEXT NOT NULL,
                        error_type TEXT NOT NULL,
                        error_message TEXT NOT NULL,
                        traceback TEXT,
                        config_hash TEXT,
                        context JSONB,
                        severity TEXT DEFAULT 'error'
                    )
                """))

                # Insert error record
                conn.execute(text("""
                    INSERT INTO error_logs
                    (component, error_type, error_message, traceback, config_hash, context, severity)
                    VALUES (:component, :error_type, :error_message, :traceback, :config_hash, :context, :severity)
                """), {
                    'component': error_info['component'],
                    'error_type': error_info['error_type'],
                    'error_message': error_info['error_message'],
                    'traceback': error_info['traceback'],
                    'config_hash': error_info['config_hash'],
                    'context': json.dumps(error_info['context']),
                    'severity': error_info.get('severity', 'error')
                })

        except Exception as db_error:
            # Don't let database errors break the error logging
            self.logger.error(f"Failed to store error in database: {db_error}")

    def get_recent_errors(self, limit: int = 50) -> list:
        """Get recent errors from database"""
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, timestamp, component, error_type, error_message, config_hash, context
                    FROM error_logs
                    ORDER BY timestamp DESC
                    LIMIT :limit
                """), {'limit': limit})

                return [dict(row._mapping) for row in result]
        except Exception as e:
            self.logger.error(f"Failed to retrieve errors: {e}")
            return []

class ErrorBoundary:
    """Context manager for error handling"""

    def __init__(self, component: str, context: Optional[Dict[str, Any]] = None):
        self.component = component
        self.context = context or {}
        self.error_handler = ErrorHandler()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error_handler.log_error(exc_val, self.context, self.component)
            return False  # Re-raise the exception
        return True

def handle_errors(component: str = "unknown"):
    """Decorator for consistent error handling"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            error_handler = ErrorHandler()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_handler.log_error(e, {
                    'function': func.__name__,
                    'args': str(args),
                    'kwargs': str(kwargs)
                }, component)
                raise
        return wrapper
    return decorator

# Global error handler instance
error_handler = ErrorHandler()

# Convenience functions
def log_error(error: Exception, context: Optional[Dict[str, Any]] = None, component: str = "unknown"):
    """Convenience function to log errors"""
    return error_handler.log_error(error, context, component)

def log_info(message: str, component: str = "unknown", context: Optional[Dict[str, Any]] = None):
    """Convenience function to log info messages"""
    return error_handler.log_info(message, component, context)

def log_warning(message: str, component: str = "unknown", context: Optional[Dict[str, Any]] = None):
    """Convenience function to log warning messages"""
    return error_handler.log_warning(message, component, context)
