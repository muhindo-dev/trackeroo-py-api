"""
Flutterwave Payment Routes — Truckeroo Nigeria

Endpoints:
  POST /api/flutterwave/pay               — initialize payment for a booking
  GET  /api/flutterwave/verify            — verify payment by tx_ref
  GET  /api/flutterwave/callback          — redirect callback from Flutterwave
  POST /api/webhooks/flutterwave          — Flutterwave webhook (charge.completed)
  GET  /api/flutterwave/banks             — list Nigerian banks
  POST /api/flutterwave/verify-account    — verify bank account
  POST /api/flutterwave/payout            — initiate payout to driver
  GET  /api/flutterwave/transfer-status   — check payout transfer status
  GET  /api/flutterwave/transfer-callback — Flutterwave transfer webhook callback
"""

import json
import os
import uuid
from datetime import datetime

from flask import Blueprint, request
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.scheduled_booking import ScheduledBooking
from backend.models.payment import Payment
from backend.models.transaction import Transaction
from backend.models.user_wallet import UserWallet
from backend.models.payout_request import PayoutRequest
from backend.models.payout_account import PayoutAccount
from backend.models.user import AdminUser
from backend.services.flutterwave_service import FlutterwaveService, FlutterwaveError, get_flutterwave
from backend.utils.auth import jwt_required_with_user, admin_required
from backend.utils.response import success_response, error_response

flutterwave_bp = Blueprint('flutterwave', __name__)

SERVICE_FEE_PCT = int(os.getenv('SERVICE_FEE_PERCENTAGE', 10))


# ═══════════════════════════════════════════════════════════════════════════
# PAYMENT INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/flutterwave/pay', methods=['POST'])
@jwt_required_with_user
def initialize_payment(user):
    """Initialize a Flutterwave payment for a scheduled booking.

    Body: { booking_id, amount? }
    Returns: { payment_link, tx_ref, booking_id }
    """
    data = request.get_json(silent=True) or {}
    booking_id = data.get('booking_id')
    if not booking_id:
        return error_response("booking_id is required")

    booking = ScheduledBooking.query.get(booking_id)
    if not booking:
        return error_response("Booking not found", status_code=404)

    if booking.customer_id != user.id and user.id != 1:
        return error_response("Not authorized", status_code=403)

    # Idempotency — already has a valid payment URL
    if booking.flw_payment_url and booking.payment_status in ('pending', 'processing'):
        return success_response("Existing payment link", {
            'payment_link': booking.flw_payment_url,
            'tx_ref': booking.flw_tx_ref,
            'booking_id': booking.id,
            'gateway': 'flutterwave',
        })

    # Amount: use agreed_price_cad if set, else customer_proposed_price
    # Stored as whole NGN (no kobo conversion needed for NGN)
    amount = float(booking.agreed_price_cad or booking.customer_proposed_price or 0)
    if amount <= 0:
        return error_response("Booking has no valid price set")
    if amount < 100:
        return error_response("Minimum payment amount is ₦100")

    tx_ref = FlutterwaveService.generate_tx_ref('book')

    # Customer info
    customer = booking.customer
    customer_email = customer.email if customer else f"user{booking.customer_id}@truckeroo.com"
    customer_name = customer.name if customer else "Truckeroo Customer"
    customer_phone = customer.phone_number if customer else ""

    flw = get_flutterwave()
    try:
        result = flw.initialize_payment(
            amount=amount,
            tx_ref=tx_ref,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            description=f"Truckeroo booking #{booking.id} — {booking.service_type}",
            meta={
                'booking_id': booking.id,
                'customer_id': booking.customer_id,
                'driver_id': booking.driver_id,
                'service_type': booking.service_type,
            },
        )
    except FlutterwaveError as e:
        return error_response(str(e))

    # Persist to booking
    booking.flw_tx_ref = tx_ref
    booking.flw_payment_url = result['payment_link']
    booking.payment_status = 'pending'
    booking.stripe_url = result['payment_link']  # Backward compat field
    db.session.commit()

    return success_response("Payment initialized", {
        'payment_link': result['payment_link'],
        'tx_ref': tx_ref,
        'booking_id': booking.id,
        'amount': amount,
        'currency': 'NGN',
        'gateway': 'flutterwave',
    })


