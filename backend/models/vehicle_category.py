from datetime import datetime
from backend.models import db


class VehicleCategory(db.Model):
    """Admin-registered vehicle categories used for vehicle registration and pricing.

    Seeded with the client's truck categories (Small/Medium/Average/Big/Trailer)
    plus Boda and Special-Hire car categories. Each category carries the base
    commercial parameters used by the pricing engine: a minimum price, an
    estimated loading time, and a per-km charge for the rest of the trip.
    """

    __tablename__ = 'vehicle_categories'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), nullable=False)  # stable machine key e.g. small_truck
    # Service group this category belongs to: 'Boda', 'Special Hire', 'Truck'
    service_group = db.Column(db.String(50), default='Truck')
    wheels = db.Column(db.Integer, nullable=True)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(100), nullable=True)

    # Commercial / pricing parameters
    min_price = db.Column(db.Numeric(12, 2), default=0.00)        # Base Price floor
    est_loading_minutes = db.Column(db.Integer, default=0)        # estimated loading time
    per_km_rate = db.Column(db.Numeric(12, 2), default=0.00)      # charge per extra km

    is_luxury = db.Column(db.SmallInteger, default=0)             # Special Hire luxury flag
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.SmallInteger, default=1)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def active():
        return VehicleCategory.query.filter_by(is_active=1).order_by(
            VehicleCategory.sort_order.asc(), VehicleCategory.id.asc()
        ).all()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'service_group': self.service_group,
            'wheels': self.wheels,
            'description': self.description,
            'icon': self.icon,
            'min_price': float(self.min_price or 0),
            'est_loading_minutes': self.est_loading_minutes or 0,
            'per_km_rate': float(self.per_km_rate or 0),
            'is_luxury': bool(self.is_luxury),
            'sort_order': self.sort_order or 0,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
