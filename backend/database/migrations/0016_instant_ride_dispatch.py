"""Migration 0016: V2 instant-ride dispatch.

- admin_users.live_service_group  — what the driver went live for (Boda/Special Hire/Truck)
- negotiations.payment_method     — MM / Visa / Cash (data collection only)
- negotiations.ride_source        — 'instant' rides come from the auto-dispatch engine
- driver_ratings.negotiation_id   — allow rating instant rides (was booking-only)
- ride_dispatches                 — ranked candidate list + offer state per ride
"""


def _add_col(cur, table, col, ddl):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
        (table, col),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def up(conn):
    with conn.cursor() as cur:
        _add_col(cur, 'admin_users', 'live_service_group', "VARCHAR(50) NULL")
        _add_col(cur, 'negotiations', 'payment_method', "VARCHAR(20) NULL")
        _add_col(cur, 'negotiations', 'ride_source', "VARCHAR(20) DEFAULT 'app'")
        _add_col(cur, 'driver_ratings', 'negotiation_id', "BIGINT NULL")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ride_dispatches (
                id               BIGINT PRIMARY KEY AUTO_INCREMENT,
                negotiation_id   BIGINT NOT NULL,
                customer_id      BIGINT NULL,
                category_id      BIGINT NULL,
                service_group    VARCHAR(50) NULL,
                candidates       TEXT,
                current_index    INT DEFAULT 0,
                offer_expires_at DATETIME NULL,
                status           VARCHAR(20) DEFAULT 'searching',
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_dispatch_negotiation (negotiation_id),
                KEY idx_dispatch_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS ride_dispatches")
        for table, col in (
            ('admin_users', 'live_service_group'),
            ('negotiations', 'payment_method'),
            ('negotiations', 'ride_source'),
            ('driver_ratings', 'negotiation_id'),
        ):
            try:
                cur.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
