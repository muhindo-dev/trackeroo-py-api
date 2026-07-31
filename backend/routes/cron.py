from flask import Blueprint, jsonify
from datetime import datetime, timedelta
from backend.models import db
from backend.models.admin_user import AdminUser
from backend.models.negotiation import Negotiation

cron_bp = Blueprint('cron', __name__)

@cron_bp.route('/api/cron/cleanup', methods=['POST', 'GET'])
def cleanup():
    """
    Automated cleanup tasks:
    1. Set drivers to Offline if no location update in the last 30 minutes.
    2. Cancel Active/Accepted/Pending negotiations that haven't been updated in the last 30 minutes.
    """
    try:
        thirty_mins_ago = datetime.utcnow() - timedelta(minutes=30)
        
        # 1. Auto-offline drivers
        # Drivers who are Online but haven't updated location recently
        offline_count = AdminUser.query.filter(
            AdminUser.user_type == 'driver',
            AdminUser.online_status == 'Online',
            (AdminUser.last_location_update < thirty_mins_ago) | (AdminUser.last_location_update.is_(None))
        ).update(
            {"online_status": "Offline"},
            synchronize_session=False
        )
        
        # 2. Auto-cancel inactive negotiations
        # Negotiations that are Active, Accepted, or Pending and haven't been updated recently
        cancel_count = Negotiation.query.filter(
            Negotiation.status.in_(['Active', 'Accepted', 'Pending']),
            Negotiation.updated_at < thirty_mins_ago
        ).update(
            {"status": "Cancelled", "is_active": "No"},
            synchronize_session=False
        )
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Cleanup completed",
            "drivers_offlined": offline_count,
            "negotiations_cancelled": cancel_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": "Cleanup failed",
            "error": str(e)
        }), 500
