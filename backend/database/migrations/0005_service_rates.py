"""Migration 0005: Create service_rates table for admin-controlled pricing per service/vehicle type."""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS service_rates (
                id                  BIGINT PRIMARY KEY AUTO_INCREMENT,
                service_type        VARCHAR(100) NOT NULL,
                vehicle_type        VARCHAR(100) DEFAULT 'Any',
                base_rate_cad       DECIMAL(8,2) DEFAULT 0.00,
                per_km_rate_cad     DECIMAL(8,2) DEFAULT 0.00,
                per_minute_rate_cad DECIMAL(8,2) DEFAULT 0.00,
                surge_multiplier    DECIMAL(4,2) DEFAULT 1.00,
                minimum_fare_cad    DECIMAL(8,2) DEFAULT 0.00,
                is_active           TINYINT(1) DEFAULT 1,
                notes               TEXT,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS service_rates")
    conn.commit()
