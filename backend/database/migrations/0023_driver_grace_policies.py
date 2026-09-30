def up(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS driver_grace_policies (
            id BIGINT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(120) NOT NULL,
            plan_id BIGINT NOT NULL, start_at DATETIME NOT NULL, end_at DATETIME NOT NULL,
            duration_days INT NOT NULL DEFAULT 7, apply_to_new_drivers TINYINT NOT NULL DEFAULT 1,
            apply_to_existing TINYINT NOT NULL DEFAULT 0, max_redemptions INT NULL,
            redemption_count INT NOT NULL DEFAULT 0, is_active TINYINT NOT NULL DEFAULT 1,
            notes TEXT NULL, created_by BIGINT NULL, created_at DATETIME, updated_at DATETIME,
            INDEX idx_grace_window (is_active, start_at, end_at)
        ) ENGINE=InnoDB""")
        for sql in ("ALTER TABLE subscriptions ADD COLUMN grace_policy_id BIGINT NULL",
                    "ALTER TABLE subscriptions ADD COLUMN is_grace TINYINT NOT NULL DEFAULT 0"):
            try: cur.execute(sql)
            except Exception as exc:
                if 'Duplicate column' not in str(exc): raise
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute('DROP TABLE IF EXISTS driver_grace_policies')
        for col in ('grace_policy_id', 'is_grace'):
            try: cur.execute(f'ALTER TABLE subscriptions DROP COLUMN {col}')
            except Exception: pass
    conn.commit()
