"""Migration 0021: stop one rating per customer from blocking all the rest.

driver_ratings had UNIQUE(customer_id, booking_id). Instant rides carry no
booking, so every one of them wrote booking_id = 0 — which made the pair
(customer, 0) unique across a customer's entire history. In practice a
customer could rate exactly one instant ride, ever; the second attempt was a
duplicate-key 500.

Fix: instant-ride ratings store booking_id = NULL (MySQL unique indexes allow
many NULLs, so real bookings stay protected), and a new unique index enforces
what actually matters — one rating per ride per direction.
"""


def up(conn):
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE driver_ratings MODIFY booking_id BIGINT NULL")
        cur.execute("""UPDATE driver_ratings SET booking_id = NULL
                       WHERE booking_id = 0 AND negotiation_id IS NOT NULL""")
        cur.execute(
            """SELECT COUNT(*) FROM information_schema.statistics
               WHERE table_schema = DATABASE() AND table_name = 'driver_ratings'
                 AND index_name = 'uq_rating_per_ride'""")
        if cur.fetchone()[0] == 0:
            cur.execute("""CREATE UNIQUE INDEX uq_rating_per_ride
                           ON driver_ratings (negotiation_id, rated_by)""")
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("DROP INDEX uq_rating_per_ride ON driver_ratings")
        except Exception:
            pass
        try:
            cur.execute("UPDATE driver_ratings SET booking_id = 0 WHERE booking_id IS NULL")
            cur.execute("ALTER TABLE driver_ratings MODIFY booking_id BIGINT NOT NULL")
        except Exception:
            pass
    conn.commit()
