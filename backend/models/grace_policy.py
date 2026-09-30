from datetime import datetime
from backend.models import db


class DriverGracePolicy(db.Model):
    __tablename__ = 'driver_grace_policies'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(120), nullable=False)
    plan_id = db.Column(db.BigInteger, db.ForeignKey('subscription_plans.id'), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    duration_days = db.Column(db.Integer, nullable=False, default=7)
    apply_to_new_drivers = db.Column(db.SmallInteger, nullable=False, default=1)
    apply_to_existing = db.Column(db.SmallInteger, nullable=False, default=0)
    max_redemptions = db.Column(db.Integer, nullable=True)
    redemption_count = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.SmallInteger, nullable=False, default=1)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan = db.relationship('SubscriptionPlan', lazy=True)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'plan_id': self.plan_id,
            'plan': self.plan.to_dict() if self.plan else None,
            'start_at': self.start_at.isoformat() if self.start_at else None,
            'end_at': self.end_at.isoformat() if self.end_at else None,
            'duration_days': self.duration_days, 'apply_to_new_drivers': bool(self.apply_to_new_drivers),
            'apply_to_existing': bool(self.apply_to_existing), 'max_redemptions': self.max_redemptions,
            'redemption_count': self.redemption_count, 'is_active': bool(self.is_active), 'notes': self.notes,
        }
