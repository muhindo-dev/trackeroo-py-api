"""Authenticated background maintenance for live driver and trip state."""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify
from sqlalchemy import or_

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.user import AdminUser
from backend.utils.cron_auth import cron_auth_error

cron_bp = Blueprint('cron', __name__)


@cron_bp.route('/api/cron/cleanup', methods=['POST'])
def cleanup():
    """Expire stale online drivers and abandoned, unaccepted ride requests."""
    auth_error = cron_auth_error()
    if auth_error is not None:
        return auth_error

    try:
        threshold = datetime.utcnow() - timedelta(minutes=30)
        drivers_offline = AdminUser.query.filter(
            AdminUser.user_type == 'Driver',
            AdminUser.ready_for_trip == 'Yes',
            or_(
                AdminUser.location_updated_at < threshold,
                AdminUser.location_updated_at.is_(None),
            ),
        ).update({'ready_for_trip': 'No'}, synchronize_session=False)

        rides_cancelled = Negotiation.query.filter(
            Negotiation.status == 'Active',
            Negotiation.updated_at < threshold,
        ).update(
            {'status': 'Cancelled', 'is_active': 'No'},
            synchronize_session=False,
        )
        db.session.commit()
        return jsonify({
            'code': 1,
            'message': 'Cleanup complete',
            'data': {
                'drivers_offline': drivers_offline,
                'negotiations_cancelled': rides_cancelled,
            },
        }), 200
    except Exception:
        db.session.rollback()
        return jsonify({'code': 0, 'message': 'Cleanup failed'}), 500
