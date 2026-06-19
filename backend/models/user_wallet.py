from datetime import datetime
from backend.models import db
from backend.utils.helpers import my_date_time


class UserWallet(db.Model):
    __tablename__ = 'user_wallets'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), unique=True, nullable=False)
    wallet_balance = db.Column(db.Numeric(10, 2), default=0)
    total_earnings = db.Column(db.Numeric(10, 2), default=0)
    stripe_customer_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_account_id = db.Column(db.String(255), unique=True, nullable=True)

    # Subscription earnings model (migration 0015)
    paid_balance = db.Column(db.Numeric(10, 2), default=0)        # settled, >24h, withdrawable
    unpaid_balance = db.Column(db.Numeric(10, 2), default=0)      # accruing within 24h
    reclaim_fee_rate = db.Column(db.Numeric(4, 2), default=0.10)  # early-withdraw fee (fraction)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'wallet_balance': float(self.wallet_balance) if self.wallet_balance else 0,
            'total_earnings': float(self.total_earnings) if self.total_earnings else 0,
            'paid_balance': float(self.paid_balance) if self.paid_balance else 0,
            'unpaid_balance': float(self.unpaid_balance) if self.unpaid_balance else 0,
            'reclaim_fee_rate': float(self.reclaim_fee_rate) if self.reclaim_fee_rate is not None else 0.10,
            'stripe_customer_id': self.stripe_customer_id,
            'stripe_account_id': self.stripe_account_id,
            'created_at': my_date_time(self.created_at),
            'updated_at': my_date_time(self.updated_at),
        }
