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
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    _register_fonts()

    pdf_dir = Path(settings.MEDIA_ROOT) / 'certificates' / 'pdf'
    pdf_dir.mkdir(parents=True, exist_ok=True)

    rel_path = f'certificates/pdf/{cert_number}.pdf'
    output_path = Path(settings.MEDIA_ROOT) / rel_path

    # ── Color palette (matches the light mode design) ─────────────────────────
    NAVY = colors.HexColor('#1A3A6B')
    LIGHT_BLUE = colors.HexColor('#E8EEF8')
    TEXT_DARK = colors.HexColor('#1A1A2E')
    SUBTEXT = colors.HexColor('#6B7280')
    SUCCESS = colors.HexColor('#10B981')
    BORDER = colors.HexColor('#E5E7EB')

    PAGE_W, PAGE_H = A4
    MARGIN = 2 * cm

    c = pdfcanvas.Canvas(str(output_path), pagesize=A4)

    # ── Header bar ────────────────────────────────────────────────────────────
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 3.5 * cm, PAGE_W, 3.5 * cm, fill=True, stroke=False)

    # Platform name in Arabic (right-aligned in header)
    c.setFillColor(colors.white)
    c.setFont(_ARABIC_FONT_BOLD if _FONT_REGISTERED else 'Helvetica-Bold', 28)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 2.2 * cm, _ar('تواتر'))

    # Sub-label on the left
    c.setFont(_ARABIC_FONT if _FONT_REGISTERED else 'Helvetica', 11)
    c.drawString(MARGIN, PAGE_H - 2.2 * cm, 'tawatur.sa')

    # ── Certificate type title ─────────────────────────────────────────────────
    c.setFillColor(TEXT_DARK)
    c.setFont(_ARABIC_FONT_BOLD if _FONT_REGISTERED else 'Helvetica-Bold', 18)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 5 * cm, _ar(cert_type_label))

    # ── Certificate number badge ───────────────────────────────────────────────
    badge_y = PAGE_H - 6.2 * cm
    c.setFillColor(LIGHT_BLUE)
    c.roundRect(MARGIN, badge_y - 0.3 * cm, PAGE_W - 2 * MARGIN, 1 * cm,
                radius=5, fill=True, stroke=False)
    c.setFillColor(NAVY)
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(PAGE_W / 2, badge_y + 0.1 * cm, cert_number)

    # ── Divider ───────────────────────────────────────────────────────────────
    divider_y = PAGE_H - 7.5 * cm
    c.setStrokeColor(BORDER)
    c.line(MARGIN, divider_y, PAGE_W - MARGIN, divider_y)

    # ── Product details (right-aligned, Arabic labels) ─────────────────────────
    details_y = divider_y - 0.8 * cm
    font_regular = _ARABIC_FONT if _FONT_REGISTERED else 'Helvetica'
    font_bold = _ARABIC_FONT_BOLD if _FONT_REGISTERED else 'Helvetica-Bold'

    def draw_row(label_ar: str, value: str, y: float):
        """Draw a label/value pair — label right-aligned, value left-aligned."""
        c.setFont(font_bold, 11)
        c.setFillColor(SUBTEXT)
        c.drawRightString(PAGE_W - MARGIN, y, _ar(label_ar))
        c.setFont(font_regular, 11)
        c.setFillColor(TEXT_DARK)
        # Values like model/brand names stay left-aligned (they may be Latin)
        c.drawString(MARGIN, y, str(value))
        return y - 0.75 * cm

    y = details_y
    y = draw_row('الفئة', product.get_category_display(), y)
    y = draw_row('الماركة', product.brand, y)
    y = draw_row('الموديل', product.model, y)
    y = draw_row('الحالة', product.get_condition_display(), y)

    if transaction:
        y = draw_row('نوع المعاملة', transaction.get_transaction_type_display(), y)
        if transaction.price:
            y = draw_row('قيمة المعاملة', f'{transaction.price} ريال', y)
        y = draw_row('تاريخ المعاملة',
                     transaction.approved_at.strftime('%Y-%m-%d %H:%M') if transaction.approved_at else '—',
                     y)

    # Trust score row with colour coding
    trust_labels = {'excellent': 'ممتاز', 'high': 'عالٍ', 'medium': 'متوسط', 'low': 'منخفض'}
    trust_display = trust_labels.get(product.trust_level, product.trust_level)
    c.setFont(font_bold, 11)
    c.setFillColor(SUBTEXT)
    c.drawRightString(PAGE_W - MARGIN, y, _ar('درجة الثقة'))
    c.setFont(font_bold, 11)
    c.setFillColor(SUCCESS if product.trust_score >= 65 else colors.orange)
    c.drawString(MARGIN, y, f'{product.trust_score}/100 — {trust_display}')
    y -= 0.75 * cm

    # ── QR Code ───────────────────────────────────────────────────────────────
    qr_size = 3.5 * cm
    qr_x = (PAGE_W - qr_size) / 2
    qr_y = y - qr_size - 0.5 * cm

    full_qr_path = Path(settings.MEDIA_ROOT) / qr_path
    if full_qr_path.exists():
        c.drawImage(str(full_qr_path), qr_x, qr_y, width=qr_size, height=qr_size)

    # ── Verification URL ──────────────────────────────────────────────────────
    c.setFont('Helvetica', 9)
    c.setFillColor(SUBTEXT)
    c.drawCentredString(PAGE_W / 2, qr_y - 0.5 * cm, verification_url)

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_y = 1.8 * cm
    c.setStrokeColor(BORDER)
    c.line(MARGIN, footer_y + 0.8 * cm, PAGE_W - MARGIN, footer_y + 0.8 * cm)

    issued_str = timezone.now().strftime('%Y-%m-%d %H:%M')
    c.setFont(font_regular, 9)
    c.setFillColor(SUBTEXT)
    c.drawRightString(PAGE_W - MARGIN, footer_y,
                      _ar(f'تاريخ الإصدار: {issued_str}'))
    c.drawString(MARGIN, footer_y, 'Issued by Tawatur Platform | tawatur.sa')

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
