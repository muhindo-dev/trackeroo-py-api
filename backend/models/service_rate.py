from datetime import datetime
from backend.models import db


class ServiceRate(db.Model):
    __tablename__ = 'service_rates'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    service_type = db.Column(db.String(100), nullable=False)
    vehicle_type = db.Column(db.String(100), default='Any')
    base_rate_cad = db.Column(db.Numeric(8, 2), default=0.00)
    per_km_rate_cad = db.Column(db.Numeric(8, 2), default=0.00)
    per_minute_rate_cad = db.Column(db.Numeric(8, 2), default=0.00)
    surge_multiplier = db.Column(db.Numeric(4, 2), default=1.00)
    minimum_fare_cad = db.Column(db.Numeric(8, 2), default=0.00)
    is_active = db.Column(db.SmallInteger, default=1)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get_rate(service_type: str, vehicle_type: str = None):
        """Return the best matching ServiceRate for a service/vehicle combo."""
        q = ServiceRate.query.filter_by(is_active=1, service_type=service_type)
        if vehicle_type:
            exact = q.filter_by(vehicle_type=vehicle_type).first()
            if exact:
                return exact
        return q.filter_by(vehicle_type='Any').first() or q.first()

    @staticmethod
    def estimate_fare(service_type: str, vehicle_type: str, distance_km: float, duration_min: float = 0) -> dict:
        """Calculate an estimated fare range for a given trip."""
        rate = ServiceRate.get_rate(service_type, vehicle_type)
        if not rate:
            return {'min': 0, 'max': 0, 'base': 0, 'per_km': 0, 'currency': 'CAD'}

        base = float(rate.base_rate_cad or 0)
        per_km = float(rate.per_km_rate_cad or 0)
        per_min = float(rate.per_minute_rate_cad or 0)
        surge = float(rate.surge_multiplier or 1)
        minimum = float(rate.minimum_fare_cad or 0)

        estimated = (base + per_km * distance_km + per_min * duration_min) * surge
        estimated = max(estimated, minimum)

        return {
            'min': round(estimated * 0.9, 2),
            'max': round(estimated * 1.1, 2),
            'estimate': round(estimated, 2),
            'base_rate': base,
            'per_km_rate': per_km,
            'surge_multiplier': surge,
            'currency': 'CAD',
        }

    def to_dict(self):
        return {
            'id': self.id,
            'service_type': self.service_type,
            'vehicle_type': self.vehicle_type,
            'base_rate_cad': float(self.base_rate_cad or 0),
            'per_km_rate_cad': float(self.per_km_rate_cad or 0),
            'per_minute_rate_cad': float(self.per_minute_rate_cad or 0),
            'surge_multiplier': float(self.surge_multiplier or 1),
            'minimum_fare_cad': float(self.minimum_fare_cad or 0),
            'is_active': bool(self.is_active),
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
