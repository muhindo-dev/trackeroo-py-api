from datetime import datetime
from backend.models import db


class PopularLocation(db.Model):
    __tablename__ = 'popular_locations'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500), nullable=True)
    lat = db.Column(db.Numeric(10, 7), nullable=False)
    lng = db.Column(db.Numeric(10, 7), nullable=False)
    city = db.Column(db.String(100), default='Lagos')
    category = db.Column(db.String(100), default='Other')
    is_active = db.Column(db.SmallInteger, default=1)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def matches(self, query: str) -> bool:
        q = query.lower().strip()
        return (
            q in (self.name or '').lower()
            or q in (self.address or '').lower()
            or q in (self.city or '').lower()
        )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'lat': float(self.lat) if self.lat else None,
            'lng': float(self.lng) if self.lng else None,
            'city': self.city,
            'category': self.category,
            'is_active': bool(self.is_active),
            'sort_order': self.sort_order,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
