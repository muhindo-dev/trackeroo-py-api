"""Instant ride engine — V2 auto-dispatch (no negotiation, fixed system price).

  POST /api/rides/quote               — price + avg driver ETA + driver count (no driver list)
  POST /api/rides/request             — create ride, rank drivers fairly, offer to best
  GET  /api/rides/<id>/status         — poll; lazily advances expired offers; proposals on no-match
  POST /api/rides/<id>/respond        — driver accept/decline the offer
  POST /api/rides/<id>/choose-driver  — customer picks a proposed driver after no-match
  POST /api/rides/<id>/cancel         — customer cancels the search
  GET  /api/drivers/<id>/card         — public driver card (direct connect by ID/QR)

Fairness ranking (per owner spec):
  ring 1 = drivers within 5 km; if empty, ring 2 = within 10 km.
  Order: fewest completed trips today  →  nearest  →  highest rating.
  Busy drivers (active trip / busy_until in future) are skipped.
"""
import json
import math
from datetime import datetime, timedelta

from flask import Blueprint, request
from sqlalchemy import func

from backend.models import db
from backend.models.user import AdminUser
from backend.models.negotiation import Negotiation
from backend.models.ride_dispatch import RideDispatch
from backend.models.vehicle_category import VehicleCategory
from backend.models.vehicle import Vehicle
from backend.models.subscription import Subscription
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response
from backend.routes.pricing import _estimate, _resolve_category
from backend.services.notification_service import notify_user

rides_bp = Blueprint('rides', __name__)

OFFER_SECONDS = 35          # how long each driver holds the offer
RING1_KM = 5.0
RING2_KM = 10.0
PROPOSAL_KM = 15.0          # radius for "no match" manual proposals
CITY_SPEED_KMH = 25.0       # ETA model


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _eta_min(km):
    return max(1, round(km / CITY_SPEED_KMH * 60))


def _online_drivers(service_group):
    """Online, subscribed, not-busy drivers live for this service group."""
    now = datetime.utcnow()
    q = AdminUser.query.filter(
        AdminUser.ready_for_trip == 'Yes',
        AdminUser.user_type == 'Driver',
        AdminUser.current_latitude.isnot(None),
        AdminUser.current_longitude.isnot(None),
    )
    if service_group:
        q = q.filter(AdminUser.live_service_group == service_group)
    drivers = []
    for d in q.limit(300).all():
        if d.busy_until and d.busy_until > now:
            continue
        if Subscription.active_for_driver(d.id) is None:
            continue
        drivers.append(d)
    return drivers


def _trips_today(driver_id):
    today = datetime.utcnow().date()
    return Negotiation.query.filter(
        Negotiation.driver_id == driver_id,
        Negotiation.status == 'Completed',
        func.date(Negotiation.updated_at) == today,
    ).count()


def _ranked_candidates(service_group, pickup_lat, pickup_lng):
    """Fairness-ranked candidate driver list. Returns [(driver, km)] ranked."""
    pool = []
    for d in _online_drivers(service_group):
        km = _haversine_km(pickup_lat, pickup_lng, float(d.current_latitude), float(d.current_longitude))
        pool.append((d, km))
    ring = [x for x in pool if x[1] <= RING1_KM] or [x for x in pool if x[1] <= RING2_KM]
    # fewest trips today → nearest → highest rating
    ring.sort(key=lambda x: (_trips_today(x[0].id), round(x[1], 1), -float(x[0].rating or 0)))
    return ring


def _driver_card_dict(d, km=None):
    vehicle = Vehicle.query.filter_by(driver_id=d.id, is_active=1).first() \
        or Vehicle.query.filter_by(owner_id=d.id, is_active=1).first()
    return {
        'id': d.id,
        'name': d.name,
        'phone_number': d.phone_number,
        'avatar': d.avatar,
        'rating': float(d.rating or 0),
        'is_online': d.ready_for_trip == 'Yes',
        'live_service_group': d.live_service_group,
        'distance_km': round(km, 1) if km is not None else None,
        'eta_min': _eta_min(km) if km is not None else None,
        'trips_today': _trips_today(d.id),
        'vehicle': {
            'model': vehicle.model if vehicle else None,
            'reg_no': vehicle.reg_no if vehicle else None,
            'colour': vehicle.colour if vehicle else None,
            'category': vehicle.category.name if vehicle and vehicle.category else None,
        } if vehicle else None,
    }


def _offer_to(dispatch, negotiation, driver_id):
    """Assign the offer to a driver and notify them."""
    negotiation.driver_id = driver_id
    d = db.session.get(AdminUser, driver_id)
    negotiation.driver_name = d.name if d else None
    dispatch.status = 'offered'
    dispatch.offer_expires_at = datetime.utcnow() + timedelta(seconds=OFFER_SECONDS)
    try:
        notify_user(driver_id, "New ride request 🚕",
                    f"Pickup: {negotiation.pickup_address or 'nearby'} — ₦{int(_num(negotiation.agreed_price) or 0)}",
                    {'type': 'ride_offer', 'negotiation_id': negotiation.id})
    except Exception:
        pass


