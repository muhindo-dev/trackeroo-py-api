"""Driver subscription endpoints — Truckfully's payment mode is subscription.

  GET  /api/subscription-plans         — list active plans
  GET  /api/subscriptions/status       — my current subscription status
  POST /api/subscriptions/subscribe    — start a subscription (Flutterwave payment link)
  POST /api/subscriptions/verify       — verify & activate a subscription by tx_ref
"""
from datetime import datetime

from flask import Blueprint, request, current_app

from backend.models import db
from backend.models.subscription import SubscriptionPlan, Subscription
from backend.models.grace_policy import DriverGracePolicy
from backend.services.grace_period_service import active_policy, offer_dict, apply_grace
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
    # Signup and "become driver" both attempt the grant, but a status refresh
    # is also a safe repair point for accounts created while a policy was
    # active. apply_grace is idempotent per driver/policy, and the eligibility
    # group is derived from the account's original registration type so an old
    # driver cannot consume a new-driver offer.
    policy = None
    registered_as_driver = (getattr(user, 'account_type', '') or '').strip().lower() == 'driver'
    is_driver = registered_as_driver or user.user_type in ('Pending Driver', 'Driver')
    can_receive_grace = is_driver and Subscription.active_for_driver(user.id) is None
    if can_receive_grace and registered_as_driver:
        candidate = active_policy(existing=False)
        created_at = getattr(user, 'created_at', None)
        now = datetime.utcnow()
        if candidate and created_at and candidate.start_at <= created_at <= min(candidate.end_at, now):
            if not Subscription.query.filter_by(driver_id=user.id, grace_policy_id=candidate.id).first():
                if apply_grace(user, existing=False, policy=candidate):
                    policy = candidate
        else:
            # Drivers who existed before the signup window are covered only
            # when the admin explicitly enabled the existing-driver audience.
            existing_policy = active_policy(existing=True)
            if existing_policy and created_at and created_at < existing_policy.start_at:
                if not Subscription.query.filter_by(driver_id=user.id, grace_policy_id=existing_policy.id).first():
                    if apply_grace(user, existing=True, policy=existing_policy):
                        policy = existing_policy
    elif can_receive_grace:
        candidate = active_policy(existing=True)
        if candidate and not Subscription.query.filter_by(driver_id=user.id, grace_policy_id=candidate.id).first():
            if apply_grace(user, existing=True, policy=candidate):
                policy = candidate
    if policy:
        db.session.commit()

    active = Subscription.active_for_driver(user.id)
    latest = Subscription.query.filter_by(driver_id=user.id).order_by(
        Subscription.created_at.desc()
    ).first()
    return success_response("Subscription status", {
        'is_subscribed': active is not None,
        'active': active.to_dict() if active else None,
        'latest': latest.to_dict() if latest else None,
        'grace_offer': offer_dict(policy),
    })


@subscriptions_bp.route('/api/driver-grace-offer', methods=['GET'])
def grace_offer():
    return success_response("Driver grace offer", offer_dict(active_policy()))


@subscriptions_bp.route('/api/admin/subscription-grace-policies', methods=['GET'])
@admin_required
def grace_policies(user):
    return success_response("Driver grace policies", [p.to_dict() for p in DriverGracePolicy.query.order_by(DriverGracePolicy.created_at.desc()).all()])


@subscriptions_bp.route('/api/admin/subscription-grace-policies', methods=['POST'])
@admin_required
def create_grace_policy(user):
    data = request.get_json(silent=True) or {}
    try:
        def parse_datetime(value):
            # Accept HTML datetime-local values and ISO-8601 payloads without
            # adding a runtime dependency to the production image.
            value = str(value).strip().replace('Z', '+00:00')
            parsed = datetime.fromisoformat(value)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        start_at, end_at = parse_datetime(data['start_at']), parse_datetime(data['end_at'])
        if end_at <= start_at: raise ValueError('end_at must be after start_at')
        plan = db.session.get(SubscriptionPlan, int(data['plan_id']))
        if not plan: raise ValueError('Invalid subscription plan')
        apply_new = bool(data.get('apply_to_new_drivers', True))
        apply_existing = bool(data.get('apply_to_existing', False))
        if not (apply_new or apply_existing): raise ValueError('Select at least one eligible driver group')
        max_redemptions = int(data['max_redemptions']) if data.get('max_redemptions') not in (None, '') else None
        if max_redemptions is not None and max_redemptions < 1: raise ValueError('max_redemptions must be at least 1')
        p = DriverGracePolicy(name=(data.get('name') or 'New driver offer').strip(), plan_id=plan.id,
            start_at=start_at, end_at=end_at, duration_days=max(int(data.get('duration_days') or plan.duration_days or 7), 1),
            apply_to_new_drivers=1 if apply_new else 0,
            apply_to_existing=1 if apply_existing else 0,
            max_redemptions=max_redemptions,
            is_active=1 if data.get('is_active', True) else 0, notes=data.get('notes'), created_by=user.id)
        db.session.add(p)
        db.session.flush()
        applied = _apply_policy_to_existing(p) if p.apply_to_existing else 0
        db.session.commit()
        result = p.to_dict(); result['existing_drivers_applied'] = applied
        return success_response("Grace policy created", result, status_code=201)
    except (KeyError, TypeError, ValueError) as exc:
        db.session.rollback(); return error_response(str(exc), 422)


