from datetime import datetime
from backend.models import db
from sqlalchemy import func


class DriverRating(db.Model):
    __tablename__ = 'driver_ratings'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.BigInteger, nullable=False)
    driver_id = db.Column(db.BigInteger, nullable=False)
    booking_id = db.Column(db.BigInteger, nullable=False)
    rating = db.Column(db.SmallInteger, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('customer_id', 'booking_id', name='uq_customer_booking'),
    )

    @staticmethod
    def get_driver_stats(driver_id: int) -> dict:
        """Return average rating and total count for a driver."""
        result = db.session.query(
            func.avg(DriverRating.rating).label('avg'),
            func.count(DriverRating.id).label('count'),
        ).filter_by(driver_id=driver_id).first()
        avg = float(result.avg) if result.avg else None
        return {
            'average_rating': round(avg, 2) if avg else None,
            'total_ratings': result.count or 0,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'driver_id': self.driver_id,
            'booking_id': self.booking_id,
            'rating': self.rating,
            'comment': self.comment,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
