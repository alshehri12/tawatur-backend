"""
CertificateService — generates QR codes and Arabic PDF certificates.

PDF layout (A4, RTL):
  ┌─────────────────────────────────────────┐
  │  [Header: navy bar — تواتر]             │
  │  [Certificate type title — centered]    │
  │  [Certificate number]                   │
  │                                         │
  │  [Product details table]                │
  │  [Transaction details table]            │
  │  [Chain & trust info]                   │
  │                                         │
  │  [QR code — centered]                   │
  │  [Verification URL]                     │
  │  [Footer: issued date + disclaimer]     │
  └─────────────────────────────────────────┘
"""

import os
import random
import string
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.utils import timezone


# ── Arabic text helpers ───────────────────────────────────────────────────────

def _ar(text: str) -> str:
    """
    Reshape Arabic text and apply the BiDi algorithm so reportlab renders
    Arabic correctly (right-to-left, connected glyphs).
    Falls back to the original string if libraries are missing.
    """
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


# ── Font registration ─────────────────────────────────────────────────────────

_FONT_REGISTERED = False
_ARABIC_FONT = 'Amiri'
_ARABIC_FONT_BOLD = 'AmiriBold'


def _register_fonts():
    """Register the Amiri Arabic font with reportlab (once per process)."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_dir = Path(settings.BASE_DIR) / 'assets' / 'fonts'
    regular = font_dir / 'Amiri-Regular.ttf'
    bold = font_dir / 'Amiri-Bold.ttf'

    if regular.exists():
        pdfmetrics.registerFont(TTFont(_ARABIC_FONT, str(regular)))
    if bold.exists():
        pdfmetrics.registerFont(TTFont(_ARABIC_FONT_BOLD, str(bold)))

    _FONT_REGISTERED = True


# ── Certificate number ────────────────────────────────────────────────────────

def _generate_certificate_number() -> str:
    """
    Generate a unique, human-readable certificate number.
    Format: TW-{YEAR}-{8 random alphanumeric uppercase chars}
    Example: TW-2026-A3B7KX2Q
    """
    from apps.certificates.models import Certificate
    year = timezone.now().year
    while True:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        number = f'TW-{year}-{suffix}'
        if not Certificate.objects.filter(certificate_number=number).exists():
            return number


# ── QR Code ───────────────────────────────────────────────────────────────────

def _generate_qr(data: str, filename: str) -> str:
    """
    Generate a QR code PNG encoding `data`.
    Saves to media/certificates/qr/{filename}.png.
    Returns the path relative to MEDIA_ROOT.
    """
    import qrcode

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=8, border=4)
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color='#1A3A6B', back_color='white')

    qr_dir = Path(settings.MEDIA_ROOT) / 'certificates' / 'qr'
    qr_dir.mkdir(parents=True, exist_ok=True)

    rel_path = f'certificates/qr/{filename}.png'
    img.save(Path(settings.MEDIA_ROOT) / rel_path)

    return rel_path


# ── PDF Generation ────────────────────────────────────────────────────────────

def _draw_pdf(cert_number: str, cert_type_label: str, product,
              qr_path: str, verification_url: str,
              transaction=None) -> str:
    """
    Render the certificate PDF and save to media/certificates/pdf/{cert_number}.pdf.
    Returns the path relative to MEDIA_ROOT.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as pdfcanvas

    _register_fonts()

    pdf_dir = Path(settings.MEDIA_ROOT) / 'certificates' / 'pdf'
    pdf_dir.mkdir(parents=True, exist_ok=True)

    rel_path = f'certificates/pdf/{cert_number}.pdf'
    output_path = Path(settings.MEDIA_ROOT) / rel_path

    # ── Palette — matches the app's green/white brand identity ────────────────
    GREEN       = colors.HexColor('#0BA378')
    GREEN_DEEP  = colors.HexColor('#067A59')
    GREEN_INK   = colors.HexColor('#0A2E22')
    MINT        = colors.HexColor('#E9F8F1')
    INK         = colors.HexColor('#14231C')
    MUTED       = colors.HexColor('#7A8C83')
    FAINT       = colors.HexColor('#ADBDB4')
    LINE        = colors.HexColor('#ECF2EE')
    WARNING     = colors.HexColor('#B45309')

    # ── Build the device/deal rows first — the page height is sized to fit
    # them exactly, like a real receipt/certificate, instead of forcing a
    # fixed A4 sheet that leaves most of the page empty ─────────────────────
    rows = [
        ('الفئة',   product.get_category_display()),
        ('الماركة والموديل', f'{product.brand} {product.model}'),
        ('الحالة',  product.get_condition_display()),
    ]
    is_direct = False
    if transaction:
        from apps.transactions.models import Transaction as TxnModel
        is_direct = transaction.transaction_type == TxnModel.DIRECT_PURCHASE
        if transaction.price:
            rows.append(('قيمة الصفقة', f'{transaction.price} ريال سعودي'))
        if transaction.approved_at:
            rows.append(('تاريخ التوثيق', transaction.approved_at.strftime('%Y/%m/%d')))

    # ── Parties block — full name, mobile, and ID for BOTH buyer and seller ───
    seller_lines, buyer_lines = [], []
    if transaction and is_direct:
        if transaction.seller_full_name:
            seller_lines.append(transaction.seller_full_name)
        if transaction.seller_mobile:
            seller_lines.append(transaction.seller_mobile)
        if transaction.seller_id_number:
            seller_lines.append(transaction.seller_id_number)
        if transaction.seller_city:
            seller_lines.append(transaction.seller_city)

        buyer = transaction.initiator
        if buyer.full_name:
            buyer_lines.append(buyer.full_name)
        if buyer.phone_number:
            buyer_lines.append(buyer.phone_number)
        if buyer.id_number:
            buyer_lines.append(buyer.id_number)

    PARTY_LINE_H = 0.52 * cm
    PARTY_PAD = 0.45 * cm
    party_lines_n = max(len(seller_lines), len(buyer_lines), 1)
    party_h = party_lines_n * PARTY_LINE_H + 2 * PARTY_PAD + 0.5 * cm  # +label row
    has_parties = bool(seller_lines or buyer_lines)

    PAGE_W, _A4_H = A4
    M = 2.1 * cm   # content margin — generous, keeps the page from feeling cramped

    HDR_H    = 3.4 * cm
    ROW_H    = 0.85 * cm
    CARD_PAD = 0.5 * cm
    card_h   = len(rows) * ROW_H + 2 * CARD_PAD
    QR, QRP  = 3.0 * cm, 0.28 * cm
    QRF      = QR + 2 * QRP

    # Sum of every vertical gap used below, top to bottom, so the page is
    # exactly as tall as the content — never a near-empty A4 sheet.
    PAGE_H = (
        HDR_H
        + 1.1 * cm                    # header -> intro line
        + 0.4 * cm                    # intro line -> parties/card
        + (party_h + 0.4 * cm if has_parties else 0)
        + 0.55 * cm
        + card_h
        + 0.9 * cm + 0.95 * cm        # card -> trust pill
        + 0.85 * cm                   # pill -> qr caption
        + 0.25 * cm + QRF             # qr caption -> qr frame
        + 0.4 * cm                    # qr -> verification url
        + 1.3 * cm + 0.6 * cm         # footer + bottom breathing room
    )
    PAGE_H = min(PAGE_H, _A4_H)  # never taller than A4, only ever shorter

    c = pdfcanvas.Canvas(str(output_path), pagesize=(PAGE_W, PAGE_H))
    font_r = _ARABIC_FONT if _FONT_REGISTERED else 'Helvetica'
    font_b = _ARABIC_FONT_BOLD if _FONT_REGISTERED else 'Helvetica-Bold'

    def rtl_row(label: str, value: str, y_pos: float, label_size=10, value_size=10.5):
        """One RTL row: bold muted label on the far right, value right-aligned
        just inside it — both anchored right so the whole row reads correctly
        right-to-left, instead of mixing a right-anchored label with a
        left-anchored value."""
        c.setFont(font_b, label_size)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_W - M, y_pos, _ar(label))
        c.setFont(font_r, value_size)
        c.setFillColor(INK)
        c.drawRightString(PAGE_W - M - 4.8 * cm, y_pos, _ar(str(value)))

    # ── Header — single flat green band, no ornamentation ─────────────────────
    HDR_BOT = PAGE_H - HDR_H

    c.setFillColor(GREEN_INK)
    c.rect(0, HDR_BOT, PAGE_W, HDR_H, fill=True, stroke=False)

    c.setFillColor(colors.white)
    c.setFont(font_b, 26)
    c.drawRightString(PAGE_W - M, HDR_BOT + 2.05 * cm, _ar('تواتر'))
    c.setFont(font_r, 10.5)
    c.setFillColor(colors.HexColor('#BFEFDC'))
    c.drawRightString(PAGE_W - M, HDR_BOT + 1.4 * cm, _ar('منصّة توثيق ملكية الأجهزة'))

    c.setFont(font_b, 13)
    c.setFillColor(colors.white)
    c.drawString(M, HDR_BOT + 2.05 * cm, _ar(cert_type_label))
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.HexColor('#BFEFDC'))
    c.drawString(M, HDR_BOT + 1.4 * cm, cert_number)

    # ── Intro line ──────────────────────────────────────────────────────────
    y = HDR_BOT - 1.1 * cm
    c.setFont(font_r, 9.5)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, y,
                        _ar('نشهد بأن عملية نقل الملكية المبيّنة أدناه قد اكتملت وتمّ توثيقها رسمياً على منصة تواتر'))

    # ── Parties — البائع / المشتري side by side, full name + mobile + ID ──────
    if has_parties:
        y -= 0.4 * cm
        party_top = y
        party_bot = party_top - party_h
        col_gap = 0.3 * cm
        col_w = (PAGE_W - 2 * M - col_gap) / 2
        seller_x = PAGE_W - M - col_w   # right column (RTL: seller reads first)
        buyer_x = M

        for x, title, lines in (
            (seller_x, 'البائع', seller_lines),
            (buyer_x, 'المشتري', buyer_lines),
        ):
            c.setFillColor(MINT)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.75)
            c.roundRect(x, party_bot, col_w, party_h, radius=6, fill=True, stroke=True)

            ty = party_top - PARTY_PAD - 0.35 * cm
            c.setFont(font_b, 9)
            c.setFillColor(GREEN_DEEP)
            c.drawRightString(x + col_w - 0.4 * cm, ty, _ar(title))

            for i, line in enumerate(lines):
                ty2 = ty - 0.5 * cm - i * PARTY_LINE_H
                c.setFont(font_r, 9.5)
                c.setFillColor(INK)
                c.drawRightString(x + col_w - 0.4 * cm, ty2, _ar(str(line)))

        y = party_bot

    # ── Device details — one simple card, hairline dividers, right-aligned ───
    # (rows / ROW_H / CARD_PAD / card_h already computed above, before the
    # canvas was created, so the page height could be sized to fit them)
    y -= 0.55 * cm
    card_top = y
    card_bot = card_top - card_h

    c.setFillColor(colors.white)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.75)
    c.roundRect(M, card_bot, PAGE_W - 2 * M, card_h, radius=6, fill=True, stroke=True)

    for i, (lbl, val) in enumerate(rows):
        row_top = card_top - CARD_PAD - i * ROW_H
        text_y = row_top - ROW_H * 0.62
        rtl_row(lbl, val, text_y)
        if i < len(rows) - 1:
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.line(M + 0.4 * cm, row_top - ROW_H, PAGE_W - M - 0.4 * cm, row_top - ROW_H)

    # ── Trust score — its own small highlighted line, not buried in the table ─
    trust_map = {'excellent': 'ممتاز', 'high': 'عالٍ', 'medium': 'متوسط', 'low': 'منخفض'}
    trust_ar = trust_map.get(product.trust_level, product.trust_level)
    is_good = product.trust_score >= 65

    y = card_bot - 0.9 * cm
    pill_w, pill_h = 6.4 * cm, 0.95 * cm
    px = (PAGE_W - pill_w) / 2
    c.setFillColor(MINT if is_good else colors.HexColor('#FEF6E7'))
    c.roundRect(px, y - pill_h, pill_w, pill_h, radius=pill_h / 2, fill=True, stroke=False)
    c.setFont(font_b, 11)
    c.setFillColor(GREEN_DEEP if is_good else WARNING)
    c.drawCentredString(PAGE_W / 2, y - pill_h * 0.64,
                        _ar(f'درجة الثقة  {product.trust_score}/100  —  {trust_ar}'))

    # ── QR code — simple thin frame, no double borders ─────────────────────
    # (QR / QRP / QRF already computed above, before the canvas was created)
    QRX = (PAGE_W - QRF) / 2

    y = y - pill_h - 0.85 * cm
    c.setFont(font_r, 9)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, y, _ar('امسح الرمز للتحقق من صحة الشهادة — بلا تسجيل دخول'))

    qr_frame_bot = y - 0.25 * cm - QRF
    c.setFillColor(colors.white)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.75)
    c.roundRect(QRX, qr_frame_bot, QRF, QRF, radius=6, fill=True, stroke=True)

    full_qr_path = Path(settings.MEDIA_ROOT) / qr_path
    if full_qr_path.exists():
        c.drawImage(str(full_qr_path),
                    QRX + QRP, qr_frame_bot + QRP,
                    width=QR, height=QR)

    c.setFont('Helvetica', 7.5)
    c.setFillColor(FAINT)
    c.drawCentredString(PAGE_W / 2, qr_frame_bot - 0.4 * cm, verification_url)

    # ── Footer — one hairline, no gold stripe ─────────────────────────────────
    FOOT_Y = 1.3 * cm
    c.setStrokeColor(LINE)
    c.setLineWidth(0.75)
    c.line(M, FOOT_Y + 0.4 * cm, PAGE_W - M, FOOT_Y + 0.4 * cm)

    issued = timezone.now().strftime('%Y/%m/%d')
    c.setFont(font_r, 8)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - M, FOOT_Y, _ar(f'تاريخ الإصدار: {issued}'))
    c.setFont('Helvetica', 8)
    c.setFillColor(FAINT)
    c.drawString(M, FOOT_Y, 'Tawatur Platform')

    c.save()
    return rel_path