def _advance(dispatch, negotiation):
    """Move the offer to the next ranked candidate; no_match when exhausted."""
    lst = dispatch.candidate_list()
    nxt = (dispatch.current_index or 0) + 1
    while nxt < len(lst):
        d = db.session.get(AdminUser, lst[nxt])
        if d and d.ready_for_trip == 'Yes' and not (d.busy_until and d.busy_until > datetime.utcnow()):
            dispatch.current_index = nxt
            _offer_to(dispatch, negotiation, lst[nxt])
            return True
        nxt += 1
    dispatch.status = 'no_match'
    dispatch.offer_expires_at = None
    negotiation.driver_id = None
    negotiation.driver_name = None
    return False


def _alt_categories(category, pickup_lat, pickup_lng):
    """Sibling categories in the same group that DO have available drivers."""
    if not category:
        return []
    alts = []
    for c in VehicleCategory.query.filter(
            VehicleCategory.service_group == category.service_group,
            VehicleCategory.is_active == 1,
            VehicleCategory.id != category.id).all():
        n = len(_ranked_candidates(c.service_group, pickup_lat, pickup_lng))
        if n:
            alts.append({'category': c.to_dict(), 'driver_count': n})
    return alts


# ─────────────────────────────────────────────────────────────────────────────

@rides_bp.route('/api/rides/quote', methods=['POST'])
@jwt_required_with_user
def quote(user):
    """Fixed system price + average ETA of drivers meeting the criteria."""
    data = request.get_json(silent=True) or request.form or {}
    category = _resolve_category(data)
    if not category:
        return error_response("Valid category_id or category_code is required")
    pickup_lat, pickup_lng = _num(data.get('pickup_lat')), _num(data.get('pickup_lng'))

    est = _estimate(category, data)
    ranked = _ranked_candidates(category.service_group, pickup_lat, pickup_lng) \
        if pickup_lat and pickup_lng else []
    etas = [_eta_min(km) for _, km in ranked]
    return success_response("Ride quote", {
        'estimate': est.get('estimate'),
        'min': est.get('min'),
        'max': est.get('max'),
        'currency': est.get('currency', 'NGN'),
        'driver_count': len(ranked),
        'avg_eta_min': round(sum(etas) / len(etas)) if etas else None,
        'category': category.to_dict(),
    })


@rides_bp.route('/api/rides/request', methods=['POST'])
@jwt_required_with_user
def request_ride(user):
    """Create an instant ride and auto-offer it to the fairest nearby driver."""
    data = request.get_json(silent=True) or request.form or {}
    category = _resolve_category(data)
    if not category:
        return error_response("Valid category_id or category_code is required")

    pickup_lat, pickup_lng = _num(data.get('pickup_lat')), _num(data.get('pickup_lng'))
    if not pickup_lat or not pickup_lng:
        return error_response("pickup_lat and pickup_lng are required")

    est = _estimate(category, data)
    price = _num(est.get('estimate'))

    payment_method = (data.get('payment_method') or '').strip() or None
    if payment_method and payment_method not in ('MM', 'Visa', 'Cash'):
        payment_method = 'Cash'

    negotiation = Negotiation(
        customer_id=user.id,
        customer_name=user.name,
        pickup_lat=str(pickup_lat), pickup_lng=str(pickup_lng),
        pickup_address=data.get('pickup_address'),
        dropoff_lat=str(_num(data.get('dropoff_lat'))), dropoff_lng=str(_num(data.get('dropoff_lng'))),
        dropoff_address=data.get('dropoff_address'),
        initial_price=int(price * 100),         # legacy cents field
        agreed_price=int(price * 100),          # fixed system price (cents convention)
        status='Active', is_active='Yes',
        customer_accepted='Accepted', customer_driver='Pending',
        payment_method=payment_method,
        ride_source='instant',
    )
    db.session.add(negotiation)
    db.session.flush()

    # Direct connect to a specific driver (ID / QR)?
    direct_id = data.get('driver_id')
    if direct_id:
        try:
            direct_id = int(direct_id)
        except (TypeError, ValueError):
            return error_response("Invalid driver_id")
        d = db.session.get(AdminUser, direct_id)
        if not d or d.user_type != 'Driver':
            return error_response("Driver not found", status_code=404)
        candidates = [direct_id]
    else:
        ranked = _ranked_candidates(category.service_group, pickup_lat, pickup_lng)
        candidates = [d.id for d, _ in ranked]

    dispatch = RideDispatch(
        negotiation_id=negotiation.id,
        customer_id=user.id,
        category_id=category.id,
        service_group=category.service_group,
        candidates=json.dumps(candidates),
        current_index=0,
    )
    db.session.add(dispatch)

    if candidates:
        _offer_to(dispatch, negotiation, candidates[0])
    else:
        dispatch.status = 'no_match'
    db.session.commit()

    return success_response("Ride requested", {
        'ride_id': negotiation.id,
        'dispatch': dispatch.to_dict(),
        'estimate': price,
        'negotiation': negotiation.to_dict(),
    })


