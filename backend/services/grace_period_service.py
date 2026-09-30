from datetime import datetime, timedelta
from uuid import uuid4
from backend.models import db
from backend.models.grace_policy import DriverGracePolicy
from backend.models.subscription import Subscription


def active_policy(now=None, existing=False):
    now = now or datetime.utcnow()
    flag = DriverGracePolicy.apply_to_existing if existing else DriverGracePolicy.apply_to_new_drivers
    return DriverGracePolicy.query.filter(
        DriverGracePolicy.is_active == 1, flag == 1,
        DriverGracePolicy.start_at <= now, DriverGracePolicy.end_at >= now,
        (DriverGracePolicy.max_redemptions.is_(None) |
         (DriverGracePolicy.redemption_count < DriverGracePolicy.max_redemptions)),
    ).order_by(DriverGracePolicy.created_at.desc(), DriverGracePolicy.id.desc()).first()


def offer_dict(policy):
    if not policy:
        return None
    return {'policy_id': policy.id, 'name': policy.name, 'plan': policy.plan.to_dict() if policy.plan else None,
            'duration_days': policy.duration_days, 'ends_at': policy.end_at.isoformat()}


def apply_grace(driver, existing=False, policy=None):
    policy = policy or active_policy(existing=existing)
    if policy:
        # Serialize redemptions against this policy so its cap cannot be
        # exceeded by two signups arriving at the same time.
        policy = DriverGracePolicy.query.filter_by(id=policy.id).with_for_update().first()
    # A driver can redeem one policy only once, including after expiry.
    if not policy or Subscription.query.filter_by(driver_id=driver.id, grace_policy_id=policy.id).first():
        return None
    if policy.max_redemptions is not None and policy.redemption_count >= policy.max_redemptions:
        return None
    now = datetime.utcnow()
    sub = Subscription(driver_id=driver.id, plan_id=policy.plan_id, amount=0,
                       currency=policy.plan.currency if policy.plan else 'NGN', status='active',
                       start_at=now, end_at=now + timedelta(days=max(int(policy.duration_days), 1)),
                       tx_ref=f'grace-{policy.id}-{driver.id}-{uuid4().hex[:12]}',
                       grace_policy_id=policy.id, is_grace=1)
    policy.redemption_count = (policy.redemption_count or 0) + 1
    db.session.add(sub)
    return sub
