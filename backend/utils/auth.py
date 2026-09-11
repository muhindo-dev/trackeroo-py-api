from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from backend.models import db
from backend.models.user import AdminUser


def get_current_user():
    """Return the caller, identified solely by a verified JWT.

    This used to fall back to a `user_id` in the query string or body whenever
    JWT verification failed — including when no token was sent at all. That was
    a complete authentication bypass: with sequential user ids, anyone could act
    as anyone by adding `?user_id=N`, and because admin_required() uses this same
    helper it also handed out admin powers. Proven against production with
    `POST /api/update-online-status {"user_id": <driver>, "status": "offline"}`
    and no Authorization header, which returned 200 and took that driver offline.

    The apps have always sent `Authorization: Bearer <token>`; the fallback was
    only ever masking expired sessions, which should re-authenticate instead.
    """
    try:
        verify_jwt_in_request()
        user_id = get_jwt_identity()
    except Exception:
        return None
    if user_id is None:
        return None
    try:
        return db.session.get(AdminUser, int(user_id))
    except (TypeError, ValueError):
        return None


def jwt_required_with_user(fn):
    """Decorator that provides the current user to the route function."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        return fn(user, *args, **kwargs)
    return wrapper


def admin_required(fn):
    """Decorator that requires the current user to be an Admin."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        if user.user_type not in ('Admin', 'Super Admin'):
            return jsonify({'code': 0, 'message': 'Admin access required'}), 403
        return fn(user, *args, **kwargs)
    return wrapper


def admin_required_strict(fn):
    """Like admin_required but WITHOUT the legacy user_id body fallback.

    The fallback in get_current_user() lets any request authenticate by
    passing user_id=<some admin id>, which is fine for ordinary endpoints on
    this live app but must never gate sensitive god-mode controls (set GPS,
    force online, impersonate). Here we require a genuinely verified JWT.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            user = db.session.get(AdminUser, int(user_id))
        except Exception:
            user = None
        if not user:
            return jsonify({'code': 0, 'message': 'Unauthorized'}), 401
        if user.user_type not in ('Admin', 'Super Admin'):
            return jsonify({'code': 0, 'message': 'Admin access required'}), 403
        return fn(user, *args, **kwargs)
    return wrapper
