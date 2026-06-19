from datetime import datetime, timedelta
from backend.models import db


class SubscriptionPlan(db.Model):
    """A driver subscription plan. Payment mode for Truckeroo is subscription:
    drivers pay a recurring fee and keep their trip earnings.
    """

    __tablename__ = 'subscription_plans'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), nullable=False)  # instant/daily/weekly/monthly
    period = db.Column(db.String(20), default='Weekly')  # Instant/Daily/Weekly/Monthly
    duration_days = db.Column(db.Integer, default=7)
    amount = db.Column(db.Numeric(12, 2), default=0.00)
    currency = db.Column(db.String(5), default='NGN')
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.SmallInteger, default=1)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def active():
        return SubscriptionPlan.query.filter_by(is_active=1).order_by(
            SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()
        ).all()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'period': self.period,
            'duration_days': self.duration_days or 0,
            'amount': float(self.amount or 0),
            'currency': self.currency or 'NGN',
            'description': self.description,
            'sort_order': self.sort_order or 0,
            'is_active': bool(self.is_active),
        }


class Subscription(db.Model):
    """An instance of a driver subscribing to a plan."""

    __tablename__ = 'subscriptions'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    driver_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), nullable=False)
    plan_id = db.Column(db.BigInteger, db.ForeignKey('subscription_plans.id'), nullable=True)
    payment_id = db.Column(db.BigInteger, nullable=True)
    tx_ref = db.Column(db.String(120), nullable=True)

    amount = db.Column(db.Numeric(12, 2), default=0.00)
    currency = db.Column(db.String(5), default='NGN')
    # pending / active / expired / cancelled
    status = db.Column(db.String(20), default='pending')
    start_at = db.Column(db.DateTime, nullable=True)
    end_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan = db.relationship('SubscriptionPlan', lazy=True,
                           primaryjoin='Subscription.plan_id == SubscriptionPlan.id',
                           foreign_keys=[plan_id])

    def activate(self, duration_days=None):
        self.status = 'active'
        self.start_at = datetime.utcnow()
        days = duration_days if duration_days is not None else (
            self.plan.duration_days if self.plan else 7)
        self.end_at = self.start_at + timedelta(days=max(int(days or 0), 0))

    @property
    def is_active_now(self):
        if self.status != 'active' or not self.end_at:
            return False
        return self.end_at >= datetime.utcnow()

    @staticmethod
    def active_for_driver(driver_id):
        now = datetime.utcnow()
        return Subscription.query.filter(
            Subscription.driver_id == driver_id,
            Subscription.status == 'active',
            Subscription.end_at >= now,
        ).order_by(Subscription.end_at.desc()).first()

    @staticmethod
    def activate_by_tx_ref(tx_ref, flw_tx_id=None):
        """Idempotently activate a pending subscription by its tx_ref and promote
        the driver. Returns the Subscription or None. Safe to call from both the
        webhook and the client-side verify endpoint."""
        from backend.models import db
        from backend.models.user import AdminUser

        sub = Subscription.query.filter_by(tx_ref=tx_ref).first()
        if not sub:
            return None
        if sub.is_active_now:
            return sub  # already activated — idempotent

        sub.activate()
        if flw_tx_id:
            sub.payment_id = flw_tx_id
        driver = db.session.get(AdminUser, sub.driver_id)
        if driver and driver.user_type == 'Pending Driver':
            driver.user_type = 'Driver'
        db.session.commit()
        return sub

    def to_dict(self):
        return {
            'id': self.id,
            'driver_id': self.driver_id,
            'plan_id': self.plan_id,
            'plan': self.plan.to_dict() if self.plan else None,
            'payment_id': self.payment_id,
            'tx_ref': self.tx_ref,
            'amount': float(self.amount or 0),
            'currency': self.currency or 'NGN',
            'status': self.status,
            'is_active_now': self.is_active_now,
            'start_at': self.start_at.isoformat() if self.start_at else None,
            'end_at': self.end_at.isoformat() if self.end_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
