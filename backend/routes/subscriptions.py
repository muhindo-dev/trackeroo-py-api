"""Driver subscription endpoints — Truckeroo's payment mode is subscription.

  GET  /api/subscription-plans         — list active plans
  GET  /api/subscriptions/status       — my current subscription status
  POST /api/subscriptions/subscribe    — start a subscription (Flutterwave payment link)
  POST /api/subscriptions/verify       — verify & activate a subscription by tx_ref
"""
from datetime import datetime

from flask import Blueprint, request, current_app

from backend.models import db
from backend.models.subscription import SubscriptionPlan, Subscription
from backend.utils.auth import jwt_required_with_user, admin_required
from backend.utils.response import success_response, error_response
from backend.services.flutterwave_service import (
    FlutterwaveService, FlutterwaveError, get_flutterwave,
)

subscriptions_bp = Blueprint('subscriptions', __name__)


@subscriptions_bp.route('/api/subscription-plans', methods=['GET'])
def list_plans():
    plans = SubscriptionPlan.active()
    return success_response("Subscription plans", [p.to_dict() for p in plans])


@subscriptions_bp.route('/api/subscriptions/status', methods=['GET'])
@jwt_required_with_user
def status(user):
    active = Subscription.active_for_driver(user.id)
    latest = Subscription.query.filter_by(driver_id=user.id).order_by(
        Subscription.created_at.desc()
    ).first()
    return success_response("Subscription status", {
        'is_subscribed': active is not None,
        'active': active.to_dict() if active else None,
        'latest': latest.to_dict() if latest else None,
    })


@subscriptions_bp.route('/api/admin/subscriptions', methods=['GET'])
@admin_required
def admin_list(user):
    """Admin oversight of subscriptions + simple revenue stats."""
    from sqlalchemy import func
    status = request.args.get('status')
    q = Subscription.query
    if status:
        q = q.filter_by(status=status)
    subs = q.order_by(Subscription.created_at.desc()).limit(500).all()

    revenue = float(db.session.query(func.coalesce(func.sum(Subscription.amount), 0)).filter(
        Subscription.status == 'active').scalar())
    active_count = Subscription.query.filter_by(status='active').count()

    rows = []
    for s in subs:
        d = s.to_dict()
        rows.append(d)
    return success_response("Subscriptions", {
        'subscriptions': rows,
        'active_count': active_count,
        'active_revenue': revenue,
    })


@subscriptions_bp.route('/api/subscriptions/expire', methods=['POST'])
def expire_subscriptions():
    """Mark lapsed subscriptions as expired and take those drivers offline.

    Intended to be called by a scheduler/cron. Protected by a shared secret
    (SUBSCRIPTION_CRON_SECRET) so it can run unauthenticated from a cron job.
    """
    import os
    from datetime import datetime
    from backend.models.user import AdminUser

    secret = os.getenv('SUBSCRIPTION_CRON_SECRET', '')
    provided = request.headers.get('X-Cron-Secret') or (
        request.get_json(silent=True) or {}).get('secret')
    if secret and provided != secret:
        return error_response("Forbidden", status_code=403)

    now = datetime.utcnow()
    lapsed = Subscription.query.filter(
        Subscription.status == 'active',
        Subscription.end_at < now,
    ).all()
    count = 0
    for sub in lapsed:
        sub.status = 'expired'
        driver = db.session.get(AdminUser, sub.driver_id)
        # Only force offline if they have no other still-active subscription.
        if driver and Subscription.active_for_driver(driver.id) is None:
            driver.ready_for_trip = 'No'
        count += 1
    db.session.commit()
    return success_response("Expired lapsed subscriptions", {'expired': count})


@subscriptions_bp.route('/api/subscriptions/subscribe', methods=['POST'])
@jwt_required_with_user
def subscribe(user):
    data = request.get_json(silent=True) or request.form or {}
    try:
        plan_id = int(data.get('plan_id'))
    except (TypeError, ValueError):
        return error_response("Valid plan_id is required")
    plan = db.session.get(SubscriptionPlan, plan_id)
    if not plan or not plan.is_active:
        return error_response("Valid plan_id is required")

    tx_ref = FlutterwaveService.generate_tx_ref('sub')
    sub = Subscription(
        driver_id=user.id,
        plan_id=plan.id,
        tx_ref=tx_ref,
        amount=plan.amount,
        currency=plan.currency or 'NGN',
        status='pending',
    )
    db.session.add(sub)
    db.session.flush()

    try:
        flw = get_flutterwave()
        app_url = current_app.config.get('APP_URL') or current_app.config.get('BASE_URL') or ''
        result = flw.initialize_payment(
            amount=float(plan.amount or 0),
            tx_ref=tx_ref,
            customer_name=user.name or 'Truckeroo Driver',
            customer_email=user.email or f"driver_{user.id}@truckeroo.com",
            customer_phone=user.phone_number or '',
            description=f"Truckeroo {plan.name} subscription",
            redirect_url=f"{app_url}/api/flutterwave/callback" if app_url else None,
            meta={'type': 'subscription', 'subscription_id': sub.id, 'driver_id': user.id},
        )
    except FlutterwaveError as e:
        db.session.rollback()
        return error_response(f"Could not start payment: {e}")

    db.session.commit()
    return success_response("Subscription payment initialized", {
        'subscription_id': sub.id,
        'tx_ref': tx_ref,
        'payment_link': result['payment_link'],
        'amount': float(plan.amount or 0),
        'plan': plan.to_dict(),
    })


@subscriptions_bp.route('/api/subscriptions/verify', methods=['POST'])
@jwt_required_with_user
def verify(user):
    data = request.get_json(silent=True) or request.form or {}
    tx_ref = data.get('tx_ref')
    if not tx_ref:
        return error_response("tx_ref is required")

    sub = Subscription.query.filter_by(tx_ref=tx_ref, driver_id=user.id).first()
    if not sub:
        return error_response("Subscription not found", status_code=404)

    if sub.is_active_now:
        return success_response("Subscription already active", sub.to_dict())

    try:
        flw = get_flutterwave()
        verification = flw.verify_by_tx_ref(tx_ref)
        ok = flw.is_payment_successful(verification, expected_amount=float(sub.amount or 0))
    except FlutterwaveError as e:
        return error_response(f"Verification failed: {e}")

    if not ok:
        return error_response("Payment not successful yet", sub.to_dict())

    # Idempotent activation shared with the webhook path.
    activated = Subscription.activate_by_tx_ref(tx_ref)
    return success_response("Subscription activated", (activated or sub).to_dict())
