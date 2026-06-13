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

    # ── Palette ───────────────────────────────────────────────────────────────
    NAVY       = colors.HexColor('#1A3A6B')
    GOLD       = colors.HexColor('#C9A84C')
    GOLD_LIGHT = colors.HexColor('#FEF9EE')
    TEXT_DARK  = colors.HexColor('#1A1A2E')
    SUBTEXT    = colors.HexColor('#6B7280')
    SUCCESS    = colors.HexColor('#10B981')
    WARNING    = colors.HexColor('#F59E0B')
    LIGHT_BG   = colors.HexColor('#F8F9FC')
    STRIPE_BG  = colors.HexColor('#EFF3FA')
    BORDER_C   = colors.HexColor('#E5E7EB')

    PAGE_W, PAGE_H = A4
    M  = 1.8 * cm    # content margin
    BD = 0.6 * cm    # page border inset from edge
    BDI = BD + 0.22 * cm  # inner border inset

    c = pdfcanvas.Canvas(str(output_path), pagesize=A4)
    font_r = _ARABIC_FONT if _FONT_REGISTERED else 'Helvetica'
    font_b = _ARABIC_FONT_BOLD if _FONT_REGISTERED else 'Helvetica-Bold'

    # ── Decorative double border ───────────────────────────────────────────────
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.8)
    c.rect(BD, BD, PAGE_W - 2 * BD, PAGE_H - 2 * BD, stroke=True, fill=False)
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.4)
    c.rect(BDI, BDI, PAGE_W - 2 * BDI, PAGE_H - 2 * BDI, stroke=True, fill=False)

    # ── Header ────────────────────────────────────────────────────────────────
    HDR_H   = 4.0 * cm
    HDR_TOP = PAGE_H - BDI
    HDR_BOT = HDR_TOP - HDR_H

    c.setFillColor(NAVY)
    c.rect(BDI, HDR_BOT, PAGE_W - 2 * BDI, HDR_H, fill=True, stroke=False)
    c.setFillColor(GOLD)
    c.rect(BDI, HDR_BOT, PAGE_W - 2 * BDI, 0.25 * cm, fill=True, stroke=False)

    c.setFillColor(colors.white)
    c.setFont(font_b, 30)
    c.drawRightString(PAGE_W - M, HDR_BOT + 2.1 * cm, _ar('تواتر'))

    c.setFont(font_r, 10)
    c.setFillColor(GOLD)
    c.drawString(M, HDR_BOT + 2.55 * cm, _ar('منصة توثيق تحويل الملكية'))
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.HexColor('#A8BDD4'))
    c.drawString(M, HDR_BOT + 1.8 * cm, 'tawatur.sa')

    # ── Certificate type title ─────────────────────────────────────────────────
    y = HDR_BOT - 1.3 * cm

    c.setFillColor(TEXT_DARK)
    c.setFont(font_b, 20)
    c.drawCentredString(PAGE_W / 2, y, _ar(cert_type_label))

    # Ornamental line + diamond under title
    y -= 0.5 * cm
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.line(M, y, PAGE_W / 2 - 2.5 * cm, y)
    c.line(PAGE_W / 2 + 2.5 * cm, y, PAGE_W - M, y)
    c.setFillColor(GOLD)
    d = 0.2 * cm
    cx = PAGE_W / 2
    path = c.beginPath()
    path.moveTo(cx, y + d); path.lineTo(cx + d, y)
    path.lineTo(cx, y - d); path.lineTo(cx - d, y)
    path.close()
    c.drawPath(path, fill=True, stroke=False)

    # ── Certificate number badge ───────────────────────────────────────────────
    y -= 0.95 * cm
    bw = 7.0 * cm
    bx = (PAGE_W - bw) / 2
    c.setFillColor(GOLD_LIGHT)
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.roundRect(bx, y - 0.3 * cm, bw, 0.8 * cm, radius=4, fill=True, stroke=True)
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(PAGE_W / 2, y, cert_number)

    # ── Intro sentence ────────────────────────────────────────────────────────
    y -= 0.75 * cm
    c.setFont(font_r, 9)
    c.setFillColor(SUBTEXT)
    c.drawCentredString(PAGE_W / 2, y,
                        _ar('نشهد بأن عملية نقل الملكية المبيّنة أدناه قد اكتملت وتمّ توثيقها رسمياً'))

    # ── Info card with alternating row stripes ────────────────────────────────
    rows = [
        ('الفئة',   product.get_category_display()),
        ('الماركة', product.brand),
        ('الموديل', product.model),
        ('الحالة',  product.get_condition_display()),
    ]
    if transaction:
        rows.append(('نوع المعاملة', transaction.get_transaction_type_display()))
        if transaction.price:
            rows.append(('قيمة المعاملة', f'{transaction.price} ريال سعودي'))
        if transaction.approved_at:
            rows.append(('تاريخ التوثيق',
                         transaction.approved_at.strftime('%Y/%m/%d  %H:%M')))

    trust_map = {'excellent': 'ممتاز', 'high': 'عالٍ', 'medium': 'متوسط', 'low': 'منخفض'}
    trust_ar  = trust_map.get(product.trust_level, product.trust_level)
    is_good   = product.trust_score >= 65

    ROW_H    = 0.72 * cm
    CARD_PAD = 0.38 * cm
    card_h   = (len(rows) + 1) * ROW_H + 2 * CARD_PAD

    y -= 0.3 * cm
    card_top = y
    card_bot = card_top - card_h

    c.setFillColor(LIGHT_BG)
    c.setStrokeColor(BORDER_C)
    c.setLineWidth(0.5)
    c.roundRect(M, card_bot, PAGE_W - 2 * M, card_h, radius=5, fill=True, stroke=True)

    for i, (lbl, val) in enumerate(rows):
        row_top = card_top - CARD_PAD - i * ROW_H
        if i % 2 == 0:
            c.setFillColor(STRIPE_BG)
            c.rect(M + 2, row_top - ROW_H, PAGE_W - 2 * M - 4, ROW_H,
                   fill=True, stroke=False)
        text_y = row_top - ROW_H * 0.62
        c.setFont(font_b, 10)
        c.setFillColor(SUBTEXT)
        c.drawRightString(PAGE_W - M - 0.5 * cm, text_y, _ar(lbl + ' :'))
        c.setFont(font_r, 10)
        c.setFillColor(TEXT_DARK)
        c.drawString(M + 0.5 * cm, text_y, str(val))

    # Trust score row
    n = len(rows)
    trust_top = card_top - CARD_PAD - n * ROW_H
    if n % 2 == 0:
        c.setFillColor(STRIPE_BG)
        c.rect(M + 2, trust_top - ROW_H, PAGE_W - 2 * M - 4, ROW_H,
               fill=True, stroke=False)
    trust_y = trust_top - ROW_H * 0.62
    c.setFont(font_b, 10)
    c.setFillColor(SUBTEXT)
    c.drawRightString(PAGE_W - M - 0.5 * cm, trust_y, _ar('درجة الثقة :'))
    c.setFont(font_b, 10)
    c.setFillColor(SUCCESS if is_good else WARNING)
    c.drawString(M + 0.5 * cm, trust_y,
                 f'{product.trust_score}/100  —  {trust_ar}')

    # ── QR Code in framed box ─────────────────────────────────────────────────
    QR  = 3.2 * cm
    QRP = 0.3 * cm
    QRF = QR + 2 * QRP
    QRX = (PAGE_W - QRF) / 2

    y = card_bot - 0.55 * cm
    c.setFont(font_r, 9)
    c.setFillColor(SUBTEXT)
    c.drawCentredString(PAGE_W / 2, y, _ar('امسح رمز QR للتحقق من صحة الشهادة'))

    qr_frame_bot = y - 0.2 * cm - QRF
    c.setFillColor(colors.white)
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.8)
    c.roundRect(QRX, qr_frame_bot, QRF, QRF, radius=4, fill=True, stroke=True)

    full_qr_path = Path(settings.MEDIA_ROOT) / qr_path
    if full_qr_path.exists():
        c.drawImage(str(full_qr_path),
                    QRX + QRP, qr_frame_bot + QRP,
                    width=QR, height=QR)

    c.setFont('Helvetica', 7.5)
    c.setFillColor(SUBTEXT)
    c.drawCentredString(PAGE_W / 2, qr_frame_bot - 0.35 * cm, verification_url)

    # ── Footer with gold stripe ────────────────────────────────────────────────
    c.setFillColor(GOLD)
    c.rect(BDI, BDI + 0.85 * cm, PAGE_W - 2 * BDI, 0.18 * cm,
           fill=True, stroke=False)

    issued = timezone.now().strftime('%Y/%m/%d')
    c.setFont(font_r, 8)
    c.setFillColor(SUBTEXT)
    c.drawRightString(PAGE_W - M, BDI + 0.38 * cm,
                      _ar(f'تاريخ الإصدار: {issued}'))
    c.setFont('Helvetica', 8)
    c.drawString(M, BDI + 0.38 * cm,
                 'Issued by Tawatur Platform  ·  tawatur.sa')

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

        pdf_path = _draw_pdf(
            cert_number=cert_number,
            cert_type_label='شهادة نقل ملكية',
            product=transaction.product,
            qr_path=qr_path,
            verification_url=verification_url,
            transaction=transaction,
        )

        cert = Certificate.objects.create(
            certificate_number=cert_number,
            transaction=transaction,
            product=transaction.product,
            owner=transaction.recipient,
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
