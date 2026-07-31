import os
from datetime import datetime
from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.user import AdminUser
from backend.utils.auth import jwt_required_with_user
from backend.utils.response import success_response, error_response
from backend.services.negotiation_state_machine import validate_transition

negotiations_bp = Blueprint('negotiations', __name__)


def _is_participant(negotiation: Negotiation, user_id: int) -> bool:
    return user_id in (negotiation.customer_id, negotiation.driver_id)


def _is_paid(negotiation: Negotiation) -> bool:
    status = (negotiation.payment_status or '').lower()
    return negotiation.stripe_paid == 'Yes' or status in ('paid', 'completed')


def _negotiation_fare(negotiation: Negotiation) -> float:
    """Fare in major currency units. Both agreed_price and initial_price are
    stored in CENTS/kobo across this codebase (accept() and set_agreed_price()
    write cents into agreed_price), so divide by 100 for the major-unit amount."""
    if negotiation.agreed_price:
        return float(negotiation.agreed_price) / 100.0
    if negotiation.initial_price:
        return float(negotiation.initial_price) / 100.0
    return 0.0


def _set_driver_busy(driver_id, minutes=120):
    """Mark a driver busy until now+minutes for ETA availability matching."""
    from datetime import timedelta
    if not driver_id:
        return
    driver = db.session.get(AdminUser, driver_id)
    if driver:
        driver.busy_until = datetime.utcnow() + timedelta(minutes=minutes)


def _free_driver(driver_id):
    """Mark a driver free now (trip ended/declined)."""
    if not driver_id:
        return
    driver = db.session.get(AdminUser, driver_id)
    if driver:
        driver.busy_until = None
        driver.available_from = datetime.utcnow()


def _credit_driver_earning(negotiation: Negotiation):
    """Subscription model: on trip completion, credit the driver's wallet with the
    fare as a `ride_earning` transaction (idempotent). This is what powers the
    wallet paid/unpaid breakdown. Skips if the trip was already settled via the
    in-app payment webhook (which credits separately)."""
    import uuid
    from backend.models.user_wallet import UserWallet
    from backend.models.transaction import Transaction

    if not negotiation.driver_id:
        return
    if _is_paid(negotiation):
        return  # already credited by the payment webhook
    # Idempotency: only one ride_earning per negotiation.
    existing = Transaction.query.filter_by(
        negotiation_id=negotiation.id, category='ride_earning'
    ).first()
    if existing:
        return

    fare = _negotiation_fare(negotiation)
    if fare <= 0:
        return

    # Lock wallet to prevent race conditions during concurrent credits
    wallet = UserWallet.query.filter_by(user_id=negotiation.driver_id).with_for_update().first()
    if not wallet:
        wallet = UserWallet(user_id=negotiation.driver_id, wallet_balance=0, total_earnings=0)
        db.session.add(wallet)
        db.session.flush()

    balance_before = float(wallet.wallet_balance or 0)
    wallet.wallet_balance = balance_before + fare
    wallet.total_earnings = float(wallet.total_earnings or 0) + fare

    db.session.add(Transaction(
        user_id=negotiation.driver_id,
        user_type='driver',
        type='credit',
        category='ride_earning',
        amount=fare,
        balance_before=balance_before,
        balance_after=wallet.wallet_balance,
        reference=f'ride-{negotiation.id}-{uuid.uuid4().hex[:8]}',
        description=f'Trip earning for ride #{negotiation.id}',
        status='completed',
        negotiation_id=negotiation.id,
    ))
    negotiation.payment_status = 'paid'


# ---------------------------------------------------------------------------
# Legacy endpoints (ApiChatController)
# ---------------------------------------------------------------------------

