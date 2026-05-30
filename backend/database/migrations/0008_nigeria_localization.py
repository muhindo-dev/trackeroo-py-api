"""Migration 0008: Nigeria localization — currency, country defaults, clean legacy Canada data."""


def up(conn):
    with conn.cursor() as cur:
        # 1. Add currency column to service_rates
        try:
            cur.execute(
                "ALTER TABLE service_rates ADD COLUMN currency VARCHAR(5) DEFAULT 'NGN'"
            )
        except Exception as e:
            if '1060' not in str(e) and 'Duplicate column' not in str(e):
                raise

        # 2. Set all existing service_rates to NGN
        cur.execute("UPDATE service_rates SET currency = 'NGN'")

        # 3. Add currency to payout_accounts (default NGN)
        try:
            cur.execute(
                "ALTER TABLE payout_accounts ADD COLUMN currency VARCHAR(5) DEFAULT 'NGN'"
            )
        except Exception as e:
            if '1060' not in str(e) and 'Duplicate column' not in str(e):
                raise
        cur.execute("UPDATE payout_accounts SET default_currency = 'NGN' WHERE default_currency = 'CAD'")

        # 4. Update existing admin_users: Canada → Nigeria defaults
        cur.execute("""
            UPDATE admin_users
            SET country_name = 'Nigeria',
                country_code = '+234',
                country_short_name = 'NG'
            WHERE country_name = 'Canada' OR country_code = '+1'
        """)

        # 5. Clear and reseed popular_locations with Nigerian cities
        cur.execute("DELETE FROM popular_locations")
        popular = [
            ('Murtala Muhammed International Airport (MMIA)', 'Airport Rd, Ikeja, Lagos', 6.5774, 3.3212, 'Lagos', 'Airport', 1),
            ('Nnamdi Azikiwe International Airport', 'Airport Rd, Garki, Abuja', 9.0063, 7.2631, 'Abuja', 'Airport', 2),
            ('Murtala Muhammed Airport Terminal 2 (MMA2)', 'Airport Road, Ikeja, Lagos', 6.5780, 3.3225, 'Lagos', 'Airport', 3),
            ('Transcorp Hilton Hotel, Abuja', '1 Aguiyi Ironsi St, Maitama, Abuja', 9.0520, 7.4887, 'Abuja', 'Hotel', 4),
            ('Eko Hotel & Suites', 'Plot 1415, Adetokunbo Ademola St, Victoria Island, Lagos', 6.4349, 3.4208, 'Lagos', 'Hotel', 5),
            ('Ikeja City Mall', '80 Obafemi Awolowo Way, Ikeja, Lagos', 6.5884, 3.3584, 'Lagos', 'Mall', 6),
            ('University of Lagos (UNILAG)', 'Akoka, Yaba, Lagos', 6.5162, 3.3975, 'Lagos', 'University', 7),
            ('University of Abuja', 'Airport Rd, Gwagwa, Abuja', 9.0119, 7.3531, 'Abuja', 'University', 8),
            ('Lagos Island General Hospital', '1 Broad St, Lagos Island, Lagos', 6.4569, 3.3947, 'Lagos', 'Hospital', 9),
            ('National Hospital Abuja', 'Plot 132, Central Business District, Abuja', 9.0600, 7.4840, 'Abuja', 'Hospital', 10),
            ('Balogun Market, Lagos Island', 'Balogun St, Lagos Island, Lagos', 6.4542, 3.3945, 'Lagos', 'Market', 11),
            ('Wuse Market, Abuja', 'Wuse Zone 5, Abuja', 9.0556, 7.4801, 'Abuja', 'Market', 12),
            ('Lekki Phase 1 Gate, Lagos', 'Admiralty Way, Lekki Phase 1, Lagos', 6.4445, 3.4730, 'Lagos', 'Landmark', 13),
            ('Port Harcourt International Airport', 'Port Harcourt, Rivers State', 5.0155, 6.9496, 'Port Harcourt', 'Airport', 14),
            ('Ibadan Central Bus Station', 'Challenge Area, Ibadan, Oyo State', 7.3775, 3.8965, 'Ibadan', 'Transit', 15),
        ]
        cur.executemany("""
            INSERT INTO popular_locations
              (name, address, lat, lng, city, category, is_active, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
        """, popular)

        # 6. Clear and reseed service_rates with NGN pricing
        cur.execute("DELETE FROM service_rates")
        rates = [
            ('Truckeroo', 'Any',        500,   150,  20,  1.00,  800,  'NGN', 'Standard rideshare seat booking'),
            ('Special Car Hire', 'Sedan', 1500, 200,  30,  1.00, 2000,  'NGN', 'Premium sedan private hire'),
            ('Special Car Hire', 'SUV',  2500,  250,  40,  1.00, 3000,  'NGN', 'Premium SUV private hire'),
            ('Airport Pickup', 'Any',   8000,  200,  30,  1.00,10000,  'NGN', 'Airport transfer standard'),
            ('Airport Pickup', 'SUV',  12000,  250,  40,  1.00,15000,  'NGN', 'Airport transfer SUV'),
            ('Movers', 'Van/Truck',    15000,  500,  80,  1.00,20000,  'NGN', 'Furniture & appliance moving (van/truck)'),
            ('Movers', 'Pickup',       10000,  400,  60,  1.00,12000,  'NGN', 'Pickup truck movers'),
            ('Courier', 'Any',          1000,  100,  15,  1.00,  800,  'NGN', 'Parcel & document delivery'),
            ('Courier', 'Motorcycle',    500,   80,  10,  1.00,  500,  'NGN', 'Motorcycle courier — fastest option'),
        ]
        cur.executemany("""
            INSERT INTO service_rates
              (service_type, vehicle_type, base_rate_cad, per_km_rate_cad,
               per_minute_rate_cad, surge_multiplier, minimum_fare_cad, currency, is_active, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
        """, rates)

    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        # Restore Canada defaults
        cur.execute("""
            UPDATE admin_users
            SET country_name = 'Canada', country_code = '+1', country_short_name = 'CA'
        """)
        cur.execute("DELETE FROM popular_locations")
        cur.execute("DELETE FROM service_rates")
        try:
            cur.execute("ALTER TABLE service_rates DROP COLUMN currency")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE payout_accounts DROP COLUMN currency")
        except Exception:
            pass
    conn.commit()
