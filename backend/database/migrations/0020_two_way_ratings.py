"""Migration 0020: let a driver rate the customer too.

driver_ratings previously only ever meant "customer rated driver". A single
`rated_by` marker turns the same table into a two-way record without a second
table or a second code path.
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
        _add_col(cur, 'driver_ratings', 'rated_by', "VARCHAR(10) NOT NULL DEFAULT 'customer'")
        # Existing rows are all customer→driver.
        cur.execute("UPDATE driver_ratings SET rated_by = 'customer' WHERE rated_by IS NULL")
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("ALTER TABLE driver_ratings DROP COLUMN rated_by")
        except Exception:
            pass
    conn.commit()
