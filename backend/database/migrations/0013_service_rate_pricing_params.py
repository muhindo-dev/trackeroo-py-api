"""Migration 0013: add client pricing-formula parameters to service_rates.

PRICE = base + p*extra_km + q*peak_min + r*offpeak_min
             + s*loading_overrun + t*completion_overrun
"""


def _add_col(cur, table, col, ddl):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
        (table, col),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


COLUMNS = [
    ('p_extra_km', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('q_peak_minute', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('r_offpeak_minute', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('s_loading_overrun', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('t_completion_overrun', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('free_km', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('peak_start_hour', 'INT DEFAULT 7'),
    ('peak_end_hour', 'INT DEFAULT 10'),
    ('peak_start_hour_pm', 'INT DEFAULT 16'),
    ('peak_end_hour_pm', 'INT DEFAULT 20'),
]


def up(conn):
    with conn.cursor() as cur:
        for col, ddl in COLUMNS:
            _add_col(cur, 'service_rates', col, ddl)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for col, _ in COLUMNS:
            cur.execute(f"ALTER TABLE service_rates DROP COLUMN {col}")
    conn.commit()
