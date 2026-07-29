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

# Sanity limits. A bad/stale GPS fix (e.g. an emulator sitting in California
# while the destination is in Lagos) used to produce a 16,000 km trip whose
# fare overflowed negotiations.agreed_price DECIMAL(10,2) — a hard 500.
MAX_TRIP_KM = 1500.0
MAX_TRIP_MINUTES = 24 * 60
MAX_FARE = 900000.0            # ₦ — anything above this is a data error
PRICE_CENTS_CEILING = 99999999  # DECIMAL(10,2) holds at most 99,999,999.99

# Book for later
MIN_SCHEDULE_MINUTES = 10      # must be at least this far out
MAX_SCHEDULE_DAYS = 30
LEAD_MINUTES = 15              # start hunting a driver this early


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _price_cents(price):
    """Legacy cents convention, clamped so it can never overflow the column."""
    return min(int(round(_num(price) * 100)), PRICE_CENTS_CEILING)


def _validate_trip(data):
    """Reject impossible trips up front. Returns an error message or None."""
    km = _num(data.get('distance_km'))
    if km < 0:
        return "Trip distance is invalid."
    if km > MAX_TRIP_KM:
        return (f"That trip is {int(km):,} km — beyond our service area. "
                "Check your pickup and destination.")
    if _num(data.get('duration_min')) > MAX_TRIP_MINUTES:
        return "That trip is too long to book in the app."
    return None


def _parse_scheduled_at(raw):
    """Parse a 'book for later' timestamp. Returns (datetime|None, error|None).

    The app sends local wall-clock time as ISO-8601; we store naive UTC to match
    the rest of the schema, so the app must send UTC (it does — toUtc()).
    """
    if raw in (None, '', 'null'):
        return None, None
    text = str(raw).strip().replace('Z', '')
    if text.endswith('+00:00'):
        text = text[:-6]
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None, "Invalid pickup time."
    if when.tzinfo is not None:
        when = when.astimezone(tz=None).replace(tzinfo=None)
    now = datetime.utcnow()
    if when < now + timedelta(minutes=MIN_SCHEDULE_MINUTES):
        return None, (f"Pick a time at least {MIN_SCHEDULE_MINUTES} minutes "
                      "from now.")
    if when > now + timedelta(days=MAX_SCHEDULE_DAYS):
        return None, f"You can only book up to {MAX_SCHEDULE_DAYS} days ahead."
    return when, None


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


def _begin_dispatch(dispatch, negotiation):
    """Start (or restart) the hunt for a driver: rank, then offer to the best.

    A dispatch that already carries a candidate list is a direct connect
    (customer chose a driver by ID/QR) — keep it. Otherwise rank live drivers
    now, which is what makes a ride booked hours ago dispatch against whoever
    is actually online at pickup time.
    """
    candidates = dispatch.candidate_list()
    if not candidates:
        ranked = _ranked_candidates(dispatch.service_group,
                                    _num(negotiation.pickup_lat),
                                    _num(negotiation.pickup_lng))
        candidates = [d.id for d, _ in ranked]
        dispatch.candidates = json.dumps(candidates)
    dispatch.current_index = 0
    if candidates:
        _offer_to(dispatch, negotiation, candidates[0])
    else:
        dispatch.status = 'no_match'
        dispatch.offer_expires_at = None
    negotiation.status = 'Active'
    negotiation.is_active = 'Yes'
    return bool(candidates)


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

    trip_error = _validate_trip(data)
    if trip_error:
        return error_response(trip_error)

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

    trip_error = _validate_trip(data)
    if trip_error:
        return error_response(trip_error)

    scheduled_at, sched_error = _parse_scheduled_at(data.get('scheduled_at'))
    if sched_error:
        return error_response(sched_error)

    est = _estimate(category, data)
    price = _num(est.get('estimate'))
    if price > MAX_FARE:
        return error_response(
            "That fare is outside our limits — please check the trip details.")

    payment_method = (data.get('payment_method') or '').strip() or None
    if payment_method and payment_method not in ('MM', 'Visa', 'Cash'):
        payment_method = 'Cash'

    # Direct connect to a specific driver (ID / QR)? Validate before writing.
    direct_id = data.get('driver_id')
    candidates = []
    if direct_id not in (None, '', 'null'):
        try:
            direct_id = int(direct_id)
        except (TypeError, ValueError):
            return error_response("Invalid driver_id")
        d = db.session.get(AdminUser, direct_id)
        if not d or d.user_type not in ('Driver', 'Pending Driver'):
            return error_response("Driver not found", status_code=404)
        candidates = [direct_id]

    note = (data.get('schedule_note') or '').strip()[:500] or None

    negotiation = Negotiation(
        customer_id=user.id,
        customer_name=user.name,
        pickup_lat=str(pickup_lat), pickup_lng=str(pickup_lng),
        pickup_address=data.get('pickup_address'),
        dropoff_lat=str(_num(data.get('dropoff_lat'))), dropoff_lng=str(_num(data.get('dropoff_lng'))),
        dropoff_address=data.get('dropoff_address'),
        initial_price=_price_cents(price),      # legacy cents field
        agreed_price=_price_cents(price),       # fixed system price (cents convention)
        status='Scheduled' if scheduled_at else 'Active',
        is_active='Yes',
        customer_accepted='Accepted', customer_driver='Pending',
        payment_method=payment_method,
        ride_source='scheduled' if scheduled_at else 'instant',
        scheduled_at=scheduled_at,
        schedule_note=note,
    )
    db.session.add(negotiation)
    db.session.flush()

    dispatch = RideDispatch(
        negotiation_id=negotiation.id,
        customer_id=user.id,
        category_id=category.id,
        service_group=category.service_group,
        candidates=json.dumps(candidates),
        current_index=0,
        scheduled_at=scheduled_at,
    )
    db.session.add(dispatch)

    if scheduled_at:
        # Nothing to dispatch yet — the sweeper (or a status poll) picks it up
        # LEAD_MINUTES before pickup.
        dispatch.status = 'scheduled'
    else:
        _begin_dispatch(dispatch, negotiation)

    try:
        db.session.commit()
    except Exception as exc:                     # never leak a raw 500
        db.session.rollback()
        return error_response(
            "We couldn't create that ride. Please check the trip details and try again.",
            data={'detail': str(exc)[:200]}, status_code=400)

    return success_response(
        "Ride scheduled" if scheduled_at else "Ride requested", {
            'ride_id': negotiation.id,
            'dispatch': dispatch.to_dict(),
            'estimate': price,
            'scheduled_at': negotiation.scheduled_at.isoformat() if scheduled_at else None,
            'negotiation': negotiation.to_dict(),
        })


