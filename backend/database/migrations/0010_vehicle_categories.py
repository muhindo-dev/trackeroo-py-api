"""Migration 0010: vehicle_categories — admin-registered categories used for
vehicle registration and as the basis of the pricing engine."""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vehicle_categories (
                id                  BIGINT PRIMARY KEY AUTO_INCREMENT,
                name                VARCHAR(100) NOT NULL,
                code                VARCHAR(50) NOT NULL,
                service_group       VARCHAR(50) DEFAULT 'Truck',
                wheels              INT NULL,
                description         TEXT,
                icon                VARCHAR(100) NULL,
                min_price           DECIMAL(12,2) DEFAULT 0.00,
                est_loading_minutes INT DEFAULT 0,
                per_km_rate         DECIMAL(12,2) DEFAULT 0.00,
                is_luxury           TINYINT(1) DEFAULT 0,
                sort_order          INT DEFAULT 0,
                is_active           TINYINT(1) DEFAULT 1,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_vehicle_category_code (code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS vehicle_categories")
    conn.commit()
