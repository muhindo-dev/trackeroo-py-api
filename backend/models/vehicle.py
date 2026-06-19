from datetime import datetime
from backend.models import db


class Vehicle(db.Model):
    """A registered vehicle, owned by a Vehicle Owner (or owner-driver) and
    optionally linked to a driver. Verified against the uploaded log book.
    """

    __tablename__ = 'vehicles'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    owner_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), nullable=False)
    driver_id = db.Column(db.BigInteger, db.ForeignKey('admin_users.id'), nullable=True)
    category_id = db.Column(db.BigInteger, db.ForeignKey('vehicle_categories.id'), nullable=True)

    type = db.Column(db.String(100), nullable=True)        # e.g. Truck, Car, Motorcycle
    model = db.Column(db.String(150), nullable=True)
    reg_no = db.Column(db.String(100), nullable=True)
    colour = db.Column(db.String(60), nullable=True)
    insurance_status = db.Column(db.String(60), default='Unknown')  # Valid/Expired/Unknown

    logbook_photo = db.Column(db.Text, nullable=True)
    photo = db.Column(db.Text, nullable=True)

    # Pending / Verified / Rejected
    verification_status = db.Column(db.String(30), default='Pending')
    is_active = db.Column(db.SmallInteger, default=1)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = db.relationship('VehicleCategory', lazy=True,
                               primaryjoin='Vehicle.category_id == VehicleCategory.id',
                               foreign_keys=[category_id])
    owner = db.relationship('AdminUser', lazy=True,
                            primaryjoin='Vehicle.owner_id == AdminUser.id',
                            foreign_keys=[owner_id])
    driver = db.relationship('AdminUser', lazy=True,
                             primaryjoin='Vehicle.driver_id == AdminUser.id',
                             foreign_keys=[driver_id])

    def to_dict(self):
        return {
            'id': self.id,
            'owner_id': self.owner_id,
            'driver_id': self.driver_id,
            'driver_name': self.driver.name if self.driver else None,
            'category_id': self.category_id,
            'category_name': self.category.name if self.category else None,
            'category': self.category.to_dict() if self.category else None,
            'type': self.type,
            'model': self.model,
            'reg_no': self.reg_no,
            'colour': self.colour,
            'insurance_status': self.insurance_status,
            'logbook_photo': self.logbook_photo,
            'photo': self.photo,
            'verification_status': self.verification_status,
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
