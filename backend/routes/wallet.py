import os
from flask import Blueprint, request
from backend.models import db
from backend.models.user_wallet import UserWallet
from backend.models.transaction import Transaction
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response

wallet_bp = Blueprint('wallet', __name__)


@wallet_bp.route('/api/wallet', methods=['GET'])
@jwt_required_with_user
def get_wallet(user):
    """Get or create user's wallet."""
    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = UserWallet(user_id=user.id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.commit()

    return success_response("Success", wallet.to_dict())


@wallet_bp.route('/api/wallet/transactions', methods=['GET'])
@jwt_required_with_user
def transactions(user):
    """Get transaction history with optional filters."""
    category = request.args.get('category')
    tx_type = request.args.get('type')
    negotiation_id = request.args.get('negotiation_id')

    q = Transaction.query.filter_by(user_id=user.id)

    if category:
        q = q.filter_by(category=category)
    if tx_type:
        q = q.filter_by(type=tx_type)
    if negotiation_id:
        q = q.filter_by(negotiation_id=negotiation_id)

    txns = q.order_by(Transaction.created_at.desc()).all()
    return success_response("Success", [t.to_dict() for t in txns])


@wallet_bp.route('/api/wallet/summary', methods=['GET'])
@jwt_required_with_user
def summary(user):
    """Wallet + statistics + recent 5 transactions."""
    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = UserWallet(user_id=user.id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.commit()

    from sqlalchemy import func

    total_credits = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
        user_id=user.id, type='credit'
    ).scalar()
    total_debits = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
        user_id=user.id, type='debit'
    ).scalar()
    total_transactions = Transaction.query.filter_by(user_id=user.id).count()
    ride_earnings = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter_by(
        user_id=user.id, type='credit', category='ride_earning'
    ).scalar()

    recent = Transaction.query.filter_by(user_id=user.id).order_by(
        Transaction.created_at.desc()
    ).limit(5).all()

    return success_response("Success", {
        'wallet': {
            'balance': wallet.wallet_balance,
            'total_earnings': wallet.total_earnings,
        },
        'statistics': {
            'total_credits': int(total_credits),
            'total_debits': int(total_debits),
            'total_transactions': total_transactions,
            'ride_earnings': int(ride_earnings),
        },
        'recent_transactions': [t.to_dict() for t in recent],
    })


@wallet_bp.route('/api/wallet/breakdown', methods=['GET'])
@jwt_required_with_user
def breakdown(user):
    """Subscription earnings breakdown: paid (settled >24h) vs unpaid (<24h),
    matching the driver wallet UI. Earnings older than 24h are withdrawable;
    within 24h they are still pending and can only be taken early at a fee.
    """
    from sqlalchemy import func
    from datetime import datetime, timedelta

    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = UserWallet(user_id=user.id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.commit()

    cutoff = datetime.utcnow() - timedelta(hours=24)

    earning_filter = (
        Transaction.user_id == user.id,
        Transaction.type == 'credit',
        Transaction.category == 'ride_earning',
    )
    unpaid = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        *earning_filter, Transaction.created_at > cutoff
    ).scalar()
    settled = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        *earning_filter, Transaction.created_at <= cutoff
    ).scalar()
    withdrawn = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == user.id,
        Transaction.type == 'debit',
        Transaction.category == 'withdrawal',
    ).scalar()

    paid_available = max(float(settled) - float(withdrawn), 0)

    return success_response("Wallet breakdown", {
        'paid_balance': round(paid_available, 2),       # withdrawable now
        'unpaid_balance': round(float(unpaid), 2),       # pending < 24h
        'total_earnings': float(wallet.total_earnings or 0),
        'wallet_balance': float(wallet.wallet_balance or 0),
        'reclaim_fee_rate': float(wallet.reclaim_fee_rate if wallet.reclaim_fee_rate is not None else 0.10),
        'currency': 'NGN',
    })


