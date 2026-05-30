"""Migration 0003: Add vehicle type and driver lifestyle/safety declaration fields to admin_users."""


def up(conn):
    with conn.cursor() as cur:
        for sql in [
            "ALTER TABLE admin_users ADD COLUMN vehicle_type VARCHAR(50) DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN uses_alcohol TINYINT(1) DEFAULT 0",
            "ALTER TABLE admin_users ADD COLUMN uses_cigarettes TINYINT(1) DEFAULT 0",
            "ALTER TABLE admin_users ADD COLUMN has_criminal_record TINYINT(1) DEFAULT 0",
            "ALTER TABLE admin_users ADD COLUMN emergency_contact_name VARCHAR(200) DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN emergency_contact_phone VARCHAR(50) DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN years_of_experience TINYINT DEFAULT 0",
        ]:
            try:
                cur.execute(sql)
            except Exception as e:
                if 'Duplicate column name' in str(e) or '1060' in str(e):
                    pass
                else:
                    raise
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for col in [
            'vehicle_type', 'uses_alcohol', 'uses_cigarettes',
            'has_criminal_record', 'emergency_contact_name',
            'emergency_contact_phone', 'years_of_experience',
        ]:
            try:
                cur.execute(f"ALTER TABLE admin_users DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
