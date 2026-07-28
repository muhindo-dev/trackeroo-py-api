import json
from datetime import datetime
from backend.models import db


class RideDispatch(db.Model):
    """Auto-dispatch state for an instant ride: the fairness-ranked candidate
    drivers, which one currently holds the offer, and the offer deadline.

    Status: searching → offered → matched | no_match | cancelled
    """

    __tablename__ = 'ride_dispatches'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    negotiation_id = db.Column(db.BigInteger, nullable=False)
    customer_id = db.Column(db.BigInteger, nullable=True)
    category_id = db.Column(db.BigInteger, nullable=True)
    service_group = db.Column(db.String(50), nullable=True)
    candidates = db.Column(db.Text, nullable=True)  # JSON list of driver ids, ranked
    current_index = db.Column(db.Integer, default=0)
    offer_expires_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='searching')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def candidate_list(self):
        try:
            return json.loads(self.candidates or '[]')
        except (ValueError, TypeError):
            return []

    def current_driver_id(self):
        lst = self.candidate_list()
        idx = self.current_index or 0
        return lst[idx] if 0 <= idx < len(lst) else None

    def to_dict(self):
        return {
            'id': self.id,
            'negotiation_id': self.negotiation_id,
            'customer_id': self.customer_id,
            'category_id': self.category_id,
            'service_group': self.service_group,
            'candidates': self.candidate_list(),
            'current_index': self.current_index or 0,
            'offer_expires_at': self.offer_expires_at.isoformat() if self.offer_expires_at else None,
            'status': self.status,
        }
