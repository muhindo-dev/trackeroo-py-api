"""Vehicle registration endpoints.

  GET  /api/vehicles                      — my vehicles (owned or driving)
  POST /api/vehicles                      — register a vehicle (optional logbook upload)
  POST /api/vehicles/<id>                 — update a vehicle
  POST /api/vehicles/<id>/link-driver     — link/unlink a driver to a vehicle
  POST /api/vehicles/<id>/logbook         — upload/replace the log book photo
  POST /api/vehicles/<id>/delete          — soft delete
Admin:
  POST /api/admin/vehicles/<id>/verify    — set verification status
"""
import os
from datetime import datetime

from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename

from backend.models import db
from backend.models.vehicle import Vehicle
from backend.models.vehicle_category import VehicleCategory
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user, admin_required
from backend.utils.response import success_response, error_response

vehicles_bp = Blueprint('vehicles', __name__)


def _str(val):
    if val is None or val == '':
        return None
    return str(val).strip()


def _int(val):
    if val is None or val == '':
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _apply_capability(driver, category, approve=False):
    """Map a vehicle's service_group to the driver's capability flags so the
    pricing/match filters work. Boda→is_boda, Special Hire→is_car, Truck→is_delivery.
    `approve=True` (vehicle verified) also sets the *_approved flag."""
    if not driver or not category:
        return
    mapping = {
        'Boda': ('is_boda', 'is_boda_approved'),
        'Special Hire': ('is_car', 'is_car_approved'),
        'Truck': ('is_delivery', 'is_delivery_approved'),
    }
    pair = mapping.get((category.service_group or '').strip())
    if not pair:
        return
    setattr(driver, pair[0], 'Yes')
    if approve:
        setattr(driver, pair[1], 'Yes')


