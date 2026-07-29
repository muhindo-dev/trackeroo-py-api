"""Migration 0019: track when a driver's location was last reported.

`ready_for_trip='Yes'` alone is not proof a driver is reachable: a driver who
force-quits the app stays flagged online forever, absorbs dispatch offers and
never answers — each dead session burning a full offer window before the
cascade moves on. Dispatch now also requires a recent location report.

Backfilled from updated_at so existing rows are not treated as fresh forever.
"""


def _add_col(cur, table, col, ddl):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
        (table, col),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        return True
    return False


def up(conn):
    with conn.cursor() as cur:
        added = _add_col(cur, 'admin_users', 'location_updated_at', "DATETIME NULL")
        if added:
            cur.execute("""UPDATE admin_users
                           SET location_updated_at = updated_at
                           WHERE current_latitude IS NOT NULL""")
        cur.execute(
            """SELECT COUNT(*) FROM information_schema.statistics
               WHERE table_schema = DATABASE() AND table_name = 'admin_users'
                 AND index_name = 'idx_driver_dispatch'""")
        if cur.fetchone()[0] == 0:
            cur.execute("""CREATE INDEX idx_driver_dispatch
                           ON admin_users (ready_for_trip, user_type, location_updated_at)""")
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("DROP INDEX idx_driver_dispatch ON admin_users")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE admin_users DROP COLUMN location_updated_at")
        except Exception:
            pass
    conn.commit()