@negotiations_bp.route('/api/negotiations', methods=['GET'])
@jwt_required_with_user
def index(user):
    """List user's negotiations with optional filters + stats."""
    status = request.args.get('status')
    sort_by = request.args.get('sort_by', 'created_at')
    sort_order = request.args.get('sort_order', 'desc')
    per_page = int(request.args.get('per_page', 50))

    q = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    )

    if status == 'active':
        q = q.filter(Negotiation.status.in_(['Active', 'Pending', 'Accepted', 'Started']))
    elif status == 'completed':
        q = q.filter(Negotiation.status == 'Completed')
    elif status == 'canceled':
        q = q.filter(Negotiation.status == 'Cancelled')

    col = getattr(Negotiation, sort_by, Negotiation.created_at)
    q = q.order_by(col.desc() if sort_order == 'desc' else col.asc())
    negotiations = q.limit(per_page).all()

    # Stats
    all_q = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    )
    total = all_q.count()
    active = all_q.filter(Negotiation.status.in_(['Active', 'Pending', 'Accepted', 'Started'])).count()
    completed = all_q.filter(Negotiation.status == 'Completed').count()
    canceled = all_q.filter(Negotiation.status == 'Cancelled').count()

    return success_response("Success", {
        'negotiations': [n.to_dict() for n in negotiations],
        'stats': {
            'total': total,
            'active': active,
            'completed': completed,
            'canceled': canceled,
        },
    })


@negotiations_bp.route('/api/negotiations', methods=['POST'])
@jwt_required_with_user
def create_legacy(user):
    """Legacy create – ApiChatController style (dollars → cents)."""
    data = request.get_json(silent=True) or request.form
    driver_id = data.get('driver_id')
    driver = AdminUser.query.get(driver_id) if driver_id else None

    price_raw = data.get('price', 0)
    try:
        price_cents = int(float(price_raw) * 100)
    except (TypeError, ValueError):
        price_cents = 0

    negotiation = Negotiation(
        customer_id=user.id,
        customer_name=user.name,
        driver_id=driver_id,
        driver_name=driver.name if driver else None,
        pickup_lat=data.get('pickup_lat'),
        pickup_lng=data.get('pickup_lng'),
        pickup_address=data.get('pickup_address'),
        dropoff_lat=data.get('dropoff_lat'),
        dropoff_lng=data.get('dropoff_lng'),
        dropoff_address=data.get('dropoff_address'),
        initial_price=price_cents,
        status='Active',
        is_active='Yes',
        customer_accepted='Accepted',
        customer_driver='Pending',
    )
    db.session.add(negotiation)
    db.session.flush()

    # Initial record
    record = NegotiationRecord(
        negotiation_id=negotiation.id,
        customer_id=user.id,
        driver_id=driver_id,
        last_negotiator_id=user.id,
        first_negotiator_id=user.id,
        price=price_cents,
        price_accepted='No',
        message_type=data.get('message_type', 'Negotiation'),
        message_body=data.get('message_body'),
    )
    db.session.add(record)
    db.session.commit()

    return success_response("Negotiation created", negotiation.to_dict(), status_code=201)


# ---------------------------------------------------------------------------
# Enhanced endpoints (ApiNegotiationController)
# ---------------------------------------------------------------------------

@negotiations_bp.route('/api/negotiations-create', methods=['POST'])
@jwt_required_with_user
def create(user):
    """Enhanced create – validates driver online, price ≥ 50 cents."""
    data = request.get_json(silent=True) or request.form
    driver_id = data.get('driver_id')

    if not driver_id:
        return error_response("driver_id is required")

    driver = AdminUser.query.get(driver_id)
    if not driver:
        return error_response("Driver not found", status_code=404)

    initial_price = int(data.get('initial_price', 0))
    if initial_price < 100 or initial_price > 9999900:
        return error_response("Initial price must be between ₦100 and ₦9,999,900")

    negotiation = Negotiation(
        customer_id=user.id,
        customer_name=user.name,
        driver_id=driver.id,
        driver_name=driver.name,
        pickup_lat=data.get('pickup_lat'),
        pickup_lng=data.get('pickup_lng'),
        pickup_address=data.get('pickup_address'),
        dropoff_lat=data.get('dropoff_lat'),
        dropoff_lng=data.get('dropoff_lng'),
        dropoff_address=data.get('dropoff_address'),
        initial_price=initial_price,
        status='Active',
        is_active='Yes',
        customer_accepted='Accepted',
        customer_driver='Pending',
    )
    db.session.add(negotiation)
    db.session.flush()

    record = NegotiationRecord(
        negotiation_id=negotiation.id,
        customer_id=user.id,
        driver_id=driver.id,
        last_negotiator_id=user.id,
        first_negotiator_id=user.id,
        price=initial_price,
        price_accepted='No',
        message_type='Negotiation',
        message_body=data.get('message_body'),
    )
    db.session.add(record)
    db.session.commit()

    return success_response("Negotiation created", negotiation.to_dict(), status_code=201)


