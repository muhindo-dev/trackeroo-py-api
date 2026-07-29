"""Migration 0018: driver trip progress + ride chat link.

- negotiations.driver_arrived_at — driver reached the pickup point
- negotiations.started_at        — trip actually began
- negotiations.completed_at      — trip finished
- negotiations.cancelled_by      — 'driver' | 'customer' | 'system'
- negotiations.cancel_reason     — free text shown to the other party
- negotiations.chat_head_id      — the conversation for this ride

Progress timestamps are separate from `status` on purpose: status is a small
state machine the whole app switches on, while "arrived" is an event both
sides need to see without inventing a new state that older clients would not
understand.
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
        _add_col(cur, 'negotiations', 'driver_arrived_at', "DATETIME NULL")
        _add_col(cur, 'negotiations', 'started_at', "DATETIME NULL")
        _add_col(cur, 'negotiations', 'completed_at', "DATETIME NULL")
        _add_col(cur, 'negotiations', 'cancelled_by', "VARCHAR(20) NULL")
        _add_col(cur, 'negotiations', 'cancel_reason', "TEXT NULL")
        _add_col(cur, 'negotiations', 'chat_head_id', "BIGINT NULL")
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for col in ('driver_arrived_at', 'started_at', 'completed_at',
                    'cancelled_by', 'cancel_reason', 'chat_head_id'):
            try:
                cur.execute(f"ALTER TABLE negotiations DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