# ═══════════════════════════════════════════════════════════════════════════
# PAYMENT VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/flutterwave/verify', methods=['GET'])
@jwt_required_with_user
def verify_payment(user):
    """Verify a Flutterwave payment by tx_ref or flw_tx_id.

    Query params: tx_ref OR flw_tx_id
    """
    tx_ref = request.args.get('tx_ref') or request.args.get('reference')
    flw_tx_id = request.args.get('flw_tx_id') or request.args.get('transaction_id')

    if not tx_ref and not flw_tx_id:
        return error_response("tx_ref or flw_tx_id is required")

    # Find the booking
    booking = None
    if tx_ref:
        booking = ScheduledBooking.query.filter_by(flw_tx_ref=tx_ref).first()
    if not booking and flw_tx_id:
        booking = ScheduledBooking.query.filter_by(flw_tx_id=flw_tx_id).first()

    flw = get_flutterwave()
    try:
        if tx_ref:
            verification = flw.verify_by_tx_ref(tx_ref)
        else:
            verification = flw.verify_by_id(flw_tx_id)
    except FlutterwaveError as e:
        return error_response(str(e))

    info = flw.extract_payment_info(verification)

    if booking:
        expected_amount = float(booking.agreed_price_cad or booking.customer_proposed_price or 0)
        is_paid = flw.is_payment_successful(verification, expected_amount, 'NGN')

        if is_paid and booking.payment_status != 'paid':
            _mark_booking_paid(booking, info)
            db.session.commit()

        return success_response("Verification complete", {
            'is_paid': is_paid or (booking.payment_status == 'paid'),
            'booking_id': booking.id,
            'booking_status': booking.status,
            'payment_status': booking.payment_status,
            'amount': info['amount'],
            'currency': info['currency'],
            'payment_type': info['payment_type'],
            'tx_ref': info['tx_ref'],
            'flw_tx_id': info['flw_tx_id'],
        })

    return success_response("Payment info", {
        **info,
        'booking_id': None,
        'is_paid': verification.get('data', {}).get('status') == 'successful',
    })


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK (redirect from Flutterwave after payment)
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/flutterwave/callback', methods=['GET', 'POST'])
def payment_callback():
    """Handle redirect from Flutterwave after customer completes payment.

    Flutterwave sends: ?status=successful&tx_ref=...&transaction_id=...
    We verify and update the booking, then redirect to mobile deeplink or success page.
    """
    status = request.args.get('status', '')
    tx_ref = request.args.get('tx_ref', '')
    transaction_id = request.args.get('transaction_id', '')

    if not tx_ref:
        return error_response("Missing tx_ref in callback", status_code=400)

    booking = ScheduledBooking.query.filter_by(flw_tx_ref=tx_ref).first()

    if status == 'successful' and transaction_id:
        flw = get_flutterwave()
        try:
            verification = flw.verify_by_id(transaction_id)
        except FlutterwaveError:
            try:
                verification = flw.verify_by_tx_ref(tx_ref)
            except FlutterwaveError:
                verification = None

        if verification and booking:
            expected = float(booking.agreed_price_cad or booking.customer_proposed_price or 0)
            if flw.is_payment_successful(verification, expected, 'NGN'):
                info = flw.extract_payment_info(verification)
                if booking.payment_status != 'paid':
                    _mark_booking_paid(booking, info)
                    db.session.commit()

    # Return JSON for mobile app WebView to detect and close
    if booking:
        paid = booking.payment_status in ('paid', 'payment_completed')
        return success_response(
            "Payment completed" if paid else "Payment pending",
            {
                'paid': paid,
                'booking_id': booking.id,
                'status': status,
                'tx_ref': tx_ref,
            }
        )

    return success_response("Callback received", {
        'status': status,
        'tx_ref': tx_ref,
    })