@negotiations_bp.route('/api/negotiation-updates', methods=['POST'])
@jwt_required_with_user
def poll_updates(user):
    """Poll for negotiation updates."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id') or data.get('id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    return success_response("Success", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-records', methods=['GET'])
@jwt_required_with_user
def records_get(user):
    """Get negotiation records."""
    negotiation_id = request.args.get('negotiation_id')

    if negotiation_id:
        negotiation = Negotiation.query.get(negotiation_id)
        if not negotiation:
            return error_response("Negotiation not found", status_code=404)
        if not _is_participant(negotiation, user.id):
            return error_response("Forbidden", status_code=403)

        records = NegotiationRecord.query.filter_by(
            negotiation_id=negotiation_id
        ).order_by(NegotiationRecord.created_at.asc()).all()
    else:
        records = NegotiationRecord.query.filter(
            (NegotiationRecord.customer_id == user.id) |
            (NegotiationRecord.driver_id == user.id)
        ).order_by(NegotiationRecord.created_at.desc()).all()

    return success_response("Success", [r.to_dict() for r in records])


@negotiations_bp.route('/api/negotiations-records', methods=['POST'])
@jwt_required_with_user
def records_post(user):
    """Add a negotiation record (counter-offer / message / voice note)."""
    data = request.get_json(silent=True) or request.form

    negotiation_id = data.get('negotiation_id')
    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)
    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    price_raw = data.get('price', 0)
    try:
        price_cents = int(float(price_raw) * 100)
    except (TypeError, ValueError):
        price_cents = 0

    message_body = data.get('message_body', '')
    if not message_body or not message_body.strip():
        return error_response("Message text cannot be empty")
    if len(message_body) > 1000:
        return error_response("Message text cannot exceed 1000 characters")

    # Handle audio file upload
    audio_url = None
    if 'audio' in request.files:
        audio_file = request.files['audio']
        if audio_file and audio_file.filename:
            ext = audio_file.filename.rsplit('.', 1)[-1].lower() if '.' in audio_file.filename else 'm4a'
            if ext not in ('m4a', 'aac', 'mp3', 'wav', 'ogg', 'opus', 'webm'):
                return error_response("Unsupported audio format")
            filename = secure_filename(
                f"voice_{negotiation.id}_{user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{ext}"
            )
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'audio')
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)
            audio_file.save(filepath)
            audio_url = f"audio/{filename}"

    record = NegotiationRecord(
        negotiation_id=negotiation.id,
        customer_id=negotiation.customer_id,
        driver_id=negotiation.driver_id,
        last_negotiator_id=user.id,
        first_negotiator_id=negotiation.customer_id or user.id,
        price=price_cents,
        price_accepted=data.get('price_accepted', 'No'),
        message_type=data.get('message_type', 'Negotiation'),
        message_body=data.get('message_body'),
        audio_url=audio_url,
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
    )
    db.session.add(record)
    db.session.commit()

    return success_response("Record added", record.to_dict(), status_code=201)


@negotiations_bp.route('/api/negotiations-accept', methods=['POST'])
@jwt_required_with_user
def accept(user):
    """Accept / start negotiation based on message_type.

    Flutter sends:
      message_type='Accept'   → both parties accepted, status → 'Accepted'
      message_type='Started'  → driver starts the trip, status → 'Started'
    """
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    message_type = data.get('message_type', '')

    # NOTE: Do NOT blindly overwrite customer_accepted / customer_driver
    # from the request payload.  The role-based logic below is the sole
    # authority for these flags — the Flutter client sends legacy values
    # ("Yes") that would conflict with the canonical "Accepted" value.

    # ── Determine status based on message_type ───────────────────────────
    if message_type == 'Started':
        if user.id != negotiation.driver_id:
            return error_response("Only the assigned driver can start this trip", status_code=403)

        # Driver can start even before payment — payment can be completed during trip
        # Validate: can only start if Accepted
        is_valid, err_msg = validate_transition(negotiation.status, 'started')
        if not is_valid:
            return error_response(err_msg, status_code=409)
            
        negotiation.status = 'Started'
        negotiation.is_active = 'Yes'
        # ETA availability: driver is busy for the trip duration window.
        _set_driver_busy(negotiation.driver_id)

    elif message_type == 'Accept':
        # Keep compatibility with existing Flutter calls while enforcing role intent.
        if user.id == negotiation.driver_id:
            negotiation.customer_driver = 'Accepted'
            # When driver accepts, the customer implicitly agreed (they proposed the price).
            negotiation.customer_accepted = 'Accepted'
        elif user.id == negotiation.customer_id:
            negotiation.customer_accepted = 'Accepted'
            # When customer accepts, it's because they are accepting the driver's counter-offer.
            negotiation.customer_driver = 'Accepted'
        else:
            return error_response("Forbidden", status_code=403)

        if (negotiation.customer_accepted == 'Accepted'
                and negotiation.customer_driver == 'Accepted'):
            if negotiation.status != 'Accepted':
                is_valid, err_msg = validate_transition(negotiation.status, 'accepted')
                if not is_valid:
                    return error_response(err_msg, status_code=409)
                negotiation.status = 'Accepted'
            negotiation.is_active = 'Yes'

        # Set agreed_price from the last negotiation record's price (cents)
        if not negotiation.agreed_price:
            last_record = (
                NegotiationRecord.query
                .filter_by(negotiation_id=negotiation.id)
                .order_by(NegotiationRecord.id.desc())
                .first()
            )
            if last_record and last_record.price:
                negotiation.agreed_price = last_record.price  # cents

    else:
        # Fallback: if both accepted, auto-set Accepted
        if (negotiation.customer_accepted == 'Accepted'
                and negotiation.customer_driver == 'Accepted'
                and negotiation.status == 'Active'):
            is_valid, err_msg = validate_transition(negotiation.status, 'accepted')
            if not is_valid:
                return error_response(err_msg, status_code=409)
            negotiation.status = 'Accepted'

    # V2 instant-ride hook: driver acceptance settles the dispatch.
    if negotiation.status in ('Accepted', 'Started') and negotiation.ride_source == 'instant':
        from backend.models.ride_dispatch import RideDispatch
        dispatch = RideDispatch.query.filter_by(negotiation_id=negotiation.id).first()
        if dispatch and dispatch.status in ('offered', 'searching'):
            dispatch.status = 'matched'

    db.session.commit()
    return success_response("Negotiation updated", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-cancel', methods=['POST'])
@jwt_required_with_user
def cancel(user):
    """Cancel a negotiation (not if Started/Completed)."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    if negotiation.status in ('Started', 'Completed'):
        return error_response("Cannot cancel a negotiation that is already " + negotiation.status)

    # V2 instant-ride hook: when the OFFERED DRIVER declines an instant ride,
    # don't kill the ride — pass the offer to the next fairest candidate.
    if negotiation.ride_source == 'instant' and user.id == negotiation.driver_id:
        from backend.models.ride_dispatch import RideDispatch
        from backend.routes.rides import _advance
        dispatch = RideDispatch.query.filter_by(negotiation_id=negotiation.id).first()
        if dispatch and dispatch.status in ('offered', 'searching'):
            advanced = _advance(dispatch, negotiation)
            db.session.commit()
            return success_response(
                "Offer passed to the next driver" if advanced else "No more drivers available",
                negotiation.to_dict())

    if negotiation.status != 'Cancelled':
        is_valid, err_msg = validate_transition(negotiation.status, 'cancelled')
        if not is_valid:
            return error_response(err_msg, status_code=409)
        negotiation.status = 'Cancelled'
    negotiation.is_active = 'No'
    _free_driver(negotiation.driver_id)
    db.session.commit()

    return success_response("Negotiation cancelled", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-complete', methods=['POST'])
@jwt_required_with_user
def complete(user):
    """Complete or cancel a negotiation/trip.

    Flutter sends message_type='Complete' or message_type='Cancel'.
    """
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    message_type = data.get('message_type', 'Complete')

    if message_type == 'Cancel':
        if negotiation.status == 'Completed':
            return error_response("Cannot cancel an already completed trip")
        if negotiation.status != 'Cancelled':
            is_valid, err_msg = validate_transition(negotiation.status, 'cancelled')
            if not is_valid:
                return error_response(err_msg, status_code=409)
            negotiation.status = 'Cancelled'
        negotiation.is_active = 'No'
        _free_driver(negotiation.driver_id)
        msg = "Trip cancelled"
    else:
        if user.id != negotiation.driver_id:
            return error_response("Only the assigned driver can complete this trip", status_code=403)

        # Subscription is the payment mode: trips no longer require an in-app
        # customer payment to complete. The driver's wallet is credited with the
        # fare as earnings on completion (idempotent), and subscription is the
        # platform's revenue.
        if negotiation.status != 'Completed':
            is_valid, err_msg = validate_transition(negotiation.status, 'completed')
            if not is_valid:
                return error_response(err_msg, status_code=409)
            negotiation.status = 'Completed'
        negotiation.is_active = 'No'
        _credit_driver_earning(negotiation)
        _free_driver(negotiation.driver_id)
        msg = "Trip completed"

    db.session.commit()
    return success_response(msg, negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-list', methods=['GET'])
@jwt_required_with_user
def list_all(user):
    """List all user's negotiations."""
    negotiations = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    ).order_by(Negotiation.created_at.desc()).all()

    return success_response("Success", [n.to_dict() for n in negotiations])


@negotiations_bp.route('/api/negotiations/<int:neg_id>/with-payment', methods=['GET'])
@jwt_required_with_user
def with_payment(user, neg_id):
    """Get negotiation with payment details."""
    negotiation = Negotiation.query.get(neg_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    from backend.models.payment import Payment
    payment = Payment.query.filter_by(negotiation_id=neg_id).first()

    return success_response("Success", {
        'negotiation': negotiation.to_dict(),
        'requires_payment': negotiation.status == 'Accepted',
        'payment_completed': negotiation.stripe_paid == 'Yes' if hasattr(negotiation, 'stripe_paid') else False,
        'payment': payment.to_dict() if payment else None,
    })


@negotiations_bp.route('/api/negotiations/<int:neg_id>/set-agreed-price', methods=['POST'])
@jwt_required_with_user
def set_agreed_price(user, neg_id):
    """Set agreed price (1000-1000000 cents)."""
    data = request.get_json(silent=True) or request.form
    agreed_price = int(data.get('agreed_price', 0))

    if agreed_price < 1000 or agreed_price > 1000000:
        return error_response("Agreed price must be between ₦1,000 and ₦10,000,000")

    negotiation = Negotiation.query.get(neg_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    negotiation.agreed_price = agreed_price
    db.session.commit()

    return success_response("Agreed price set", negotiation.to_dict())


@negotiations_bp.route('/api/negotiations-refresh-payment', methods=['POST'])
@jwt_required_with_user
def refresh_payment(user):
    """Generate/refresh Stripe payment link for negotiation."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    # Already paid — no need to regenerate
    if negotiation.stripe_paid == 'Yes':
        return success_response("Already paid", {
            'negotiation_id': negotiation.id,
            'stripe_url': negotiation.stripe_url,
            'stripe_id': negotiation.stripe_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': 'paid',
            'stripe_paid': 'Yes',
            'is_paid': True,
        })

    force = data.get('force_regenerate', False)

    # Re-use existing session if not forcing regenerate and url exists
    if not force and negotiation.stripe_url and negotiation.stripe_session_id:
        return success_response("Payment link ready", {
            'negotiation_id': negotiation.id,
            'stripe_url': negotiation.stripe_url,
            'stripe_id': negotiation.stripe_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': negotiation.payment_status,
            'stripe_paid': negotiation.stripe_paid,
            'is_paid': False,
        })

    # Determine price in cents
    price_cents = 0
    if negotiation.agreed_price:
        price_cents = int(negotiation.agreed_price)
    elif negotiation.initial_price:
        price_cents = int(negotiation.initial_price)

    if price_cents < 50:
        return error_response("Price too low. Minimum is ₦50.")

    # Get customer email for Stripe
    customer_email = None
    try:
        customer = AdminUser.query.get(negotiation.customer_id)
        if customer:
            customer_email = customer.email
    except Exception:
        pass

    try:
        from backend.services.stripe_service import create_checkout_session

        result = create_checkout_session(
            amount_cents=price_cents,
            metadata={
                'negotiation_id': str(negotiation.id),
                'type': 'car_hire',
            },
            customer_email=customer_email,
        )

        negotiation.stripe_id = result['stripe_id']
        negotiation.stripe_session_id = result['session_id']
        negotiation.stripe_url = result['url']
        negotiation.payment_status = 'pending'
        db.session.commit()

        return success_response("Payment link generated", {
            'negotiation_id': negotiation.id,
            'stripe_url': negotiation.stripe_url,
            'stripe_id': negotiation.stripe_id,
            'agreed_price': negotiation.agreed_price,
            'payment_status': 'pending',
            'stripe_paid': negotiation.stripe_paid,
            'is_paid': False,
        })

    except Exception as e:
        current_app.logger.error(f"Failed to create payment session: {str(e)}")
        return error_response("Failed to create payment session")


@negotiations_bp.route('/api/negotiations-check-payment', methods=['POST'])
@jwt_required_with_user
def check_payment(user):
    """Check payment status for a negotiation — syncs with Stripe if session exists."""
    data = request.get_json(silent=True) or request.form
    negotiation_id = data.get('negotiation_id')

    negotiation = Negotiation.query.get(negotiation_id)
    if not negotiation:
        return error_response("Negotiation not found", status_code=404)

    if not _is_participant(negotiation, user.id):
        return error_response("Forbidden", status_code=403)

    # Already marked paid locally — return immediately
    if negotiation.stripe_paid == 'Yes':
        return success_response("Success", {
            'payment_status': 'paid',
            'stripe_paid': 'Yes',
            'is_paid': True,
            'stripe_url': negotiation.stripe_url,
        })

    # Sync with Stripe if we have a session
    if negotiation.stripe_session_id:
        try:
            from backend.services.stripe_service import check_session_status

            status_data = check_session_status(negotiation.stripe_session_id)

            if status_data.get('is_paid'):
                negotiation.stripe_paid = 'Yes'
                negotiation.payment_status = 'paid'
                from datetime import datetime
                negotiation.payment_completed_at = datetime.utcnow()
                db.session.commit()

                return success_response("Success", {
                    'payment_status': 'paid',
                    'stripe_paid': 'Yes',
                    'is_paid': True,
                    'stripe_url': negotiation.stripe_url,
                })
        except Exception as e:
            # Stripe check failed — fall through to return current DB state
            pass

    # Auto-generate a Stripe session if none exists so the client gets a
    # payment URL.  Only do this for the customer on an accepted/started trip
    # that has a valid price.
    if (not negotiation.stripe_session_id
            and user.id == negotiation.customer_id
            and negotiation.status in ('Accepted', 'Started', 'Active')):
        price_cents = 0
        if negotiation.agreed_price:
            price_cents = int(negotiation.agreed_price)
        elif negotiation.initial_price:
            price_cents = int(negotiation.initial_price)

        if price_cents >= 50:
            customer_email = None
            try:
                customer = AdminUser.query.get(negotiation.customer_id)
                if customer:
                    customer_email = customer.email
            except Exception:
                pass

            try:
                from backend.services.stripe_service import create_checkout_session

                result = create_checkout_session(
                    amount_cents=price_cents,
                    metadata={
                        'negotiation_id': str(negotiation.id),
                        'type': 'car_hire',
                    },
                    customer_email=customer_email,
                )

                negotiation.stripe_id = result['stripe_id']
                negotiation.stripe_session_id = result['session_id']
                negotiation.stripe_url = result['url']
                negotiation.payment_status = 'pending'
                db.session.commit()

                return success_response("Success", {
                    'payment_status': 'pending',
                    'stripe_paid': negotiation.stripe_paid or 'No',
                    'is_paid': False,
                    'stripe_url': negotiation.stripe_url,
                })
            except Exception as e:
                # Session creation failed — fall through to return current state
                pass

    return success_response("Success", {
        'payment_status': negotiation.payment_status or 'unpaid',
        'stripe_paid': negotiation.stripe_paid or 'No',
        'is_paid': False,
        'stripe_url': negotiation.stripe_url,
    })


@negotiations_bp.route('/api/negotiations-test', methods=['GET'])
@jwt_required_with_user
def test(user):
    """Debug/test endpoint."""
    total = Negotiation.query.filter(
        (Negotiation.customer_id == user.id) | (Negotiation.driver_id == user.id)
    ).count()

    return success_response("Success", {
        'message': 'Negotiations API working',
        'user_id': user.id,
        'total_negotiations': total,
    })
