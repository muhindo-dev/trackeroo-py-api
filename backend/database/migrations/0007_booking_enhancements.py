"""Migration 0007: Enhance scheduled_bookings with KG weight, ETA, distance, driver selection flag."""


def up(conn):
    with conn.cursor() as cur:
        for sql in [
            "ALTER TABLE scheduled_bookings ADD COLUMN luggage_weight_kg DECIMAL(8,2) DEFAULT 0",
            "ALTER TABLE scheduled_bookings ADD COLUMN expected_arrival_at DATETIME DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN driver_selected_by_customer TINYINT(1) DEFAULT 0",
            "ALTER TABLE scheduled_bookings ADD COLUMN distance_km DECIMAL(10,3) DEFAULT 0",
            "ALTER TABLE scheduled_bookings ADD COLUMN estimated_duration_minutes INT DEFAULT 0",
            "ALTER TABLE scheduled_bookings ADD COLUMN agreed_price_cad DECIMAL(8,2) DEFAULT 0",
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
            'luggage_weight_kg', 'expected_arrival_at',
            'driver_selected_by_customer', 'distance_km',
            'estimated_duration_minutes', 'agreed_price_cad',
        ]:
            try:
                cur.execute(f"ALTER TABLE scheduled_bookings DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
