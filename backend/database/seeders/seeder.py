"""Database seeder for Truckfully's new commercial model.

Seeds (idempotently, keyed on unique codes/types):
  * vehicle_categories  — the client's truck categories + Boda + Special Hire cars
  * subscription_plans  — Instant / Daily / Weekly / Monthly
  * service_rates       — time-based pricing coefficients (q, r, s, t) per service group

Pricing model used by the engine:
    base_price = category.min_price
    p          = category.per_km_rate            (charge per extra km)
    q, r, s, t = service_rates row for the group  (time-based coefficients)

    PRICE = base + p*extra_km + q*peak_min + r*offpeak_min
                 + s*loading_overrun_min + t*completion_overrun_min
"""

# name, code, service_group, wheels, min_price, est_loading_minutes, per_km_rate, is_luxury, sort_order
VEHICLE_CATEGORIES = [
    ('Small Truck',  'small_truck',   'Truck',        4,  15000, 20, 400, 0, 10),
    ('Medium Truck', 'medium_truck',  'Truck',        6,  25000, 30, 600, 0, 20),
    ('Average Truck', 'average_truck', 'Truck',       10, 40000, 45, 900, 0, 30),
    ('Big Truck',    'big_truck',     'Truck',        6,  35000, 40, 800, 0, 40),
    ('Trailer',      'trailer',       'Truck',        22, 80000, 60, 1500, 0, 50),
    ('Boda Boda',    'boda',          'Boda',         2,  500,   2,  150, 0, 60),
    ('Normal Ride',  'special_normal', 'Special Hire', 4, 2000,  5,  250, 0, 70),
    ('Luxury Ride',  'special_luxury', 'Special Hire', 4, 5000,  5,  500, 1, 80),
]

# name, code, period, duration_days, amount, description, sort_order
SUBSCRIPTION_PLANS = [
    ('Instant',  'instant', 'Instant',  1,  18000,  'Pay-as-you-go daily access', 10),
    ('Daily',    'daily',   'Daily',    1,  20000,  'Drive for 1 day', 20),
    ('Weekly',   'weekly',  'Weekly',   7,  100000, 'Best value — drive for 7 days', 30),
    ('Monthly',  'monthly', 'Monthly',  30, 350000, 'Drive for 30 days', 40),
]

# service_type, base, per_km, q_peak, r_offpeak, s_loading, t_completion, free_km
SERVICE_GROUP_RATES = [
    ('Boda',         0, 0, 30,  15, 20,  25, 0),
    ('Special Hire', 0, 0, 60,  30, 40,  50, 0),
    ('Truck',        0, 0, 120, 60, 100, 120, 0),
]


def run(conn):
    with conn.cursor() as cur:
        # ---- Vehicle categories ----
        for (name, code, group, wheels, min_price, loading, per_km, luxury, order) in VEHICLE_CATEGORIES:
            cur.execute(
                """
                INSERT INTO vehicle_categories
                    (name, code, service_group, wheels, min_price, est_loading_minutes,
                     per_km_rate, is_luxury, sort_order, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    name=VALUES(name), service_group=VALUES(service_group), wheels=VALUES(wheels),
                    min_price=VALUES(min_price), est_loading_minutes=VALUES(est_loading_minutes),
                    per_km_rate=VALUES(per_km_rate), is_luxury=VALUES(is_luxury),
                    sort_order=VALUES(sort_order)
                """,
                (name, code, group, wheels, min_price, loading, per_km, luxury, order),
            )

        # ---- Subscription plans ----
        for (name, code, period, days, amount, desc, order) in SUBSCRIPTION_PLANS:
            cur.execute(
                """
                INSERT INTO subscription_plans
                    (name, code, period, duration_days, amount, currency, description, sort_order, is_active)
                VALUES (%s, %s, %s, %s, %s, 'NGN', %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    name=VALUES(name), period=VALUES(period), duration_days=VALUES(duration_days),
                    amount=VALUES(amount), description=VALUES(description), sort_order=VALUES(sort_order)
                """,
                (name, code, period, days, amount, desc, order),
            )

        # ---- Service-group time coefficients ----
        for (stype, base, per_km, q, r, s, t, free_km) in SERVICE_GROUP_RATES:
            cur.execute(
                "SELECT id FROM service_rates WHERE service_type=%s AND vehicle_type='Any'",
                (stype,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE service_rates
                       SET base_rate_cad=%s, per_km_rate_cad=%s, q_peak_minute=%s,
                           r_offpeak_minute=%s, s_loading_overrun=%s, t_completion_overrun=%s,
                           free_km=%s, is_active=1
                     WHERE id=%s
                    """,
                    (base, per_km, q, r, s, t, free_km, row[0]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO service_rates
                        (service_type, vehicle_type, base_rate_cad, per_km_rate_cad, currency,
                         is_active, q_peak_minute, r_offpeak_minute, s_loading_overrun,
                         t_completion_overrun, free_km)
                    VALUES (%s, 'Any', %s, %s, 'NGN', 1, %s, %s, %s, %s, %s)
                    """,
                    (stype, base, per_km, q, r, s, t, free_km),
                )

    conn.commit()
    print("  Seeded vehicle categories, subscription plans, and service-group rates.")
