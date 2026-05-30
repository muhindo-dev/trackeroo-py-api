"""Driver ratings — submit, retrieve, and check ratings for completed trips."""

from datetime import datetime
from flask import Blueprint, request
from sqlalchemy import func
from backend.models import db
from backend.models.driver_rating import DriverRating
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

ratings_bp = Blueprint('ratings', __name__)


@ratings_bp.route('/api/ratings', methods=['POST'])
@jwt_required_with_user
def submit_rating(user):
    """Customer submits a rating for a completed + paid booking."""
    data = request.get_json(silent=True) or request.form

    booking_id = int(data.get('booking_id', 0))
    rating_val = int(data.get('rating', 0))
    comment = data.get('comment', '').strip()

    if not booking_id:
        return error_response("booking_id is required")
    if rating_val < 1 or rating_val > 5:
        return error_response("Rating must be between 1 and 5")

    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    if booking.customer_id != user.id:
        return error_response("You can only rate your own bookings", status_code=403)

    if booking.status not in ('completed', 'Completed'):
        return error_response("You can only rate completed trips")

    if booking.payment_status not in ('paid', 'payment_completed', 'succeeded'):
        return error_response("Rating is only available after payment is completed")

    if not booking.driver_id:
        return error_response("No driver assigned to this booking")

    # Check for duplicate
    existing = DriverRating.query.filter_by(
        customer_id=user.id, booking_id=booking_id
    ).first()
    if existing:
        return error_response("You have already rated this trip")

    rating = DriverRating(
        customer_id=user.id,
        driver_id=booking.driver_id,
        booking_id=booking_id,
        rating=rating_val,
        comment=comment or None,
    )
    db.session.add(rating)

    # Update driver's average rating
    new_avg = db.session.query(
        func.avg(DriverRating.rating)
    ).filter_by(driver_id=booking.driver_id).scalar() or rating_val

    driver = AdminUser.query.get(booking.driver_id)
    if driver:
        driver.rating = round(float(new_avg), 2)

    db.session.commit()

    return success_response("Rating submitted. Thank you!", rating.to_dict(), status_code=201)


@ratings_bp.route('/api/ratings/driver/<int:driver_id>', methods=['GET'])
def driver_ratings(driver_id):
    """Get all ratings for a driver with stats."""
    stats = DriverRating.get_driver_stats(driver_id)
    recent = DriverRating.query.filter_by(driver_id=driver_id).order_by(
        DriverRating.created_at.desc()
    ).limit(20).all()

    return success_response("Success", {
        **stats,
        'ratings': [r.to_dict() for r in recent],
    })


@ratings_bp.route('/api/ratings/booking/<int:booking_id>', methods=['GET'])
@jwt_required_with_user
def booking_rating_status(user, booking_id):
    """Check whether this booking has been rated by the current user."""
    existing = DriverRating.query.filter_by(
        customer_id=user.id, booking_id=booking_id
    ).first()
    return success_response("Success", {
        'rated': existing is not None,
        'rating': existing.to_dict() if existing else None,
    })


@ratings_bp.route('/api/drivers/available', methods=['GET'])
def available_drivers():
    """Return online drivers (optionally filtered by vehicle/service type) with ratings."""
    service_type = request.args.get('service_type', '')
    vehicle_type = request.args.get('vehicle_type', '')

    q = AdminUser.query.filter(
        AdminUser.user_type == 'Driver',
        AdminUser.ready_for_trip == 'Yes',
        AdminUser.deleted_at.is_(None),
    )

    if vehicle_type:
        q = q.filter(AdminUser.vehicle_type == vehicle_type)

    drivers = q.order_by(AdminUser.rating.desc()).limit(30).all()

    result = []
    for d in drivers:
        stats = DriverRating.get_driver_stats(d.id)
        result.append({
            'id': d.id,
            'name': d.name,
            'avatar': d.avatar,
            'vehicle_type': d.vehicle_type,
            'automobile': d.automobile,
            'rating': stats['average_rating'],
            'total_ratings': stats['total_ratings'],
            'is_online': d.ready_for_trip == 'Yes',
            'current_latitude': str(d.current_latitude) if d.current_latitude else None,
            'current_longitude': str(d.current_longitude) if d.current_longitude else None,
        })

    return success_response("Success", result)
