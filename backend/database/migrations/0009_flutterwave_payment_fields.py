"""Migration 0009: Add Flutterwave payment fields, remove Stripe-specific columns."""


def up(conn):
    with conn.cursor() as cur:

        # ── scheduled_bookings: FLW payment fields ──────────────────────────
        for sql in [
            "ALTER TABLE scheduled_bookings ADD COLUMN flw_tx_ref VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN flw_tx_id VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN flw_payment_url TEXT DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN flw_payment_type VARCHAR(100) DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN flw_payment_data JSON DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN flw_verified_at DATETIME DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN amount_ngn DECIMAL(12,2) DEFAULT 0",
        ]:
            try:
                cur.execute(sql)
            except Exception as e:
                if '1060' not in str(e) and 'Duplicate column' not in str(e):
                    raise

        # ── negotiations: FLW payment fields ────────────────────────────────
        for sql in [
            "ALTER TABLE negotiations ADD COLUMN flw_tx_ref VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE negotiations ADD COLUMN flw_tx_id VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE negotiations ADD COLUMN flw_payment_url TEXT DEFAULT NULL",
            "ALTER TABLE negotiations ADD COLUMN flw_payment_type VARCHAR(100) DEFAULT NULL",
            "ALTER TABLE negotiations ADD COLUMN flw_verified_at DATETIME DEFAULT NULL",
        ]:
            try:
                cur.execute(sql)
            except Exception as e:
                if '1060' not in str(e) and 'Duplicate column' not in str(e):
                    raise

        # ── payments: rename stripe ref column + add FLW fields ─────────────
        for sql in [
            "ALTER TABLE payments ADD COLUMN flw_reference VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE payments ADD COLUMN flw_tx_id VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE payments ADD COLUMN gateway VARCHAR(50) DEFAULT 'flutterwave'",
        ]:
            try:
                cur.execute(sql)
            except Exception as e:
                if '1060' not in str(e) and 'Duplicate column' not in str(e):
                    raise

        # ── payout_accounts: FLW bank account details ────────────────────────
        for sql in [
            "ALTER TABLE payout_accounts ADD COLUMN flw_bank_code VARCHAR(10) DEFAULT NULL",
            "ALTER TABLE payout_accounts ADD COLUMN flw_account_number VARCHAR(20) DEFAULT NULL",
            "ALTER TABLE payout_accounts ADD COLUMN flw_account_name VARCHAR(200) DEFAULT NULL",
            "ALTER TABLE payout_accounts ADD COLUMN flw_bank_name VARCHAR(200) DEFAULT NULL",
            "ALTER TABLE payout_accounts ADD COLUMN flw_verified TINYINT(1) DEFAULT 0",
            "ALTER TABLE payout_accounts ADD COLUMN flw_verified_at DATETIME DEFAULT NULL",
        ]:
            try:
                cur.execute(sql)
            except Exception as e:
                if '1060' not in str(e) and 'Duplicate column' not in str(e):
                    raise

        # ── payout_requests: FLW transfer fields ────────────────────────────
        for sql in [
            "ALTER TABLE payout_requests ADD COLUMN flw_transfer_id VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE payout_requests ADD COLUMN flw_reference VARCHAR(255) DEFAULT NULL",
            "ALTER TABLE payout_requests ADD COLUMN flw_transfer_status VARCHAR(50) DEFAULT NULL",
            "ALTER TABLE payout_requests ADD COLUMN flw_response_data JSON DEFAULT NULL",
        ]:
            try:
                cur.execute(sql)
            except Exception as e:
                if '1060' not in str(e) and 'Duplicate column' not in str(e):
                    raise

    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for table, cols in [
            ('scheduled_bookings', ['flw_tx_ref', 'flw_tx_id', 'flw_payment_url', 'flw_payment_type', 'flw_payment_data', 'flw_verified_at', 'amount_ngn']),
            ('negotiations', ['flw_tx_ref', 'flw_tx_id', 'flw_payment_url', 'flw_payment_type', 'flw_verified_at']),
            ('payments', ['flw_reference', 'flw_tx_id', 'gateway']),
            ('payout_accounts', ['flw_bank_code', 'flw_account_number', 'flw_account_name', 'flw_bank_name', 'flw_verified', 'flw_verified_at']),
            ('payout_requests', ['flw_transfer_id', 'flw_reference', 'flw_transfer_status', 'flw_response_data']),
        ]:
            for col in cols:
                try:
                    cur.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
                except Exception:
                    pass
    conn.commit()
