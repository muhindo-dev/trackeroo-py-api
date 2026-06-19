"""Vehicle category endpoints.

Public:
  GET  /api/vehicle-categories            — list active categories (mobile dropdown)
Admin:
  GET  /api/admin/vehicle-categories      — list all
  POST /api/admin/vehicle-categories      — create
  POST /api/admin/vehicle-categories/<id> — update
  POST /api/admin/vehicle-categories/<id>/delete — soft delete
"""
from datetime import datetime

from flask import Blueprint, request

from backend.models import db
from backend.models.vehicle_category import VehicleCategory
from backend.models.service_rate import ServiceRate
from backend.utils.auth import admin_required
from backend.utils.response import success_response, error_response

vehicle_categories_bp = Blueprint('vehicle_categories', __name__)


def _num(val, default=0):
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _int(val, default=0):
    if val is None or val == '':
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


@vehicle_categories_bp.route('/api/vehicle-categories', methods=['GET'])
def list_public():
    group = request.args.get('service_group')
    q = VehicleCategory.query.filter_by(is_active=1)
    if group:
        q = q.filter_by(service_group=group)
    cats = q.order_by(VehicleCategory.sort_order.asc(), VehicleCategory.id.asc()).all()
    return success_response("Vehicle categories", [c.to_dict() for c in cats])


@vehicle_categories_bp.route('/api/admin/vehicle-categories', methods=['GET'])
@admin_required
def list_admin(user):
    cats = VehicleCategory.query.order_by(
        VehicleCategory.sort_order.asc(), VehicleCategory.id.asc()
    ).all()
    return success_response("Vehicle categories", [c.to_dict() for c in cats])


def _apply(cat, data):
    if 'name' in data:
        cat.name = data.get('name')
    if 'code' in data and data.get('code'):
        cat.code = data.get('code')
    if 'service_group' in data:
        cat.service_group = data.get('service_group')
    if 'wheels' in data:
        cat.wheels = _int(data.get('wheels'))
    if 'description' in data:
        cat.description = data.get('description')
    if 'icon' in data:
        cat.icon = data.get('icon')
    if 'min_price' in data:
        cat.min_price = _num(data.get('min_price'))
    if 'est_loading_minutes' in data:
        cat.est_loading_minutes = _int(data.get('est_loading_minutes'))
    if 'per_km_rate' in data:
        cat.per_km_rate = _num(data.get('per_km_rate'))
    if 'is_luxury' in data:
        cat.is_luxury = 1 if str(data.get('is_luxury')).lower() in ('1', 'true', 'yes') else 0
    if 'sort_order' in data:
        cat.sort_order = _int(data.get('sort_order'))
    if 'is_active' in data:
        cat.is_active = 1 if str(data.get('is_active')).lower() in ('1', 'true', 'yes') else 0


@vehicle_categories_bp.route('/api/admin/vehicle-categories', methods=['POST'])
@admin_required
def create(user):
    data = request.get_json(silent=True) or request.form or {}
    if not data.get('name') or not data.get('code'):
        return error_response("name and code are required")
    if VehicleCategory.query.filter_by(code=data.get('code')).first():
        return error_response("A category with this code already exists")
    cat = VehicleCategory()
    _apply(cat, data)
    db.session.add(cat)
    db.session.commit()
    return success_response("Category created", cat.to_dict())


@vehicle_categories_bp.route('/api/admin/vehicle-categories/<int:cat_id>', methods=['POST'])
@admin_required
def update(user, cat_id):
    cat = db.session.get(VehicleCategory, cat_id)
    if not cat:
        return error_response("Category not found", status_code=404)
    data = request.get_json(silent=True) or request.form or {}
    _apply(cat, data)
    cat.updated_at = datetime.utcnow()
    db.session.commit()
    return success_response("Category updated", cat.to_dict())


@vehicle_categories_bp.route('/api/admin/vehicle-categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def delete(user, cat_id):
    cat = db.session.get(VehicleCategory, cat_id)
    if not cat:
        return error_response("Category not found", status_code=404)
    cat.is_active = 0
    db.session.commit()
    return success_response("Category deactivated", cat.to_dict())


# ── Pricing parameters (service_rates: base + q,r,s,t + peak windows) ──────────

@vehicle_categories_bp.route('/api/admin/service-rates', methods=['GET'])
@admin_required
def service_rates_list(user):
    rates = ServiceRate.query.filter_by(is_active=1).order_by(ServiceRate.service_type.asc()).all()
    return success_response("Service rates", [r.to_dict() for r in rates])


_RATE_FIELDS = {
    'base_rate_cad': float, 'per_km_rate_cad': float, 'per_minute_rate_cad': float,
    'surge_multiplier': float, 'minimum_fare_cad': float,
    'p_extra_km': float, 'q_peak_minute': float, 'r_offpeak_minute': float,
    's_loading_overrun': float, 't_completion_overrun': float, 'free_km': float,
    'peak_start_hour': int, 'peak_end_hour': int,
    'peak_start_hour_pm': int, 'peak_end_hour_pm': int,
}


@vehicle_categories_bp.route('/api/admin/service-rates/<int:rate_id>', methods=['POST'])
@admin_required
def service_rate_update(user, rate_id):
    rate = db.session.get(ServiceRate, rate_id)
    if not rate:
        return error_response("Service rate not found", status_code=404)
    data = request.get_json(silent=True) or request.form or {}
    for field, caster in _RATE_FIELDS.items():
        if field in data and data.get(field) not in (None, ''):
            try:
                setattr(rate, field, caster(data.get(field)))
            except (ValueError, TypeError):
                pass
    db.session.commit()
    return success_response("Service rate updated", rate.to_dict())
