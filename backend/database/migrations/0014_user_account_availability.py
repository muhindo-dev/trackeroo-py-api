"""Migration 0014: account model (Customer/Driver/VehicleOwner) + availability
matching columns on admin_users."""


def _add_col(cur, table, col, ddl):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
        (table, col),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


COLUMNS = [
    ('account_type', "VARCHAR(30) DEFAULT 'Customer'"),
    ('owner_kind', 'VARCHAR(30) NULL'),
    ('company_id', 'BIGINT NULL'),
    ('vehicle_count', 'INT DEFAULT 0'),
    ('payment_period', 'VARCHAR(20) NULL'),
    ('available_from', 'DATETIME NULL'),
    ('busy_until', 'DATETIME NULL'),
]


def up(conn):
    with conn.cursor() as cur:
        for col, ddl in COLUMNS:
            _add_col(cur, 'admin_users', col, ddl)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for col, _ in COLUMNS:
            cur.execute(f"ALTER TABLE admin_users DROP COLUMN {col}")
    conn.commit()
