"""Migration 0015: subscription earnings model on user_wallets — paid vs unpaid
balance and an early-withdrawal reclaim fee rate."""


def _add_col(cur, table, col, ddl):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
        (table, col),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


COLUMNS = [
    ('paid_balance', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('unpaid_balance', 'DECIMAL(10,2) DEFAULT 0.00'),
    ('reclaim_fee_rate', 'DECIMAL(4,2) DEFAULT 0.10'),
]


def up(conn):
    with conn.cursor() as cur:
        for col, ddl in COLUMNS:
            _add_col(cur, 'user_wallets', col, ddl)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for col, _ in COLUMNS:
            cur.execute(f"ALTER TABLE user_wallets DROP COLUMN {col}")
    conn.commit()