def _save_logbook(vehicle_id, file):
    filename = secure_filename(f"logbook_{vehicle_id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images')
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return f"images/{filename}"


@vehicles_bp.route('/api/vehicles', methods=['GET'])
@jwt_required_with_user
def my_vehicles(user):
    vehicles = Vehicle.query.filter(
        Vehicle.is_active == 1,
        db.or_(Vehicle.owner_id == user.id, Vehicle.driver_id == user.id),
    ).order_by(Vehicle.created_at.desc()).all()
    return success_response("My vehicles", [v.to_dict() for v in vehicles])


@vehicles_bp.route('/api/vehicles', methods=['POST'])
@jwt_required_with_user
def register_vehicle(user):
    data = request.form if request.form else (request.get_json(silent=True) or {})

    category_id = _int(data.get('category_id'))
    category = db.session.get(VehicleCategory, category_id) if category_id else None
    if category_id and (not category or not category.is_active):
        return error_response("Invalid or inactive vehicle category")

    vehicle = Vehicle(
        owner_id=user.id,
        driver_id=_int(data.get('driver_id')),
        category_id=category_id,
        type=_str(data.get('type')),
        model=_str(data.get('model')),
        reg_no=_str(data.get('reg_no')),
        colour=_str(data.get('colour')),
        insurance_status=_str(data.get('insurance_status')) or 'Unknown',
        verification_status='Pending',
    )
    db.session.add(vehicle)
    db.session.flush()  # get id for the logbook filename

    logbook = request.files.get('logbook') or request.files.get('logbook_photo')
    if logbook and logbook.filename:
        vehicle.logbook_photo = _save_logbook(vehicle.id, logbook)
    photo = request.files.get('photo')
    if photo and photo.filename:
        vehicle.photo = _save_logbook(vehicle.id, photo)

    # Keep the owner's declared vehicle count in sync
    owner = db.session.get(AdminUser, user.id)
    owner.vehicle_count = (owner.vehicle_count or 0) + 1
    db.session.commit()
    return success_response("Vehicle registered", vehicle.to_dict())


def _owned(user, vehicle):
    return vehicle and (vehicle.owner_id == user.id or user.user_type in ('Admin', 'Super Admin'))


@vehicles_bp.route('/api/vehicles/<int:vehicle_id>', methods=['POST'])
@jwt_required_with_user
def update_vehicle(user, vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not _owned(user, vehicle):
        return error_response("Vehicle not found", status_code=404)
    data = request.form if request.form else (request.get_json(silent=True) or {})
    for field in ('type', 'model', 'reg_no', 'colour', 'insurance_status'):
        if field in data:
            setattr(vehicle, field, _str(data.get(field)))
    if 'category_id' in data:
        vehicle.category_id = _int(data.get('category_id'))
    logbook = request.files.get('logbook') or request.files.get('logbook_photo')
    if logbook and logbook.filename:
        vehicle.logbook_photo = _save_logbook(vehicle.id, logbook)
        vehicle.verification_status = 'Pending'
    vehicle.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Vehicle updated", vehicle.to_dict())


@vehicles_bp.route('/api/vehicles/<int:vehicle_id>/link-driver', methods=['POST'])
@jwt_required_with_user
def link_driver(user, vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not _owned(user, vehicle):
        return error_response("Vehicle not found", status_code=404)
    data = request.get_json(silent=True) or request.form or {}
    driver_id = _int(data.get('driver_id'))
    if driver_id:
        driver = db.session.get(AdminUser, driver_id)
        if not driver:
            return error_response("Driver not found", status_code=404)
        vehicle.driver_id = driver_id
        # Grant capability from the vehicle's category (approved if already verified).
        category = db.session.get(VehicleCategory, vehicle.category_id) if vehicle.category_id else None
        _apply_capability(driver, category, approve=(vehicle.verification_status == 'Verified'))
    else:
        vehicle.driver_id = None  # unlink
    vehicle.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Driver link updated", vehicle.to_dict())


@vehicles_bp.route('/api/vehicles/<int:vehicle_id>/logbook', methods=['POST'])
@jwt_required_with_user
def upload_logbook(user, vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not _owned(user, vehicle):
        return error_response("Vehicle not found", status_code=404)
    logbook = request.files.get('logbook') or request.files.get('logbook_photo') or request.files.get('photo')
    if not logbook or not logbook.filename:
        return error_response("No log book file uploaded")
    vehicle.logbook_photo = _save_logbook(vehicle.id, logbook)
    vehicle.verification_status = 'Pending'
    vehicle.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Log book uploaded", vehicle.to_dict())


@vehicles_bp.route('/api/vehicles/<int:vehicle_id>/delete', methods=['POST'])
@jwt_required_with_user
def delete_vehicle(user, vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not _owned(user, vehicle):
        return error_response("Vehicle not found", status_code=404)
    vehicle.is_active = 0
    vehicle.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Vehicle removed", vehicle.to_dict())


@vehicles_bp.route('/api/admin/vehicles', methods=['GET'])
@admin_required
def admin_list(user):
    status = request.args.get('verification_status')
    q = Vehicle.query.filter_by(is_active=1)
    if status:
        q = q.filter_by(verification_status=status)
    vehicles = q.order_by(Vehicle.created_at.desc()).all()
    return success_response("Vehicles", [v.to_dict() for v in vehicles])


@vehicles_bp.route('/api/admin/vehicles/<int:vehicle_id>/verify', methods=['POST'])
@admin_required
def verify_vehicle(user, vehicle_id):
    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        return error_response("Vehicle not found", status_code=404)
    data = request.get_json(silent=True) or request.form or {}
    status = data.get('verification_status', 'Verified')
    if status not in ('Pending', 'Verified', 'Rejected'):
        return error_response("Invalid verification status")
    vehicle.verification_status = status
    vehicle.updated_at = datetime.utcnow()
    # On approval, grant the linked driver the approved capability for this category.
    if status == 'Verified' and vehicle.driver_id:
        driver = db.session.get(AdminUser, vehicle.driver_id)
        category = db.session.get(VehicleCategory, vehicle.category_id) if vehicle.category_id else None
        _apply_capability(driver, category, approve=True)
    db.session.commit()
    return success_response("Vehicle verification updated", vehicle.to_dict())
