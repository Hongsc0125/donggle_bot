"""
Script to create and populate alert tables in the database.
Run this script once to set up the alert system.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db.session import SessionLocal
import logging
from datetime import datetime, time

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alert-setup")

# SQL to create alert table
CREATE_ALERT_TABLE = text("""
CREATE TABLE IF NOT EXISTS alert (
    alert_id VARCHAR(10) PRIMARY KEY,
    alert_type VARCHAR(10) NOT NULL,
    alert_time TIME NOT NULL,
    create_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    interval VARCHAR(10) DEFAULT 'day',
    update_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# SQL to create alert_user table
CREATE_ALERT_USER_TABLE = text("""
CREATE TABLE IF NOT EXISTS alert_user (
    user_id VARCHAR(20) NOT NULL,
    alert_id VARCHAR(10) NOT NULL,
    create_dt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, alert_id)
);
""")

# SQL to insert default alerts
INSERT_DEFAULT_ALERTS = text("""
INSERT INTO alert (alert_id, alert_type, alert_time, interval)
VALUES
    ('AL00004', 'boss', '12:00:00', 'day'),
    ('AL00005', 'boss', '18:00:00', 'day'),
    ('AL00006', 'boss', '20:00:00', 'day'),
    ('AL00007', 'boss', '22:00:00', 'day'),
    ('AL00008', 'barrier', '00:00:00', 'day'),
    ('AL00009', 'barrier', '03:00:00', 'day'),
    ('AL00010', 'barrier', '06:00:00', 'day'),
    ('AL00011', 'barrier', '09:00:00', 'day'),
    ('AL00012', 'barrier', '12:00:00', 'day'),
    ('AL00013', 'barrier', '15:00:00', 'day'),
    ('AL00014', 'barrier', '18:00:00', 'day'),
    ('AL00015', 'barrier', '21:00:00', 'day'),
    ('AL00016', 'mon', '00:00:00', 'week'),
    ('AL00017', 'tue', '00:00:00', 'week'),
    ('AL00018', 'wed', '00:00:00', 'week'),
    ('AL00019', 'thu', '00:00:00', 'week'),
    ('AL00020', 'fri', '00:00:00', 'week'),
    ('AL00021', 'sat', '00:00:00', 'week'),
    ('AL00022', 'sun', '00:00:00', 'week')
ON CONFLICT (alert_id) DO NOTHING;
""")

def main():
    """Create alert tables and insert default data"""
    logger.info("Starting alert system setup...")
    
    with SessionLocal() as db:
        try:
            # Create tables
            logger.info("Creating alert table...")
            db.execute(CREATE_ALERT_TABLE)
            
            logger.info("Creating alert_user table...")
            db.execute(CREATE_ALERT_USER_TABLE)
            
            # Insert default data
            logger.info("Inserting default alerts...")
            db.execute(INSERT_DEFAULT_ALERTS)
            
            # Commit changes
            db.commit()
            logger.info("Alert system setup completed successfully!")
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error setting up alert system: {e}")
            raise

if __name__ == "__main__":
    main()
