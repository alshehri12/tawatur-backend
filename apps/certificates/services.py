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
    Generate the next sequential certificate number.
    Format: TWR-{6-digit zero-padded sequence}
    Example: TWR-000049

    Backed by a singleton counter row, incremented inside a row-locked
    transaction so concurrent requests never hand out the same number.
    """
    from django.db import transaction as db_transaction
    from apps.certificates.models import CertificateSequence

    with db_transaction.atomic():
        seq, _ = CertificateSequence.objects.select_for_update().get_or_create(pk=1)
        number = f'TWR-{seq.next_value:06d}'
        seq.next_value += 1
        seq.save(update_fields=['next_value'])

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


# ── Arabic-indic numerals (used for money amounts, matching Saudi convention) ──

_ARABIC_INDIC = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')


def _money_ar(value) -> str:
    """Format a Decimal/float as '٥٬٣٠٠٫٠٠' — Arabic-indic digits, Arabic
    thousands (٬) and decimal (٫) separators, matching how Saudi legal
    documents typically render currency amounts."""
    formatted = f'{float(value):,.2f}'
    formatted = formatted.replace(',', '٬').replace('.', '٫')
    return formatted.translate(_ARABIC_INDIC)


def _id_type_label(id_number: str) -> str:
    """Saudi national IDs start with 1, Iqama (residency) IDs start with 2."""
    if not id_number:
        return 'غير محدد'
    if id_number.startswith('1'):
        return 'هوية وطنية'
    if id_number.startswith('2'):
        return 'إقامة'
    return 'غير محدد'


DISCLAIMER_TITLE = 'إقرار وإخلاء مسؤولية'
DISCLAIMER_P1 = (
    'منصة تواتر منصة إلكترونية مختصة بتوثيق عمليات البيع والشراء لضمان الحقوق '
    'وإثبات وقوع الصفقات. تقتصر مهمتها على التوثيق وتسجيل البيانات المدخلة، '
    'ولا تتحمل أي مسؤولية عن صحتها أو دقتها.'
)
DISCLAIMER_P2 = (
    'المسؤولية الكاملة عن صحة جميع البيانات الواردة تقع على عاتق مدخلها، '
    'وأي بيانات غير صحيحة تُعرّض صاحبها للمساءلة القانونية وفق أنظمة المملكة '
    'العربية السعودية.'
)


# ── PDF Generation ────────────────────────────────────────────────────────────

def _draw_pdf(cert_number: str, cert_type_label: str, product,
              qr_path: str, verification_url: str,
              transaction=None) -> str:
    """
    Render the certificate PDF and save to media/certificates/pdf/{cert_number}.pdf.
    Returns the path relative to MEDIA_ROOT.

    Layout matches the reference "وثيقة توثيق عملية بيع وشراء" design: a plain
    letterhead (logo + reference number), a title bar, four numbered sections
    (المشتري / البائع / السلعة / حالة العقد) each under a navy header bar, a
    disclaimer box, and a footer — instead of the previous single-card layout.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.pdfbase.pdfmetrics import stringWidth

    _register_fonts()

    pdf_dir = Path(settings.MEDIA_ROOT) / 'certificates' / 'pdf'
    pdf_dir.mkdir(parents=True, exist_ok=True)

    rel_path = f'certificates/pdf/{cert_number}.pdf'
    output_path = Path(settings.MEDIA_ROOT) / rel_path

    # ── Palette — deep navy + gold, matching the reference document's
    # formal-letterhead look (deliberately distinct from the app's green UI —
    # this is a legal document, not an app screen) ────────────────────────────
    NAVY        = colors.HexColor('#12294A')
    NAVY_LIGHT  = colors.HexColor('#EEF2F8')
    GOLD        = colors.HexColor('#C9A84C')
    INK         = colors.HexColor('#1A1F29')
    MUTED       = colors.HexColor('#6B7280')
    FAINT       = colors.HexColor('#9CA6B4')
    LINE        = colors.HexColor('#E4E9F0')
    SUCCESS     = colors.HexColor('#0E8C55')
    LINK_BLUE   = colors.HexColor('#2557A7')

    font_r = _ARABIC_FONT if _FONT_REGISTERED else 'Helvetica'
    font_b = _ARABIC_FONT_BOLD if _FONT_REGISTERED else 'Helvetica-Bold'

    def wrap_ar(text: str, font: str, size: float, max_width: float) -> list:
        """Word-wrap `text` (logical order) to fit max_width, measuring each
        candidate line's *reshaped* width so Arabic ligatures are accounted
        for. Returns lines still in logical order — _ar() is applied per
        line at draw time."""
        words = text.split(' ')
        lines, current = [], []
        for w in words:
            trial = ' '.join(current + [w])
            if current and stringWidth(_ar(trial), font, size) > max_width:
                lines.append(' '.join(current))
                current = [w]
            else:
                current.append(w)
        if current:
            lines.append(' '.join(current))
        return lines

    # ── Gather all data up front — nothing here touches the canvas, so the
    # page height can be computed exactly before it's created ────────────────
    from apps.transactions.models import Transaction as TxnModel
    is_direct = bool(transaction) and transaction.transaction_type == TxnModel.DIRECT_PURCHASE

    buyer = transaction.initiator if transaction else None
    seller_otp_verified = bool(transaction) and transaction.audit_logs.filter(
        action__in=['seller_confirmed_via_link']
    ).exists()

    section1_rows = []
    if buyer:
        section1_rows = [
            ('الاسم الكامل', buyer.full_name or '—'),
            ('رقم الجوال', buyer.phone_number or '—'),
            ('نوع الحساب', buyer.get_user_type_display()),
            ('طريقة التحقق', 'تم التحقق عبر رمز OTP للجوال'),
        ]

    section2_rows = []
    section2_id_label = 'رقم الهوية / الإقامة'
    seller_id = ''
    if transaction and is_direct:
        seller_id = transaction.seller_id_number or ''
        section2_rows = [
            ('الاسم الكامل', transaction.seller_full_name or '—'),
            ('نوع الهوية', _id_type_label(seller_id)),
            (section2_id_label, seller_id or '—'),
            ('التحقق من الهوية',
             'تم التحقق عبر رمز OTP للجوال' if seller_otp_verified
             else 'لم يتم التحقق — بيانات مدخلة من المشتري'),
        ]

    product_headline = f'{product.brand} {product.model} ({product.get_condition_display()})'
    identifier = product.imei_1 or product.serial_number
    section3_rows = [
        ('قيمة الصفقة المتفق عليها',
         f'{_money_ar(transaction.price)} ريال سعودي' if transaction and transaction.price else '—'),
        ('المعرّف (رقم تسلسلي/IMEI — إدخال يدوي)',
         f'{identifier} (يدوي)' if identifier else 'غير مُدخل'),
    ]

    section4_rows = [
        ('حالة العقد', 'مكتمل وموثق'),
        ('تاريخ الإتمام',
         transaction.approved_at.strftime('%Y/%m/%d %I:%M %p') if transaction and transaction.approved_at else '—'),
    ]

    # Build the section list, drop empty ones, then number what's left with
    # Arabic ordinals (أولاً/ثانياً/...) so numbering stays correct even when
    # a section is skipped (e.g. an on-demand ownership certificate has no
    # buyer/seller transaction to describe).
    ordinals = ['أولاً', 'ثانياً', 'ثالثاً', 'رابعاً', 'خامساً']
    raw_sections = [
        ('بيانات المشتري', section1_rows, None),
        ('بيانات البائع', section2_rows, None),
        ('تفاصيل السلعة', section3_rows, product_headline),
        ('حالة العقد', section4_rows, None),
    ]
    non_empty = [(t, r, h) for (t, r, h) in raw_sections if r]
    sections = [(f'{ordinals[i]} — {t}', r, h) for i, (t, r, h) in enumerate(non_empty)]
    section2_full_title = next((t for t, r, h in sections if 'البائع' in t), None)

    if is_direct:
        intro_text = (
            'بموجب هذه الوثيقة الصادرة عن منصة تواتر، يُشهد على إتمام عملية البيع '
            'والشراء الموضحة أدناه بين الطرفين المذكورين، بعد استيفاء إجراءات '
            'التحقق المطلوبة. وتُعدّ هذه الوثيقة إثباتاً رسمياً لوقوع الصفقة وتفاصيلها.'
        )
    else:
        intro_text = (
            'بموجب هذه الوثيقة الصادرة عن منصة تواتر، يُشهد بأن الجهاز الموضحة '
            'بياناته أدناه مسجّل ومملوك حالياً للمالك الموثّق على المنصة.'
        )

    PAGE_W, _A4_H = A4
    M = 1.9 * cm
    CONTENT_W = PAGE_W - 2 * M

    intro_lines = wrap_ar(intro_text, font_r, 9.5, CONTENT_W - 1.0 * cm)
    disc_p1_lines = wrap_ar(DISCLAIMER_P1, font_r, 8.7, CONTENT_W - 1.2 * cm)
    disc_p2_lines = wrap_ar(DISCLAIMER_P2, font_r, 8.7, CONTENT_W - 1.2 * cm)

    # ── Vertical rhythm constants ──────────────────────────────────────────
    HDR_H       = 2.5 * cm
    TITLE_BAR_H = 1.1 * cm
    SEC_HDR_H   = 0.8 * cm
    ROW_H       = 0.72 * cm
    HEADLINE_H  = 0.85 * cm   # extra row for the bold product name in section 3
    LINE_H      = 0.4 * cm    # wrapped-text line height
    QR, QRP     = 2.6 * cm, 0.25 * cm
    QRF         = QR + 2 * QRP

    def section_h(rows, headline):
        return SEC_HDR_H + len(rows) * ROW_H + (HEADLINE_H if headline else 0)

    sections_total_h = sum(section_h(r, h) for (_, r, h) in sections)
    sections_total_h += 0.3 * cm * (len(sections) - 1)  # gap between sections

    disclaimer_h = (
        0.55 * cm  # title
        + len(disc_p1_lines) * LINE_H
        + 0.15 * cm
        + len(disc_p2_lines) * LINE_H
        + 0.6 * cm  # box padding
    )

    PAGE_H = (
        0.5 * cm                                   # top gold rule margin
        + HDR_H
        + 0.3 * cm
        + TITLE_BAR_H
        + 0.5 * cm
        + len(intro_lines) * LINE_H
        + 0.5 * cm
        + sections_total_h
        + 0.5 * cm
        + disclaimer_h
        + 0.5 * cm
        + QRF + 0.7 * cm                           # QR block + captions
        + 1.6 * cm                                  # footer block
        + 0.6 * cm                                  # bottom breathing room
    )
    PAGE_H = min(PAGE_H, 3 * _A4_H)  # sane upper bound; keeps content-fit sizing

    c = pdfcanvas.Canvas(str(output_path), pagesize=(PAGE_W, PAGE_H))

    def rtl_row(label: str, value: str, y_pos: float, x_right: float, label_w: float):
        c.setFont(font_b, 9)
        c.setFillColor(MUTED)
        c.drawRightString(x_right, y_pos, _ar(label))
        c.setFont(font_r, 9.5)
        c.setFillColor(INK)
        c.drawRightString(x_right - label_w, y_pos, _ar(str(value)))

    # ── Top gold rule ─────────────────────────────────────────────────────
    y = PAGE_H - 0.5 * cm
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.line(M, y, PAGE_W - M, y)

    # ── Header — right: logo + wordmark + subtitle. left: ref + issue date ──
    y -= 0.15 * cm
    logo_size = 0.85 * cm
    c.setFillColor(NAVY)
    c.roundRect(PAGE_W - M - logo_size, y - logo_size, logo_size, logo_size, radius=4, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont(font_b, 15)
    c.drawCentredString(PAGE_W - M - logo_size / 2, y - logo_size + 0.27 * cm, _ar('ت'))

    c.setFillColor(NAVY)
    c.setFont(font_b, 17)
    c.drawRightString(PAGE_W - M - logo_size - 0.25 * cm, y - 0.35 * cm, _ar('تواتر'))
    c.setFillColor(MUTED)
    c.setFont(font_r, 8.5)
    c.drawRightString(PAGE_W - M - logo_size - 0.25 * cm, y - 0.85 * cm, _ar('منصة توثيق عمليات البيع والشراء'))

    c.setFillColor(NAVY)
    c.setFont(font_b, 10.5)
    c.drawString(M, y - 0.35 * cm, cert_number)
    c.setFillColor(MUTED)
    c.setFont(font_r, 8)
    issued_str = timezone.now().strftime('%Y/%m/%d — %I:%M %p')
    c.drawString(M, y - 0.85 * cm, _ar(f'تاريخ الإصدار: {issued_str}'))

    y -= HDR_H

    # ── Title bar ───────────────────────────────────────────────────────────
    # Direct-purchase transactions get the reference document's exact title;
    # on-demand certificates (no transaction, e.g. current-ownership) fall
    # back to their own type label since "بيع وشراء" wouldn't apply to them.
    title_bar_text = 'وثيقة توثيق عملية بيع وشراء' if is_direct else cert_type_label
    y -= 0.3 * cm
    c.setFillColor(NAVY_LIGHT)
    c.rect(M, y - TITLE_BAR_H, CONTENT_W, TITLE_BAR_H, fill=True, stroke=False)
    c.setFillColor(NAVY)
    c.setFont(font_b, 13)
    c.drawCentredString(PAGE_W / 2, y - TITLE_BAR_H / 2 - 0.15 * cm, _ar(title_bar_text))
    y -= TITLE_BAR_H

    # ── Intro paragraph ─────────────────────────────────────────────────────
    y -= 0.5 * cm
    c.setFont(font_r, 9.5)
    c.setFillColor(MUTED)
    for line in intro_lines:
        c.drawCentredString(PAGE_W / 2, y, _ar(line))
        y -= LINE_H

    # ── Sections ────────────────────────────────────────────────────────────
    y -= 0.15 * cm
    for title, rows, headline in sections:
        h = section_h(rows, headline)
        sec_top = y
        sec_bot = sec_top - h

        # Navy header bar
        c.setFillColor(NAVY)
        c.rect(M, sec_top - SEC_HDR_H, CONTENT_W, SEC_HDR_H, fill=True, stroke=False)
        c.setFillColor(colors.white)
        c.setFont(font_b, 10.5)
        c.drawRightString(PAGE_W - M - 0.35 * cm, sec_top - SEC_HDR_H * 0.65, _ar(title))

        # Body
        c.setFillColor(colors.white)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.75)
        c.rect(M, sec_bot, CONTENT_W, h - SEC_HDR_H, fill=True, stroke=True)

        row_y = sec_top - SEC_HDR_H

        if headline:
            row_y -= HEADLINE_H
            c.setFillColor(NAVY)
            c.setFont(font_b, 12.5)
            c.drawCentredString(PAGE_W / 2, row_y + HEADLINE_H * 0.4, _ar(headline))
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.line(M + 0.3 * cm, row_y, PAGE_W - M - 0.3 * cm, row_y)

        for i, (lbl, val) in enumerate(rows):
            row_top = row_y - i * ROW_H
            text_y = row_top - ROW_H * 0.65
            is_link = (title == section2_full_title and lbl == section2_id_label and val not in ('—', ''))
            c.setFont(font_b, 9)
            c.setFillColor(MUTED)
            c.drawRightString(PAGE_W - M - 0.35 * cm, text_y, _ar(lbl))
            c.setFont(font_r, 9.5)
            if val in ('تم التحقق عبر رمز OTP للجوال', 'مكتمل وموثق'):
                c.setFillColor(SUCCESS)
            elif is_link:
                c.setFillColor(LINK_BLUE)
            else:
                c.setFillColor(INK)
            c.drawRightString(PAGE_W - M - 6.6 * cm, text_y, _ar(str(val)))
            if i < len(rows) - 1:
                c.setStrokeColor(LINE)
                c.setLineWidth(0.5)
                c.line(M + 0.3 * cm, row_top - ROW_H, PAGE_W - M - 0.3 * cm, row_top - ROW_H)

        y = sec_bot - 0.3 * cm

    # ── Disclaimer box ──────────────────────────────────────────────────────
    y -= 0.2 * cm
    disc_top = y
    disc_bot = disc_top - disclaimer_h
    c.setFillColor(NAVY_LIGHT)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.75)
    c.roundRect(M, disc_bot, CONTENT_W, disclaimer_h, radius=5, fill=True, stroke=True)

    ty = disc_top - 0.45 * cm
    c.setFont(font_b, 10)
    c.setFillColor(NAVY)
    c.drawRightString(PAGE_W - M - 0.6 * cm, ty, _ar(DISCLAIMER_TITLE))
    ty -= 0.5 * cm
    c.setFont(font_r, 8.7)
    c.setFillColor(MUTED)
    for line in disc_p1_lines:
        c.drawRightString(PAGE_W - M - 0.6 * cm, ty, _ar(line))
        ty -= LINE_H
    ty -= 0.15 * cm
    for line in disc_p2_lines:
        c.drawRightString(PAGE_W - M - 0.6 * cm, ty, _ar(line))
        ty -= LINE_H

    y = disc_bot

    # ── QR code — kept as an extra beyond the reference design, since it's a
    # genuinely useful no-login verification path already built on this
    # platform; still simple/unobtrusive so it doesn't compete visually ──────
    y -= 0.6 * cm
    c.setFont(font_r, 8)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, y, _ar('امسح الرمز للتحقق من صحة الوثيقة — بلا تسجيل دخول'))

    qr_frame_bot = y - 0.2 * cm - QRF
    QRX = (PAGE_W - QRF) / 2
    c.setFillColor(colors.white)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.75)
    c.roundRect(QRX, qr_frame_bot, QRF, QRF, radius=5, fill=True, stroke=True)

    full_qr_path = Path(settings.MEDIA_ROOT) / qr_path
    if full_qr_path.exists():
        c.drawImage(str(full_qr_path), QRX + QRP, qr_frame_bot + QRP, width=QR, height=QR)

    c.setFont('Helvetica', 7)
    c.setFillColor(FAINT)
    c.drawCentredString(PAGE_W / 2, qr_frame_bot - 0.35 * cm, verification_url)

    y = qr_frame_bot - 0.35 * cm

    # ── Footer ──────────────────────────────────────────────────────────────
    y -= 0.5 * cm
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.line(M, y, PAGE_W - M, y)
    y -= 0.5 * cm

    c.setFont(font_b, 10.5)
    c.setFillColor(NAVY)
    c.drawCentredString(PAGE_W / 2, y, _ar('منصة تواتر'))
    y -= 0.42 * cm
    c.setFont(font_r, 8)
    c.setFillColor(MUTED)
    c.drawCentredString(PAGE_W / 2, y, _ar('وثيقة صادرة آلياً — يمكن التحقق منها برقم المرجع أعلاه'))
    y -= 0.4 * cm
    c.setFont(font_r, 7.5)
    c.setFillColor(FAINT)
    c.drawCentredString(PAGE_W / 2, y, _ar(f'رقم المرجع: {cert_number} | {issued_str}'))

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
