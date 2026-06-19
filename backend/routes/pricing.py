"""Pricing & availability matching.

  POST /api/pricing/estimate   — fare estimate for a category + trip
  POST /api/pricing/match      — fare estimate + drivers available by pickup ETA

Pricing model:
    base_price = category.min_price
    p          = category.per_km_rate
    q, r, s, t = service_rates row for the category's service_group

    PRICE = base + p*extra_km + q*peak_min + r*offpeak_min
                 + s*loading_overrun_min + t*completion_overrun_min
"""
from datetime import datetime, timedelta

from flask import Blueprint, request

from backend.models import db
from backend.models.vehicle_category import VehicleCategory
from backend.models.service_rate import ServiceRate
from backend.models.user import AdminUser
from backend.utils.response import success_response, error_response

pricing_bp = Blueprint('pricing', __name__)


def _num(val, default=0.0):
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_dt(val):
    if not val:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(str(val)[:19], fmt)
        except ValueError:
            continue
    return None


def _resolve_category(data):
    cat_id = data.get('category_id')
    code = data.get('category_code') or data.get('category')
    if cat_id:
        try:
            return db.session.get(VehicleCategory, int(cat_id))
        except (ValueError, TypeError):
            return None
    if code:
        return VehicleCategory.query.filter_by(code=code).first()
    return None


def _estimate(category, data):
    distance_km = _num(data.get('distance_km'))
    duration_min = _num(data.get('duration_min'))
    loading_overrun = _num(data.get('loading_overrun_min'))
    completion_overrun = _num(data.get('completion_overrun_min'))
    start_dt = _parse_dt(data.get('start_time')) or datetime.utcnow()

    rate = ServiceRate.get_rate(category.service_group) or ServiceRate.get_rate('Truck')
    if not rate:
        # No coefficients configured — fall back to base + per_km only.
        extra = max(distance_km, 0)
        price = max(float(category.min_price or 0) + float(category.per_km_rate or 0) * extra,
                    float(category.min_price or 0))
        return {
            'estimate': round(price, 0),
            'min': round(price * 0.95, 0),
            'max': round(price * 1.1, 0),
            'currency': 'NGN',
            'breakdown': {'base': float(category.min_price or 0), 'extra_km': extra},
        }

    result = rate.estimate_fare_v2(
        distance_km=distance_km,
        duration_min=duration_min,
        loading_overrun_min=loading_overrun,
        completion_overrun_min=completion_overrun,
        start_dt=start_dt,
        min_price=float(category.min_price or 0),
        base_price=float(category.min_price or 0),
        per_km=float(category.per_km_rate or 0),
    )
    result['category'] = category.to_dict()
    result['est_loading_minutes'] = category.est_loading_minutes or 0
    return result


@pricing_bp.route('/api/pricing/estimate', methods=['POST'])
def estimate():
    data = request.get_json(silent=True) or request.form or {}
    category = _resolve_category(data)
    if not category:
        return error_response("Valid category_id or category_code is required")
    return success_response("Fare estimate", _estimate(category, data))


@pricing_bp.route('/api/pricing/match', methods=['POST'])
def match():
    """Estimate the fare and return online drivers whose availability matches the
    requested pickup time. A driver matches when they are online and either free
    now or free (busy_until) before the requested pickup ETA."""
    data = request.get_json(silent=True) or request.form or {}
    category = _resolve_category(data)
    if not category:
        return error_response("Valid category_id or category_code is required")

    estimate_data = _estimate(category, data)

    pickup_eta = _parse_dt(data.get('pickup_time'))
    # Default matching window: drivers free within the next 2 hours
    horizon = pickup_eta or (datetime.utcnow() + timedelta(hours=2))

    service_flag_map = {
        'Boda': AdminUser.is_boda,
        'Special Hire': AdminUser.is_car,
        'Truck': AdminUser.is_delivery,
    }
    flag_col = service_flag_map.get(category.service_group)

    q = AdminUser.query.filter(
        AdminUser.ready_for_trip == 'Yes',
        AdminUser.user_type == 'Driver',
    )
    if flag_col is not None:
        q = q.filter(flag_col == 'Yes')
    # Available now (busy_until null/past) OR becomes free before the pickup ETA
    q = q.filter(
        db.or_(
            AdminUser.busy_until.is_(None),
            AdminUser.busy_until <= horizon,
        )
    )
    drivers = q.order_by(AdminUser.rating.desc()).limit(20).all()

    matched = []
    for d in drivers:
        free_at = d.busy_until or d.available_from
        matched.append({
            'id': d.id,
            'name': d.name,
            'phone_number': d.phone_number,
            'avatar': d.avatar,
            'rating': float(d.rating) if d.rating else 0,
            'current_latitude': str(d.current_latitude) if d.current_latitude else None,
            'current_longitude': str(d.current_longitude) if d.current_longitude else None,
            'available_from': free_at.isoformat() if free_at else None,
            'vehicle_type': d.vehicle_type,
        })

    return success_response("Matched drivers", {
        'estimate': estimate_data,
        'pickup_eta': horizon.isoformat(),
        'drivers': matched,
        'driver_count': len(matched),
    })