@wallet_bp.route('/api/wallet/reclaim', methods=['POST'])
@jwt_required_with_user
def reclaim(user):
    """Reclaim (early withdraw) unpaid earnings at a fee. The net amount becomes
    available; the fee is recorded as a service_fee debit."""
    import uuid
    from datetime import datetime

    from sqlalchemy import func
    from datetime import datetime, timedelta
    from backend.models.payout_request import PayoutRequest
    from backend.models.payout_account import PayoutAccount

    wallet = UserWallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        # Auto-create (consistent with /wallet/breakdown) so we fall through to a
        # clean "no payout account / no unpaid earnings" message instead of 404.
        wallet = UserWallet(user_id=user.id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.commit()

    # A reclaim is an EARLY PAYOUT of unpaid (<24h) earnings at a fee, routed
    # through the normal payout-request flow (real money-out via admin/Flutterwave).
    account = PayoutAccount.query.filter_by(user_id=user.id, status='active').first()
    if not account:
        return error_response(
            "No active payout account. Set up your payout account first.",
            {'requires_payout_account': True})

    cutoff = datetime.utcnow() - timedelta(hours=24)
    unpaid = float(db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == user.id,
        Transaction.type == 'credit',
        Transaction.category == 'ride_earning',
        Transaction.created_at > cutoff,
    ).scalar())

    # Already-reclaimed within the same window (prevents double-reclaim).
    already = float(db.session.query(func.coalesce(func.sum(PayoutRequest.amount), 0)).filter(
        PayoutRequest.user_id == user.id,
        PayoutRequest.created_at > cutoff,
        PayoutRequest.status.in_(('pending', 'processing', 'approved', 'completed')),
        PayoutRequest.description.like('Early reclaim%'),
    ).scalar())

    available = max(round(unpaid - already, 2), 0)
    if available <= 0:
        return error_response("No unpaid earnings available to reclaim right now.")

    data = request.get_json(silent=True) or request.form or {}
    try:
        requested = float(data.get('amount') or 0)
    except (ValueError, TypeError):
        requested = 0
    if requested <= 0:
        requested = available
    amount = round(min(requested, available), 2)  # server-side cap

    fee_rate = float(wallet.reclaim_fee_rate if wallet.reclaim_fee_rate is not None else 0.10)
    fee = round(amount * fee_rate, 2)
    net = round(amount - fee, 2)

    payout = PayoutRequest(
        user_id=user.id,
        payout_account_id=account.id,
        amount=amount,
        fee_amount=fee,
        net_amount=net,
        currency=os.getenv('FLW_CURRENCY', 'NGN'),
        status='pending',
        payout_method='reclaim',
        description=f'Early reclaim ({fee_rate * 100:.0f}% fee)',
        requested_at=datetime.utcnow(),
    )
    db.session.add(payout)
    # Record the fee as a service_fee debit for the ledger.
    db.session.add(Transaction(
        user_id=user.id, user_type='driver', type='debit', category='service_fee',
        amount=fee, balance_before=float(wallet.wallet_balance or 0),
        balance_after=float(wallet.wallet_balance or 0),
        reference=f"reclaimfee_{uuid.uuid4().hex[:16]}",
        description=f"Early withdrawal fee ({fee_rate * 100:.0f}%)",
        status='completed',
    ))
    wallet.updated_at = datetime.utcnow()
    db.session.commit()

    return success_response("Reclaim requested — pending payout", {
        'amount': amount,
        'fee': fee,
        'net': net,
        'fee_rate': fee_rate,
        'available_before': available,
        'payout_request_id': payout.id,
    })


@wallet_bp.route('/api/wallet/earnings', methods=['GET'])
@jwt_required_with_user
def earnings(user):
    """Earnings stats by period."""
    from sqlalchemy import func
    from datetime import datetime, timedelta

    period = request.args.get('period', 'all')
    now = datetime.utcnow()

    q = Transaction.query.filter_by(user_id=user.id, type='credit', category='ride_earning')

    if period == 'today':
        q = q.filter(func.date(Transaction.created_at) == now.date())
    elif period == 'week':
        q = q.filter(Transaction.created_at >= now - timedelta(days=7))
    elif period == 'month':
        q = q.filter(Transaction.created_at >= now - timedelta(days=30))
    elif period == 'year':
        q = q.filter(Transaction.created_at >= now - timedelta(days=365))

    total_earnings = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.user_id == user.id,
        Transaction.type == 'credit',
        Transaction.category == 'ride_earning',
    )

    # Apply same date filter
    if period == 'today':
        total_earnings = total_earnings.filter(func.date(Transaction.created_at) == now.date())
    elif period == 'week':
        total_earnings = total_earnings.filter(Transaction.created_at >= now - timedelta(days=7))
    elif period == 'month':
        total_earnings = total_earnings.filter(Transaction.created_at >= now - timedelta(days=30))
    elif period == 'year':
        total_earnings = total_earnings.filter(Transaction.created_at >= now - timedelta(days=365))

    total = total_earnings.scalar()
    trip_count = q.count()
    avg = int(total / trip_count) if trip_count > 0 else 0

    return success_response("Success", {
        'period': period,
        'total_earnings': int(total),
        'trip_count': trip_count,
        'average_per_trip': avg,
    })
