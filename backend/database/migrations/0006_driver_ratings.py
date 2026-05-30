"""Migration 0006: Create driver_ratings table for post-trip customer ratings."""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS driver_ratings (
                id          BIGINT PRIMARY KEY AUTO_INCREMENT,
                customer_id BIGINT NOT NULL,
                driver_id   BIGINT NOT NULL,
                booking_id  BIGINT NOT NULL,
                rating      TINYINT NOT NULL,
                comment     TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_customer_booking (customer_id, booking_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS driver_ratings")
    conn.commit()