def _status_payload(negotiation, dispatch, include_proposals=False):
    payload = {
        'ride_id': negotiation.id,
        'ride_status': negotiation.status,
        'dispatch_status': dispatch.status if dispatch else None,
        'scheduled_at': negotiation.scheduled_at.isoformat() if negotiation.scheduled_at else None,
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
        # When nobody can take it now, booking for later is the way out.
        payload['can_schedule'] = negotiation.scheduled_at is None
        payload['suggested_times'] = _suggested_times()
    return payload


def _suggested_times():
    """A few sensible 'book for later' slots, rounded to the next half hour."""
    now = datetime.utcnow()
    base = (now + timedelta(minutes=30)).replace(second=0, microsecond=0)
    base = base.replace(minute=0 if base.minute < 30 else 30)
    out = []
    for label, delta in (('In 1 hour', timedelta(hours=1)),
                         ('In 3 hours', timedelta(hours=3)),
                         ('Tomorrow morning', None)):
        if delta is None:
            when = (now + timedelta(days=1)).replace(
                hour=7, minute=0, second=0, microsecond=0)
        else:
            when = base + delta
        out.append({'label': label, 'at': when.isoformat()})
    return out


@rides_bp.route('/api/rides/<int:ride_id>/status', methods=['GET'])
@jwt_required_with_user
def ride_status(user, ride_id):
    """Poll ride status. Lazily advances expired offers (serverless dispatch)."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation:
        return error_response("Ride not found", status_code=404)
    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()

    if dispatch and dispatch.status == 'scheduled' and _is_due(dispatch):
        _begin_dispatch(dispatch, negotiation)
        db.session.commit()
    elif dispatch and dispatch.status == 'offered':
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


def _is_due(dispatch):
    """A scheduled dispatch is due LEAD_MINUTES before the pickup time."""
    if not dispatch.scheduled_at:
        return True
    return datetime.utcnow() >= dispatch.scheduled_at - timedelta(minutes=LEAD_MINUTES)


@rides_bp.route('/api/rides/scheduled', methods=['GET'])
@jwt_required_with_user
def scheduled_rides(user):
    """The customer's upcoming 'book for later' rides."""
    rows = Negotiation.query.filter(
        Negotiation.customer_id == user.id,
        Negotiation.scheduled_at.isnot(None),
        Negotiation.status.notin_(['Cancelled', 'Completed']),
    ).order_by(Negotiation.scheduled_at.asc()).limit(50).all()

    items = []
    for n in rows:
        d = RideDispatch.query.filter_by(negotiation_id=n.id).first()
        items.append({
            'ride_id': n.id,
            'ride_status': n.status,
            'dispatch_status': d.status if d else None,
            'scheduled_at': n.scheduled_at.isoformat() if n.scheduled_at else None,
            'pickup_address': n.pickup_address,
            'dropoff_address': n.dropoff_address,
            'schedule_note': n.schedule_note,
            'payment_method': n.payment_method,
            'price': (float(n.agreed_price) / 100.0) if n.agreed_price else 0.0,
            'service_group': d.service_group if d else None,
            'driver_name': n.driver_name,
        })
    return success_response("Scheduled rides", items)


@rides_bp.route('/api/rides/<int:ride_id>/start-now', methods=['POST'])
@jwt_required_with_user
def start_scheduled_now(user, ride_id):
    """Customer decides not to wait — dispatch a scheduled ride immediately."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation or negotiation.customer_id != user.id:
        return error_response("Ride not found", status_code=404)
    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()
    if not dispatch or dispatch.status != 'scheduled':
        return error_response("This ride is not waiting on a schedule")

    negotiation.scheduled_at = None
    dispatch.scheduled_at = None
    _begin_dispatch(dispatch, negotiation)
    db.session.commit()
    return success_response("Searching for a driver now",
                            _status_payload(negotiation, dispatch, include_proposals=True))


@rides_bp.route('/api/rides/<int:ride_id>/reschedule', methods=['POST'])
@jwt_required_with_user
def reschedule_ride(user, ride_id):
    """Move a scheduled ride to a different time (also used to book a failed
    instant ride for later instead of cancelling it)."""
    negotiation = db.session.get(Negotiation, ride_id)
    if not negotiation or negotiation.customer_id != user.id:
        return error_response("Ride not found", status_code=404)
    if negotiation.status in ('Accepted', 'Started', 'Completed'):
        return error_response("This trip is already under way")

    data = request.get_json(silent=True) or request.form or {}
    when, err = _parse_scheduled_at(data.get('scheduled_at'))
    if err:
        return error_response(err)
    if not when:
        return error_response("scheduled_at is required")

    dispatch = RideDispatch.query.filter_by(negotiation_id=ride_id).first()
    if not dispatch:
        return error_response("No dispatch for this ride", status_code=404)

    note = (data.get('schedule_note') or '').strip()[:500]
    if note:
        negotiation.schedule_note = note
    negotiation.scheduled_at = when
    negotiation.status = 'Scheduled'
    negotiation.is_active = 'Yes'
    negotiation.ride_source = 'scheduled'
    negotiation.driver_id = None
    negotiation.driver_name = None
    dispatch.scheduled_at = when
    dispatch.status = 'scheduled'
    dispatch.offer_expires_at = None
    dispatch.candidates = json.dumps([])   # re-rank against who's live at pickup time
    dispatch.current_index = 0
    db.session.commit()
    return success_response("Ride booked for later",
                            _status_payload(negotiation, dispatch))


@rides_bp.route('/api/rides/dispatch-due', methods=['POST'])
def dispatch_due():
    """Cron: start dispatching every scheduled ride that has come due.

    Polling from the customer's app does the same thing lazily, but this makes
    it work when nobody has the app open.
    """
    import os
    secret = os.getenv('SUBSCRIPTION_CRON_SECRET', '')
    provided = request.headers.get('X-Cron-Secret') or (
        request.get_json(silent=True) or {}).get('secret')
    if secret and provided != secret:
        return error_response("Forbidden", status_code=403)

    cutoff = datetime.utcnow() + timedelta(minutes=LEAD_MINUTES)
    due = RideDispatch.query.filter(
        RideDispatch.status == 'scheduled',
        RideDispatch.scheduled_at.isnot(None),
        RideDispatch.scheduled_at <= cutoff,
    ).limit(200).all()

    started, matched = 0, 0
    for d in due:
        n = db.session.get(Negotiation, d.negotiation_id)
        if not n or n.status in ('Cancelled', 'Completed'):
            d.status = 'cancelled'
            continue
        if _begin_dispatch(d, n):
            matched += 1
        started += 1
        try:
            notify_user(n.customer_id, "Your booked ride is starting 🚕",
                        "We're finding you a driver now.",
                        {'type': 'ride_scheduled_start', 'negotiation_id': n.id})
        except Exception:
            pass
    db.session.commit()
    return success_response("Due rides dispatched",
                            {'started': started, 'with_candidates': matched})


@rides_bp.route('/api/drivers/<int:driver_id>/card', methods=['GET'])
@jwt_required_with_user
def driver_card(user, driver_id):
    """Verify a driver by ID (used by connect-by-ID / QR scan)."""
    d = db.session.get(AdminUser, driver_id)
    if not d or d.user_type not in ('Driver', 'Pending Driver'):
        return error_response("Driver not found", status_code=404)
    return success_response("Driver card", _driver_card_dict(d))