def _status_payload(negotiation, dispatch, include_proposals=False):
    payload = {
        'ride_id': negotiation.id,
        'ride_status': negotiation.status,
        'dispatch_status': dispatch.status if dispatch else None,
        'negotiation': negotiation.to_dict(),
    }
    if dispatch and dispatch.status == 'no_match' and include_proposals:
        pickup_lat = _num(negotiation.pickup_lat)
        pickup_lng = _num(negotiation.pickup_lng)
        pool = []
        for d in _online_drivers(None):          # any group, wider net
            km = _haversine_km(pickup_lat, pickup_lng,
                               float(d.current_latitude), float(d.current_longitude))
            if km <= PROPOSAL_KM:
                pool.append((d, km))
        pool.sort(key=lambda x: x[1])
        payload['proposals'] = [_driver_card_dict(d, km) for d, km in pool[:10]]
        category = db.session.get(VehicleCategory, dispatch.category_id) if dispatch.category_id else None
        payload['alt_categories'] = _alt_categories(category, pickup_lat, pickup_lng)
    return payload


@rides_bp.route('/api/rides/<int:ride_id>/status', methods=['GET'])
@jwt_required_with_user
def ride_status(user, ride_id):
    """Poll ride status. Lazily advances expired offers (serverless dispatch)."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation:
        return error_response("Ride not found", status_code=404)
    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()

    if dispatch and dispatch.status == 'offered':
        if negotiation.status in ('Accepted', 'Started'):
            dispatch.status = 'matched'
            db.session.commit()
        elif dispatch.offer_expires_at and dispatch.offer_expires_at < datetime.utcnow():
            _advance(dispatch, negotiation)
            db.session.commit()

    return success_response("Ride status", _status_payload(negotiation, dispatch, include_proposals=True))


@rides_bp.route('/api/rides/<int:ride_id>/respond', methods=['POST'])
@jwt_required_with_user
def respond(user, ride_id):
    """Driver accepts or declines the current offer."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation:
        return error_response("Ride not found", status_code=404)
    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()
    if not dispatch or dispatch.status not in ('offered', 'searching'):
        return error_response("This ride is not awaiting a response")
    if negotiation.driver_id != user.id:
        return error_response("This offer is not assigned to you", status_code=403)

    action = (request.get_json(silent=True) or request.form or {}).get('action', 'accept')
    if action == 'accept':
        negotiation.status = 'Accepted'
        negotiation.customer_driver = 'Accepted'
        negotiation.is_active = 'Yes'
        dispatch.status = 'matched'
        user.busy_until = datetime.utcnow() + timedelta(minutes=90)
        db.session.commit()
        try:
            notify_user(negotiation.customer_id, "Driver found! 🎉",
                        f"{user.name} is on the way.",
                        {'type': 'ride_matched', 'negotiation_id': negotiation.id})
        except Exception:
            pass
        return success_response("Ride accepted", _status_payload(negotiation, dispatch))

    # decline → advance to next candidate
    advanced = _advance(dispatch, negotiation)
    db.session.commit()
    return success_response(
        "Passed to next driver" if advanced else "No more drivers available",
        _status_payload(negotiation, dispatch))


@rides_bp.route('/api/rides/<int:ride_id>/choose-driver', methods=['POST'])
@jwt_required_with_user
def choose_driver(user, ride_id):
    """After no_match, the customer manually picks one of the proposed drivers."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation or negotiation.customer_id != user.id:
        return error_response("Ride not found", status_code=404)
    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()
    if not dispatch:
        return error_response("No dispatch for this ride", status_code=404)
    try:
        driver_id = int((request.get_json(silent=True) or request.form or {}).get('driver_id'))
    except (TypeError, ValueError):
        return error_response("driver_id is required")
    d = db.session.get(AdminUser, driver_id)
    if not d:
        return error_response("Driver not found", status_code=404)

    lst = dispatch.candidate_list()
    lst.append(driver_id)
    dispatch.candidates = json.dumps(lst)
    dispatch.current_index = len(lst) - 1
    _offer_to(dispatch, negotiation, driver_id)
    db.session.commit()
    return success_response("Offer sent to chosen driver", _status_payload(negotiation, dispatch))


@rides_bp.route('/api/rides/<int:ride_id>/cancel', methods=['POST'])
@jwt_required_with_user
def cancel_ride(user, ride_id):
    """Customer cancels the search / ride before it starts."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation or negotiation.customer_id != user.id:
        return error_response("Ride not found", status_code=404)
    if negotiation.status in ('Started', 'Completed'):
        return error_response("Trip already " + negotiation.status)
    negotiation.status = 'Cancelled'
    negotiation.is_active = 'No'
    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()
    if dispatch:
        dispatch.status = 'cancelled'
    db.session.commit()
    return success_response("Ride cancelled")


@rides_bp.route('/api/drivers/<int:driver_id>/card', methods=['GET'])
@jwt_required_with_user
def driver_card(user, driver_id):
    """Verify a driver by ID (used by connect-by-ID / QR scan)."""
    d = db.session.get(AdminUser, driver_id)
    if not d or d.user_type not in ('Driver', 'Pending Driver'):
        return error_response("Driver not found", status_code=404)
    return success_response("Driver card", _driver_card_dict(d))
