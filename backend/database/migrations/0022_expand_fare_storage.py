"""Widen fare and settlement storage without changing existing values or units.

Apply before accepting larger fares. Narrowing rollback is deliberately refused
because it could truncate fares created after this migration.
"""

COLUMNS = {
    'negotiations': {'initial_price': 'BIGINT', 'agreed_price': 'DECIMAL(30,2)'},
    'negotiation_records': {'price': 'BIGINT'},
    'trips': {'price': 'BIGINT'},
    'trip_bookings': {'price': 'BIGINT'},
    'scheduled_bookings': {'agreed_price_cad': 'DECIMAL(30,2)', 'amount_ngn': 'DECIMAL(30,2)'},
    'user_wallets': {c: 'DECIMAL(30,2)' for c in
                     ('wallet_balance', 'total_earnings', 'paid_balance', 'unpaid_balance')},
    'transactions': {c: 'DECIMAL(30,2)' for c in ('amount', 'balance_before', 'balance_after')},
    'payments': {c: 'DECIMAL(30,2)' for c in ('amount', 'service_fee', 'driver_amount')},
    'payout_requests': {c: 'DECIMAL(30,2)' for c in ('amount', 'fee_amount', 'net_amount')},
}


def up(conn):
    with conn.cursor() as cur:
        for table, columns in COLUMNS.items():
            changes = []
            for column, sql_type in columns.items():
                cur.execute(
                    "SELECT IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                    (table, column))
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError(f"Missing required fare column {table}.{column}")
                nullable, default, comment = row
                definition = f"MODIFY COLUMN `{column}` {sql_type}"
                definition += ' NULL' if nullable == 'YES' else ' NOT NULL'
                if default is not None:
                    # MySQL rejects decimal defaults (for example 0.00) on
                    # integer columns when widening legacy fare fields.
                    normalized = default
                    if sql_type.upper().startswith(('BIGINT', 'INT')):
                        try:
                            normalized = str(int(float(default)))
                        except (TypeError, ValueError):
                            normalized = default
                    definition += ' DEFAULT ' + conn.escape(normalized)
                # Omit an explicit DEFAULT NULL for nullable legacy columns;
                # MariaDB/MySQL variants can reject it while changing types.
                if comment:
                    definition += ' COMMENT ' + conn.escape(comment)
                changes.append(definition)
            cur.execute(f"ALTER TABLE `{table}` " + ', '.join(changes))
    conn.commit()


def down(conn):
    raise RuntimeError('Fare columns cannot be narrowed safely; retain the widened schema.')