# ═══════════════════════════════════════════════════════════════════════════
# WEBHOOK — Flutterwave sends charge.completed events here
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/webhooks/flutterwave', methods=['POST'])
def flutterwave_webhook():
    """Handle Flutterwave webhook events.

    Flutterwave sends a POST with JSON body and 'verificationhash' header.
    Event types handled:
      • charge.completed — customer completed payment
      • transfer.completed — payout transfer completed/failed
    """
    # Verify signature
    flw = get_flutterwave()
    signature = request.headers.get('verificationhash', '')
    payload_bytes = request.get_data()

    if not flw.verify_webhook_signature(payload_bytes, signature):
        return error_response("Invalid webhook signature", status_code=401)

    try:
        event = json.loads(payload_bytes)
    except (json.JSONDecodeError, ValueError):
        return error_response("Invalid JSON payload", status_code=400)

    event_type = event.get('event', '')
    event_data = event.get('data', {})

    if event_type == 'charge.completed':
        _handle_charge_completed(flw, event_data)
    elif event_type == 'transfer.completed':
        _handle_transfer_completed(event_data)

    # Always return 200 to prevent Flutterwave retries
    return {'status': 'success'}, 200


def _handle_charge_completed(flw: FlutterwaveService, data: dict):
    """Process a charge.completed webhook event."""
    tx_ref = data.get('tx_ref', '')
    flw_tx_id = str(data.get('id', ''))
    paid_status = data.get('status', '')

    if paid_status != 'successful':
        return

    # Find booking by tx_ref
    booking = ScheduledBooking.query.filter(
        (ScheduledBooking.flw_tx_ref == tx_ref) |
        (ScheduledBooking.flw_tx_id == flw_tx_id)
    ).first()

    if not booking:
        # Also try stripe_id field (backward compat)
        booking = ScheduledBooking.query.filter_by(stripe_id=tx_ref).first()

    if not booking:
        return  # Unknown booking — log and ignore

    # Idempotency
    if booking.payment_status == 'paid':
        return

    # Verify with Flutterwave before acting (never trust webhook data alone)
    try:
        verification = flw.verify_by_id(flw_tx_id) if flw_tx_id else flw.verify_by_tx_ref(tx_ref)
    except FlutterwaveError:
        return

    expected = float(booking.agreed_price_cad or booking.customer_proposed_price or 0)
    if not flw.is_payment_successful(verification, expected, 'NGN'):
        return

    info = flw.extract_payment_info(verification)
    _mark_booking_paid(booking, info)
    db.session.commit()


def _handle_transfer_completed(data: dict):
    """Process a transfer.completed webhook event (payout status update)."""
    flw_transfer_id = str(data.get('id', ''))
    reference = data.get('reference', '')
    status = data.get('status', '').upper()

    payout = PayoutRequest.query.filter(
        (PayoutRequest.flw_transfer_id == flw_transfer_id) |
        (PayoutRequest.flw_reference == reference)
    ).first()

    if not payout:
        return

    payout.flw_transfer_status = status
    payout.flw_response_data = data

    if status == 'SUCCESSFUL':
        payout.status = 'approved'
        payout.processed_at = datetime.utcnow()
    elif status == 'FAILED':
        payout.status = 'failed'

    db.session.commit()


# ═══════════════════════════════════════════════════════════════════════════
# BANK UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/flutterwave/banks', methods=['GET'])
@jwt_required_with_user
def list_banks(user):
    """Return list of Nigerian banks with codes."""
    country = request.args.get('country', 'NG')
    flw = get_flutterwave()
    try:
        banks = flw.get_banks(country)
        return success_response("Success", banks)
    except FlutterwaveError as e:
        return error_response(str(e))


@flutterwave_bp.route('/api/flutterwave/verify-account', methods=['POST'])
@jwt_required_with_user
def verify_account(user):
    """Verify a Nigerian bank account number.

    Body: { account_number, bank_code }
    Returns: { account_name, account_number, bank_code }
    """
    data = request.get_json(silent=True) or {}
    account_number = data.get('account_number', '')
    bank_code = data.get('bank_code', '') or data.get('account_bank', '')

    if not account_number or not bank_code:
        return error_response("account_number and bank_code are required")

    flw = get_flutterwave()
    try:
        result = flw.verify_bank_account(account_number, bank_code)
        return success_response("Account verified", result)
    except FlutterwaveError as e:
        return error_response(str(e))


