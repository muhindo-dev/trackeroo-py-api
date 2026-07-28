"""Migration 0012: subscription_plans + subscriptions — Truckfully's payment mode
is subscription: drivers pay a recurring fee and keep their trip earnings."""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id            BIGINT PRIMARY KEY AUTO_INCREMENT,
                name          VARCHAR(100) NOT NULL,
                code          VARCHAR(50) NOT NULL,
                period        VARCHAR(20) DEFAULT 'Weekly',
                duration_days INT DEFAULT 7,
                amount        DECIMAL(12,2) DEFAULT 0.00,
                currency      VARCHAR(5) DEFAULT 'NGN',
                description   TEXT,
                sort_order    INT DEFAULT 0,
                is_active     TINYINT(1) DEFAULT 1,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_subscription_plan_code (code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id         BIGINT PRIMARY KEY AUTO_INCREMENT,
                driver_id  BIGINT NOT NULL,
                plan_id    BIGINT NULL,
                payment_id BIGINT NULL,
                tx_ref     VARCHAR(120) NULL,
                amount     DECIMAL(12,2) DEFAULT 0.00,
                currency   VARCHAR(5) DEFAULT 'NGN',
                status     VARCHAR(20) DEFAULT 'pending',
                start_at   DATETIME NULL,
                end_at     DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_subscriptions_driver (driver_id),
                KEY idx_subscriptions_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS subscriptions")
        cur.execute("DROP TABLE IF EXISTS subscription_plans")
    conn.commit()
