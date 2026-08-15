"""
Public seller-confirmation page.

Reached via the link the buyer shares with the seller (SMS/WhatsApp) —
no Tawatur account, app install, or login required, matching the existing
"the seller does not need a platform account" design of the direct-purchase
flow.

Acceptance is gated behind an OTP sent to the mobile number the seller
types on the page — this proves whoever is clicking "accept" actually owns
the phone number the buyer named as the seller, not just anyone who
received the forwarded link. There is no SMS integration yet, so the OTP is
printed directly on the page (clearly marked as a temporary dev/testing
behavior), the same way the rest of the platform exposes OTPs before an SMS
provider is wired up.

Route: /confirm/<uuid:token>/  (mounted at project root, not under /api/v1/,
since it's meant to be opened directly in a phone browser).
"""

from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Transaction
from .services import TransactionService


def terms_view(request):
    """Public terms & conditions page — linked from the app's purchase form
    and from the public seller-confirmation page, so there's one source of
    truth for the T&C text."""
    return render(request, 'transactions/terms.html', {
        'updated_at': timezone.now().strftime('%Y/%m/%d'),
    })


def _masked_imei(product) -> str:
    imei = product.imei_1 or product.serial_number
    if not imei:
        return ''
    if len(imei) <= 7:
        return imei
    return f'{imei[:3]} ••••• {imei[-4:]}'


@require_http_methods(['GET', 'POST'])
def seller_confirm_view(request, token):
    from apps.accounts.services import OTPService
    from apps.accounts.models import OTPVerification
    from core.hashing import hash_phone

    txn = get_object_or_404(
        Transaction.objects.select_related('product', 'initiator'),
        link_token=token,
    )

    error = None
    otp_debug = None          # dev-mode: OTP printed on the page, no SMS yet
    mobile_value = ''         # carried forward across the mobile -> otp steps
    stage = 'summary'         # summary -> mobile -> otp -> (done via txn.status)

    is_expired_now = txn.status == Transaction.PENDING and txn.expires_at < timezone.now()
    if is_expired_now:
        txn.status = Transaction.EXPIRED
        txn.save(update_fields=['status', 'updated_at'])

    if request.method == 'POST' and txn.status == Transaction.PENDING:
        action = request.POST.get('action')

        if action == 'reject':
            try:
                TransactionService.reject_by_seller(txn)
            except ValueError as e:
                error = str(e)
            txn.refresh_from_db()

        elif action == 'start_accept':
            # Server-side backstop for the client-side checkbox gate — a
            # request without agreed_terms (JS disabled, form tampered with)
            # must not be able to proceed past the summary stage.
            if not request.POST.get('agreed_terms'):
                error = 'يجب الموافقة على الشروط والأحكام قبل المتابعة.'
                stage = 'summary'
            else:
                stage = 'mobile'

        elif action == 'send_otp':
            mobile_value = request.POST.get('mobile', '').strip()
            if not mobile_value:
                error = 'أدخل رقم جوالك.'
                stage = 'mobile'
            else:
                otp_plain, sent = OTPService.request_otp(mobile_value, purpose=OTPVerification.SELLER_CONFIRM)
                if not sent:
                    error = 'تم تجاوز الحد المسموح للمحاولات. حاول مرة أخرى لاحقاً.'
                    stage = 'mobile'
                else:
                    otp_debug = otp_plain
                    stage = 'otp'

        elif action == 'verify_otp':
            mobile_value = request.POST.get('mobile', '').strip()
            otp_code = request.POST.get('otp_code', '').strip()

            ok, otp_error = OTPService.verify_otp(mobile_value, otp_code, purpose=OTPVerification.SELLER_CONFIRM)
            if not ok:
                error = otp_error
                stage = 'otp'
            elif hash_phone(mobile_value) != txn.seller_mobile_hash:
                error = 'رقم الجوال الذي أدخلته لا يطابق رقم البائع المسجَّل في هذه الصفقة.'
                stage = 'mobile'
            else:
                try:
                    TransactionService.confirm_by_seller(txn)
                except ValueError as e:
                    error = str(e)
                txn.refresh_from_db()

    buyer = txn.initiator
    buyer_phone = buyer.phone_number
    buyer_phone_masked = (
        f'{buyer_phone[:3]} ••• {buyer_phone[-2:]}' if len(buyer_phone) >= 5 else buyer_phone
    )
    buyer_verified_label = {
        'verified': 'مستخدم موثّق',
        'pending':  'قيد التحقق',
        'unverified': 'مستخدم غير موثّق',
    }.get(buyer.verification_status, 'مستخدم')

    context = {
        'txn': txn,
        'product': txn.product,
        'buyer': buyer,
        'buyer_phone_masked': buyer_phone_masked,
        'buyer_verified_label': buyer_verified_label,
        'masked_identifier': _masked_imei(txn.product),
        'error': error,
        'stage': stage,
        'mobile_value': mobile_value,
        'otp_debug': otp_debug,
    }
    return render(request, 'transactions/seller_confirm.html', context)