# ═══════════════════════════════════════════════════════════════════════════
# PAYOUTS — Driver transfers
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/flutterwave/payout', methods=['POST'])
@jwt_required_with_user
def initiate_payout(user):
    """Admin or driver initiates a payout withdrawal.

    Body: { payout_request_id }
    Only admin (id=1) can trigger payouts.
    """
    if user.id != 1:
        return error_response("Admin only", status_code=403)

    data = request.get_json(silent=True) or {}
    payout_id = data.get('payout_request_id')
    if not payout_id:
        return error_response("payout_request_id is required")

    payout = PayoutRequest.query.get(payout_id)
    if not payout:
        return error_response("Payout request not found", status_code=404)

    if payout.status != 'pending':
        return error_response(f"Payout is already {payout.status}")

    # Get driver's payout account
    payout_account = PayoutAccount.query.filter_by(user_id=payout.user_id).first()
    if not payout_account or not payout_account.flw_bank_code or not payout_account.flw_account_number:
        return error_response("Driver has no verified bank account. Ask them to add one in Account Settings.")

    # Get driver info
    driver = AdminUser.query.get(payout.user_id)
    driver_name = driver.name if driver else "Driver"

    flw = get_flutterwave()
    reference = FlutterwaveService.generate_tx_ref('pay')

    try:
        result = flw.initiate_transfer(
            account_bank=payout_account.flw_bank_code,
            account_number=payout_account.flw_account_number,
            amount=float(payout.amount),
            beneficiary_name=payout_account.flw_account_name or driver_name,
            narration=f"Truckeroo earnings payout for {driver_name}",
            reference=reference,
        )
    except FlutterwaveError as e:
        return error_response(str(e))

    # Update payout request
    payout.flw_transfer_id = result['flw_transfer_id']
    payout.flw_reference = result['reference']
    payout.flw_transfer_status = result['status']
    payout.flw_response_data = result['flw_response']
    payout.status = 'processing' if result['status'] == 'PENDING' else 'approved'
    db.session.commit()

    return success_response("Payout initiated", {
        'payout_id': payout.id,
        'flw_transfer_id': result['flw_transfer_id'],
        'reference': result['reference'],
        'status': result['status'],
        'amount': result['amount'],
        'currency': result['currency'],
    })


@flutterwave_bp.route('/api/flutterwave/transfer-status', methods=['GET'])
@jwt_required_with_user
def transfer_status(user):
    """Check status of a payout transfer.

    Query: ?flw_transfer_id=...
    """
    flw_transfer_id = request.args.get('flw_transfer_id', '')
    if not flw_transfer_id:
        return error_response("flw_transfer_id is required")

    flw = get_flutterwave()
    try:
        result = flw.get_transfer_status(flw_transfer_id)
        return success_response("Success", result)
    except FlutterwaveError as e:
        return error_response(str(e))


@flutterwave_bp.route('/api/flutterwave/transfer-callback', methods=['POST'])
def transfer_callback():
    """Flutterwave transfer callback (payout status update)."""
    data = request.get_json(silent=True) or {}
    _handle_transfer_completed(data)
    return {'status': 'ok'}, 200


