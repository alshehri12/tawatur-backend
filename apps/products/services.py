"""
Business logic services for the products domain.

  - ProductRegistrationService : creates a Product + initial OwnershipRecord
                                  and triggers duplicate-detection fraud checks.
  - TrustScoreService          : calculates and persists trust score + level.
"""

from django.db import transaction as db_transaction


class TrustScoreService:
    """
    Calculates a product's trust score based on ownership chain quality.

    Score formula (max 100):
      Base                                     : 50
      Per verified transfer (capped at 3)      : +10 each
      Ownership chain integrity = 100%         : +10
      Per active fraud alert on the product    : -20
      Max score                                : 100
      Min score                                : 0

    Levels: Excellent (85-100) / High (65-84) / Medium (40-64) / Low (<40)
    """

    LEVEL_MAP = [
        (85, 'excellent'),
        (65, 'high'),
        (40, 'medium'),
        (0, 'low'),
    ]

    @classmethod
    def calculate(cls, product) -> tuple:
        """
        Recalculate and persist the trust score for the given product.
        Returns (score: int, level: str).
        """
        from apps.fraud.models import FraudAlert

        score = 50  # base score every product starts with

        # Count ownership records belonging to identity-verified users
        records = product.ownership_records.select_related('owner').all()
        verified_count = min(
            records.filter(owner__identity_submitted=True).count(),
            3,  # cap bonus at 3 transfers = +30 max
        )
        score += verified_count * 10

        # Bonus for a fully documented ownership chain
        if product.chain_integrity == 100:
            score += 10

        # Penalty for each open fraud alert on this product
        open_alerts = FraudAlert.objects.filter(
            product=product,
            status=FraudAlert.OPEN,
        ).count()
        score -= open_alerts * 20

        # Clamp to valid range
        score = max(0, min(100, score))

        # Map score to human-readable level
        level = 'low'
        for threshold, label in cls.LEVEL_MAP:
            if score >= threshold:
                level = label
                break

        product.trust_score = score
        product.trust_level = level
        product.save(update_fields=['trust_score', 'trust_level'])

        return score, level


class ProductRegistrationService:
    """
    Handles the full product registration flow in a single atomic operation:
      1. Encrypt and hash IMEI / serial number.
      2. Check for duplicates → create FraudAlert if any found.
      3. Create the Product record.
      4. Create the initial OwnershipRecord (transfer_type='initial').
      5. Calculate the initial trust score.
    """

    @staticmethod
    @db_transaction.atomic
    def register(user, validated_data: dict):
        """
        Create and return a new Product owned by user.
        validated_data keys: category, brand, model, condition,
                             imei_1?, imei_2?, serial_number?, notes?
        """
        from core.encryption import encrypt
        from core.hashing import hash_value
        from apps.fraud.models import FraudAlert
        from .models import Product, OwnershipRecord

        imei_1 = validated_data.get('imei_1') or ''
        imei_2 = validated_data.get('imei_2') or ''
        serial = validated_data.get('serial_number') or ''

        # ── Duplicate-detection before creating the product ───────────────────
        fraud_events = []  # collect (alert_type, severity, description) tuples

        if imei_1:
            imei_1_hash = hash_value(imei_1)
            # Check both IMEI slots of all existing active products
            duplicate_exists = (
                Product.objects.filter(imei_1_hash=imei_1_hash, is_active=True).exists()
                or Product.objects.filter(imei_2_hash=imei_1_hash, is_active=True).exists()
            )
            if duplicate_exists:
                fraud_events.append((
                    FraudAlert.DUPLICATE_IMEI, FraudAlert.HIGH,
                    f'محاولة تسجيل IMEI مكرر (أول 6 أرقام: {imei_1[:6]}XXXXXX).',
                ))

        if imei_2:
            imei_2_hash = hash_value(imei_2)
            duplicate_exists = (
                Product.objects.filter(imei_1_hash=imei_2_hash, is_active=True).exists()
                or Product.objects.filter(imei_2_hash=imei_2_hash, is_active=True).exists()
            )
            if duplicate_exists:
                fraud_events.append((
                    FraudAlert.DUPLICATE_IMEI, FraudAlert.HIGH,
                    f'محاولة تسجيل IMEI مكرر (خانة SIM 2).',
                ))

        if serial:
            serial_hash = hash_value(serial)
            if Product.objects.filter(serial_hash=serial_hash, is_active=True).exists():
                fraud_events.append((
                    FraudAlert.DUPLICATE_SERIAL, FraudAlert.MEDIUM,
                    f'محاولة تسجيل رقم تسلسلي مكرر.',
                ))

        # ── Create the Product ────────────────────────────────────────────────
        product = Product.objects.create(
            category=validated_data['category'],
            brand=validated_data['brand'],
            model=validated_data['model'],
            condition=validated_data['condition'],
            notes=validated_data.get('notes', ''),
            registered_by=user,
            # Encrypted values (empty string when not provided)
            imei_1_encrypted=encrypt(imei_1) if imei_1 else '',
            imei_2_encrypted=encrypt(imei_2) if imei_2 else '',
            serial_encrypted=encrypt(serial) if serial else '',
            # Hash indexes (None when not provided — allows NULL uniqueness)
            imei_1_hash=hash_value(imei_1) if imei_1 else None,
            imei_2_hash=hash_value(imei_2) if imei_2 else None,
            serial_hash=hash_value(serial) if serial else None,
        )

        # ── Create initial ownership record ───────────────────────────────────
        OwnershipRecord.objects.create(
            product=product,
            owner=user,
            transfer_type=OwnershipRecord.INITIAL,
            is_current=True,
        )

        # ── Persist any fraud alerts ──────────────────────────────────────────
        for alert_type, severity, description in fraud_events:
            FraudAlert.objects.create(
                alert_type=alert_type,
                severity=severity,
                product=product,
                user=user,
                description=description,
            )

        # ── Calculate initial trust score ─────────────────────────────────────
        TrustScoreService.calculate(product)

        return product