@subscriptions_bp.route('/api/admin/subscription-grace-policies/<int:policy_id>', methods=['PUT'])
@admin_required
def update_grace_policy(user, policy_id):
    p = db.session.get(DriverGracePolicy, policy_id)
    if not p: return error_response('Grace policy not found', 404)
    data = request.get_json(silent=True) or {}
    try:
        if 'plan_id' in data:
            plan = db.session.get(SubscriptionPlan, int(data['plan_id']))
            if not plan:
                db.session.rollback(); return error_response('Invalid subscription plan', 422)
            p.plan = plan
        if 'start_at' in data: p.start_at = datetime.fromisoformat(str(data['start_at']).replace('Z', '+00:00')).replace(tzinfo=None)
        if 'end_at' in data: p.end_at = datetime.fromisoformat(str(data['end_at']).replace('Z', '+00:00')).replace(tzinfo=None)
        if p.end_at <= p.start_at:
            db.session.rollback(); return error_response('End date must be after start date', 422)
        if 'max_redemptions' in data: p.max_redemptions = int(data['max_redemptions']) if data['max_redemptions'] else None
        if 'duration_days' in data:
            p.duration_days = int(data['duration_days'])
            if p.duration_days < 1: raise ValueError('duration_days must be at least 1')
        if p.max_redemptions is not None and p.max_redemptions < 1:
            raise ValueError('max_redemptions must be at least 1')
        if 'name' in data and not str(data['name']).strip():
            raise ValueError('name is required')
    except (TypeError, ValueError) as exc:
        db.session.rollback(); return error_response(f'Invalid policy value: {exc}', 422)
    for key in ('name', 'notes'):
        if key in data: setattr(p, key, data[key])
    for key in ('apply_to_new_drivers', 'apply_to_existing', 'is_active'):
        if key in data: setattr(p, key, 1 if data[key] else 0)
    if not (p.apply_to_new_drivers or p.apply_to_existing):
        db.session.rollback(); return error_response('Select at least one eligible driver group', 422)
    if 'name' in data: p.name = str(data['name']).strip()
    if 'notes' in data: p.notes = data['notes']
    db.session.flush()
    if any(k in data for k in ('plan_id', 'duration_days')):
        now = datetime.utcnow()
        for grant in Subscription.query.filter_by(grace_policy_id=p.id, is_grace=1, status='active').all():
            if grant.end_at and grant.end_at >= now:
                grant.plan_id = p.plan_id
                grant.amount = 0
                grant.currency = p.plan.currency if p.plan else grant.currency
                if grant.start_at:
                    from datetime import timedelta
                    grant.end_at = grant.start_at + timedelta(days=p.duration_days)
                if grant.end_at < now: grant.status = 'expired'
    applied = _apply_policy_to_existing(p) if p.apply_to_existing and p.is_active else 0
    db.session.commit()
    result = p.to_dict(); result['existing_drivers_applied'] = applied
    return success_response("Grace policy updated", result)


def _apply_policy_to_existing(policy):
    now = datetime.utcnow()
    if not (policy.is_active and policy.apply_to_existing and policy.start_at <= now <= policy.end_at):
        return 0
    from backend.models.user import AdminUser
    count = 0
    for driver in AdminUser.query.filter_by(user_type='Pending Driver').all():
        if policy.max_redemptions is not None and policy.redemption_count >= policy.max_redemptions: break
        if apply_grace(driver, existing=True, policy=policy): count += 1
    return count