# ═══════════════════════════════════════════════════════════════════════════
# PAYOUT ACCOUNT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@flutterwave_bp.route('/api/flutterwave/payout-account', methods=['POST'])
@jwt_required_with_user
def save_payout_account(user):
    """Save and verify driver's Nigerian bank account for payouts.

    Body: { account_number, bank_code, bank_name }
    Verifies the account with Flutterwave before saving.
    """
    data = request.get_json(silent=True) or {}
    account_number = data.get('account_number', '').strip()
    bank_code = data.get('bank_code', '').strip()
    bank_name = data.get('bank_name', '').strip()

    if not account_number or not bank_code:
        return error_response("account_number and bank_code are required")

    flw = get_flutterwave()
    try:
        verified = flw.verify_bank_account(account_number, bank_code)
    except FlutterwaveError as e:
        return error_response(f"Bank account verification failed: {e}")

    account_name = verified.get('account_name', '')

    # Upsert payout account
    payout_account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not payout_account:
        payout_account = PayoutAccount(user_id=user.id)
        db.session.add(payout_account)

    payout_account.flw_bank_code = bank_code
    payout_account.flw_account_number = account_number
    payout_account.flw_account_name = account_name
    payout_account.flw_bank_name = bank_name
    payout_account.flw_verified = True
    payout_account.flw_verified_at = datetime.utcnow()
    payout_account.default_currency = 'NGN'
    db.session.commit()

    return success_response("Bank account saved and verified", {
        'account_name': account_name,
        'account_number': account_number,
        'bank_code': bank_code,
        'bank_name': bank_name,
        'verified': True,
    })


@flutterwave_bp.route('/api/flutterwave/payout-account', methods=['GET'])
@jwt_required_with_user
def get_payout_account(user):
    """Get the current user's payout account details."""
    account = PayoutAccount.query.filter_by(user_id=user.id).first()
    if not account:
        return success_response("No payout account saved", None)

    return success_response("Success", {
        'account_number': account.flw_account_number,
        'account_name': account.flw_account_name,
        'bank_code': account.flw_bank_code,
        'bank_name': account.flw_bank_name,
        'verified': bool(account.flw_verified),
        'currency': account.default_currency or 'NGN',
    })


# ═══════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _mark_booking_paid(booking: ScheduledBooking, payment_info: dict):
    """Mark a scheduled booking as paid and credit the driver's wallet."""
    amount = payment_info.get('amount', 0)

    # Update booking
    booking.payment_status = 'paid'
    booking.stripe_paid = True   # Backward-compat flag
    booking.flw_tx_id = payment_info.get('flw_tx_id', '')
    booking.flw_payment_type = payment_info.get('payment_type', '')
    booking.payment_completed_at = datetime.utcnow()

    if booking.status in ('pending', 'assigned', 'driver_assigned', 'price_accepted',
                          'payment_pending', 'confirmed'):
        booking.status = 'payment_completed'

    # Record payment
    payment = Payment(
        customer_id=booking.customer_id,
        driver_id=booking.driver_id,
        flw_reference=booking.flw_tx_ref or '',
        flw_tx_id=payment_info.get('flw_tx_id', ''),
        stripe_payment_intent_id=booking.flw_tx_ref or '',  # backward compat
        amount=amount,
        service_fee=round(amount * SERVICE_FEE_PCT / 100, 2),
        driver_amount=round(amount * (100 - SERVICE_FEE_PCT) / 100, 2),
        status='succeeded',
        gateway='flutterwave',
        payment_type='booking_payment',
        currency='NGN',
        description=f"Booking #{booking.id} — {booking.service_type}",
    )
    db.session.add(payment)

    # Credit driver wallet
    if booking.driver_id:
        driver_amount = float(amount) * (100 - SERVICE_FEE_PCT) / 100
        wallet = UserWallet.query.filter_by(user_id=booking.driver_id).first()
        if not wallet:
            wallet = UserWallet(user_id=booking.driver_id, wallet_balance=0, total_earnings=0)
            db.session.add(wallet)
            db.session.flush()

        balance_before = float(wallet.wallet_balance or 0)
        wallet.wallet_balance = balance_before + driver_amount
        wallet.total_earnings = float(wallet.total_earnings or 0) + driver_amount

        tx = Transaction(
            user_id=booking.driver_id,
            user_type='driver',
            type='credit',
            category='ride_earning',
            amount=driver_amount,
            balance_before=balance_before,
            balance_after=wallet.wallet_balance,
            reference=f"earn-{booking.flw_tx_ref or booking.id}-{uuid.uuid4().hex[:8]}",
            description=f"Earning for booking #{booking.id}",
            status='completed',
        )
        db.session.add(tx)