# ── Public Service API ────────────────────────────────────────────────────────

class CertificateService:

    @staticmethod
    def _get_site_url() -> str:
        """Base URL for public verification links."""
        return getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')

    @classmethod
    def generate_transfer_certificate(cls, transaction) -> 'Certificate':
        """
        Generate the Ownership Transfer Certificate for an approved transaction.
        Called automatically when a transaction is approved.
        """
        from apps.certificates.models import Certificate

        cert_number = _generate_certificate_number()
        verification_url = f'{cls._get_site_url()}/api/v1/verify/{cert_number}/'

        qr_path = _generate_qr(verification_url, cert_number)

        from .models import Certificate as CertModel
        from apps.transactions.models import Transaction as TxnModel
        is_direct = transaction.transaction_type == TxnModel.DIRECT_PURCHASE
        cert_label = 'عقد شراء مباشر' if is_direct else 'شهادة نقل ملكية'

        pdf_path = _draw_pdf(
            cert_number=cert_number,
            cert_type_label=cert_label,
            product=transaction.product,
            qr_path=qr_path,
            verification_url=verification_url,
            transaction=transaction,
        )

        # For direct purchases the buyer (initiator) is the new owner;
        # for legacy link-based transfers the recipient is the new owner.
        cert_owner = transaction.initiator if is_direct else transaction.recipient

        cert = Certificate.objects.create(
            certificate_number=cert_number,
            transaction=transaction,
            product=transaction.product,
            owner=cert_owner,
            certificate_type=Certificate.OWNERSHIP_TRANSFER,
            qr_code_path=qr_path,
            pdf_path=pdf_path,
            verification_url=verification_url,
        )

        return cert

    @classmethod
    def generate_ownership_certificate(cls, user, product) -> 'Certificate':
        """
        Generate a Current Ownership Certificate on demand.
        Only the current owner of the product may request this.
        """
        from apps.certificates.models import Certificate
        from apps.products.models import OwnershipRecord

        is_owner = OwnershipRecord.objects.filter(
            product=product, owner=user, is_current=True
        ).exists()
        if not is_owner:
            raise ValueError('فقط المالك الحالي يمكنه إنشاء شهادة الملكية.')

        cert_number = _generate_certificate_number()
        verification_url = f'{cls._get_site_url()}/api/v1/verify/{cert_number}/'

        qr_path = _generate_qr(verification_url, cert_number)
        pdf_path = _draw_pdf(
            cert_number=cert_number,
            cert_type_label='شهادة ملكية حالية',
            product=product,
            qr_path=qr_path,
            verification_url=verification_url,
        )

        cert = Certificate.objects.create(
            certificate_number=cert_number,
            product=product,
            owner=user,
            certificate_type=Certificate.CURRENT_OWNERSHIP,
            qr_code_path=qr_path,
            pdf_path=pdf_path,
            verification_url=verification_url,
        )

        return cert