@subscriptions_bp.route('/api/admin/subscription-grace-policies/<int:policy_id>/apply-existing', methods=['POST'])
@admin_required
def apply_existing_grace(user, policy_id):
    p = db.session.get(DriverGracePolicy, policy_id)
    if not p: return error_response('Grace policy not found', 404)
    count = _apply_policy_to_existing(p)
    db.session.commit(); return success_response("Grace offer applied to pending drivers", {'applied': count})


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

    from backend.models.user import AdminUser
    rows = []
    for s in subs:
        d = s.to_dict()
        driver = db.session.get(AdminUser, s.driver_id) if s.driver_id else None
        d['driver_name'] = driver.name if driver else None
        d['driver_email'] = driver.email if driver else None
        d['driver_phone'] = driver.phone_number if driver else None
        rows.append(d)
    return success_response("Subscriptions", {
        'subscriptions': rows,
        'active_count': active_count,
        'active_revenue': revenue,
    })


def _promote_driver(driver_id):
    """Ensure a driver whose subscription is active can operate."""
    from backend.models.user import AdminUser
    driver = db.session.get(AdminUser, driver_id)
    if driver and driver.user_type == 'Pending Driver':
        driver.user_type = 'Driver'


@subscriptions_bp.route('/api/admin/subscriptions/<int:sub_id>/activate', methods=['POST'])
@admin_required
def admin_activate(user, sub_id):
    """Admin marks a subscription as PAID & ACTIVE (manual activation).

    Optional body: {"duration_days": <int>} to override the plan duration.
    """
    sub = db.session.get(Subscription, sub_id)
    if not sub:
        return error_response("Subscription not found", status_code=404)
    data = request.get_json(silent=True) or request.form or {}
    duration = data.get('duration_days')
    try:
        duration = int(duration) if duration not in (None, '') else None
    except (TypeError, ValueError):
        duration = None
    sub.activate(duration_days=duration)
    _promote_driver(sub.driver_id)
    db.session.commit()
    return success_response("Subscription activated", sub.to_dict())


@subscriptions_bp.route('/api/admin/subscriptions/<int:sub_id>/cancel', methods=['POST'])
@admin_required
def admin_cancel(user, sub_id):
    """Admin cancels/expires a subscription and takes the driver offline if they
    have no other active subscription."""
    from backend.models.user import AdminUser
    sub = db.session.get(Subscription, sub_id)
    if not sub:
        return error_response("Subscription not found", status_code=404)
    data = request.get_json(silent=True) or request.form or {}
    sub.status = data.get('status', 'cancelled')
    if sub.status not in ('cancelled', 'expired'):
        sub.status = 'cancelled'
    driver = db.session.get(AdminUser, sub.driver_id)
    if driver and Subscription.active_for_driver(driver.id) is None:
        driver.ready_for_trip = 'No'
    db.session.commit()
    return success_response("Subscription " + sub.status, sub.to_dict())


@subscriptions_bp.route('/api/admin/subscriptions/grant', methods=['POST'])
@admin_required
def admin_grant(user):
    """Admin manually grants (creates + activates) a subscription for a driver —
    e.g. a comped or offline-paid subscription. Body: {driver_id, plan_id,
    duration_days?}."""
    from backend.models.user import AdminUser
    data = request.get_json(silent=True) or request.form or {}
    try:
        driver_id = int(data.get('driver_id'))
        plan_id = int(data.get('plan_id'))
    except (TypeError, ValueError):
        return error_response("Valid driver_id and plan_id are required")

    driver = db.session.get(AdminUser, driver_id)
    plan = db.session.get(SubscriptionPlan, plan_id)
    if not driver:
        return error_response("Driver not found", status_code=404)
    if not plan:
        return error_response("Plan not found", status_code=404)

    duration = data.get('duration_days')
    try:
        duration = int(duration) if duration not in (None, '') else None
    except (TypeError, ValueError):
        duration = None

    sub = Subscription(
        driver_id=driver_id, plan_id=plan.id, amount=plan.amount,
        currency=plan.currency or 'NGN', status='pending',
        tx_ref=f"admin-grant-{driver_id}-{plan_id}",
    )
    db.session.add(sub)
    db.session.flush()
    sub.activate(duration_days=duration)
    _promote_driver(driver_id)
    db.session.commit()
    return success_response("Subscription granted & activated", sub.to_dict())


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
            customer_name=user.name or 'Truckfully Driver',
            customer_email=user.email or f"driver_{user.id}@truckfully.com",
            customer_phone=user.phone_number or '',
            description=f"Truckfully {plan.name} subscription",
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
