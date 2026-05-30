"""Migration 0004: Create popular_locations table for admin-managed key places."""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS popular_locations (
                id          BIGINT PRIMARY KEY AUTO_INCREMENT,
                name        VARCHAR(200) NOT NULL,
                address     VARCHAR(500),
                lat         DECIMAL(10,7) NOT NULL,
                lng         DECIMAL(10,7) NOT NULL,
                city        VARCHAR(100) DEFAULT 'Toronto',
                category    VARCHAR(100) DEFAULT 'Other',
                is_active   TINYINT(1) DEFAULT 1,
                sort_order  INT DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS popular_locations")
    conn.commit()
