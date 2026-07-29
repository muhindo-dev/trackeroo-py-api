"""Migration 0017: Book for later (scheduled instant rides).

- negotiations.scheduled_at    — when the customer wants to be picked up
- negotiations.schedule_note   — optional note to the driver
- ride_dispatches.scheduled_at — dispatch stays 'scheduled' until this moment
"""


def _add_col(cur, table, col, ddl):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s""",
        (table, col),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _add_index(cur, table, name, cols):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s""",
        (table, name),
    )
    if cur.fetchone()[0] == 0:
        cur.execute(f"CREATE INDEX {name} ON {table} ({cols})")


def up(conn):
    with conn.cursor() as cur:
        _add_col(cur, 'negotiations', 'scheduled_at', "DATETIME NULL")
        _add_col(cur, 'negotiations', 'schedule_note', "TEXT NULL")
        _add_col(cur, 'ride_dispatches', 'scheduled_at', "DATETIME NULL")
        # The due-dispatch sweeper scans on (status, scheduled_at).
        _add_index(cur, 'ride_dispatches', 'idx_dispatch_scheduled', 'status, scheduled_at')
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("DROP INDEX idx_dispatch_scheduled ON ride_dispatches")
        except Exception:
            pass
        for table, col in (
            ('negotiations', 'scheduled_at'),
            ('negotiations', 'schedule_note'),
            ('ride_dispatches', 'scheduled_at'),
        ):
            try:
                cur.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
