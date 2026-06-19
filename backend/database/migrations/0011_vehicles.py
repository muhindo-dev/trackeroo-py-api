"""Migration 0011: vehicles — registered vehicles owned by a Vehicle Owner and
optionally linked to a driver; verified against an uploaded log book."""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id                  BIGINT PRIMARY KEY AUTO_INCREMENT,
                owner_id            BIGINT NOT NULL,
                driver_id           BIGINT NULL,
                category_id         BIGINT NULL,
                type                VARCHAR(100) NULL,
                model               VARCHAR(150) NULL,
                reg_no              VARCHAR(100) NULL,
                colour              VARCHAR(60) NULL,
                insurance_status    VARCHAR(60) DEFAULT 'Unknown',
                logbook_photo       TEXT,
                photo               TEXT,
                verification_status VARCHAR(30) DEFAULT 'Pending',
                is_active           TINYINT(1) DEFAULT 1,
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_vehicles_owner (owner_id),
                KEY idx_vehicles_driver (driver_id),
                KEY idx_vehicles_category (category_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS vehicles")
    conn.commit()
