from flask import Blueprint, request
from datetime import datetime
from backend.models import db
from backend.models.user import AdminUser
from backend.models.negotiation import Negotiation
from backend.models.popular_location import PopularLocation
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

location_bp = Blueprint('location', __name__)


def _subscription_block(user, going_online):
    """Return an error_response if a driver may not go online, else None.

    Truckfully's payment mode is subscription: a driver can only go online with
    an active subscription. Customers/owners who aren't drivers are unaffected.
    """
    if not going_online:
        return None
    if user.user_type not in ('Driver', 'Pending Driver'):
        return None
    from backend.models.subscription import Subscription
    if Subscription.active_for_driver(user.id) is None:
        return error_response(
            "An active subscription is required to go online.",
            {'requires_subscription': True}, status_code=402,
        )
    return None


@location_bp.route('/api/go-on-off', methods=['POST'])
@jwt_required_with_user
def go_on_off(user):
    """Toggle driver online/offline. Updates GPS and last_location_update."""
    data = request.get_json(silent=True) or request.form
    lati = data.get('lati')
    long_ = data.get('long')
    status = data.get('status')

    if not all([lati, long_, status]):
        return error_response("lati, long, and status are required")

    if status not in ('online', 'offline'):
        return error_response("Status must be 'online' or 'offline'")

    blocked = _subscription_block(user, status == 'online')
    if blocked is not None:
        return blocked

    # ready_for_trip is the real DB column (varchar 'Yes'/'No')
    user.current_latitude = lati
    user.current_longitude = long_
    user.location_updated_at = datetime.utcnow()
    user.current_address = f"{lati},{long_}"
    user.ready_for_trip = 'Yes' if status == 'online' else 'No'
    # V2: capture the service group the driver goes live for
    if status == 'online':
        group = (data.get('service_group') or '').strip()
        if group:
            user.live_service_group = group
    else:
        user.live_service_group = None
    user.last_location_update = datetime.utcnow()

    db.session.commit()

    return success_response(f"Success!, you are now {status}.", status)


@location_bp.route('/api/update-online-status', methods=['POST'])
@jwt_required_with_user
def update_online_status(user):
    """Flexible status update. If no status param, returns current."""
    data = request.get_json(silent=True) or request.form
    status = data.get('status')
    lat = data.get('latitude') or data.get('lati')
    lng = data.get('longitude') or data.get('long')

    if lat:
        user.current_latitude = lat
    if lng:
        user.current_longitude = lng
        user.location_updated_at = datetime.utcnow()

    if status:
        if status not in ('online', 'offline'):
            return error_response("Status must be 'online' or 'offline'")
        blocked = _subscription_block(user, status == 'online')
        if blocked is not None:
            return blocked
        user.ready_for_trip = 'Yes' if status == 'online' else 'No'
        # V2: driver declares which service they're going live for (dynamic groups)
        if status == 'online':
            group = (data.get('service_group') or '').strip()
            if group:
                from backend.models.vehicle_category import VehicleCategory
                valid = {g[0] for g in db.session.query(
                    VehicleCategory.service_group).filter_by(is_active=1).distinct()}
                if group not in valid:
                    return error_response(
                        f"Invalid service_group. Choose one of: {', '.join(sorted(valid))}")
                user.live_service_group = group
        else:
            user.live_service_group = None
        if lat or lng:
            user.last_location_update = datetime.utcnow()
    else:
        # Return current status
        db.session.commit()
        return success_response("Success", 'online' if user.ready_for_trip == 'Yes' else 'offline')

    db.session.commit()
    return success_response("Success", 'online' if user.ready_for_trip == 'Yes' else 'offline')


@location_bp.route('/api/refresh-status', methods=['POST'])
@jwt_required_with_user
def refresh_status(user):
    """Get driver status + active trip info."""
    data = request.get_json(silent=True) or request.form
    lati = data.get('lati')
    long_ = data.get('long')

    if lati:
        user.current_latitude = lati
    if long_:
        user.current_longitude = long_
        user.location_updated_at = datetime.utcnow()

    # Check for active trip (negotiation)
    active_trip = Negotiation.query.filter(
        Negotiation.driver_id == user.id,
        Negotiation.status.in_(['Accepted', 'Started']),
    ).order_by(Negotiation.created_at.desc()).first()

    db.session.commit()

    return success_response("Success", {
        'status': 'online' if user.ready_for_trip == 'Yes' else 'offline',
        'has_trip': 'Yes' if active_trip else 'No',
        'trip': active_trip.to_dict() if active_trip else None,
    })


@location_bp.route('/api/update-location', methods=['POST'])
@jwt_required_with_user
def update_location(user):
    """Update user's GPS coordinates."""
    data = request.get_json(silent=True) or request.form
    lat = data.get('latitude')
    lng = data.get('longitude')

    if lat is None or lng is None:
        return error_response("latitude and longitude are required")

    lat = float(lat)
    lng = float(lng)
    if lat < -90 or lat > 90:
        return error_response("Invalid latitude")
    if lng < -180 or lng > 180:
        return error_response("Invalid longitude")

    user.current_latitude = str(lat)
    user.current_longitude = str(lng)
    user.location_updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Success", {
        'latitude': user.current_latitude,
        'longitude': user.current_longitude,
        'current_address': user.current_address,
        'updated_at': str(user.updated_at),
    })


@location_bp.route('/api/locations/popular', methods=['GET'])
def popular_locations():
    """Public endpoint — return popular locations matching a search query.
    Returns up to `limit` results (default 3) ordered by sort_order.
    """
    query = (request.args.get('query') or '').strip()
    limit = min(int(request.args.get('limit', 3)), 10)

    q = PopularLocation.query.filter_by(is_active=1).order_by(
        PopularLocation.sort_order.asc(),
        PopularLocation.name.asc(),
    )
    all_locs = q.all()

    if query:
        results = [loc for loc in all_locs if loc.matches(query)]
    else:
        results = all_locs

    return success_response("Success", [loc.to_dict() for loc in results[:limit]])


@location_bp.route('/api/important-contacts/update-location', methods=['POST'])
@jwt_required_with_user
def update_location_alt(user):
    """Duplicate route – same as update-location."""
    data = request.get_json(silent=True) or request.form
    lat = data.get('latitude')
    lng = data.get('longitude')

    if lat:
        user.current_latitude = str(lat)
    if lng:
        user.current_longitude = str(lng)
        user.location_updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Success", {
        'latitude': user.current_latitude,
        'longitude': user.current_longitude,
        'current_address': user.current_address,
        'updated_at': str(user.updated_at),
    })
