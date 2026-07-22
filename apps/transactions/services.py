"""
Transaction business logic service.

TransactionService handles the full ownership transfer lifecycle:
  create()   → initiator (current owner) sends a transfer request to recipient.
  approve()  → recipient accepts → ownership is transferred immediately.
  reject()   → recipient declines → no ownership change.
  cancel()   → initiator withdraws the request before recipient acts.
  expire()   → called by Celery beat to mark stale pending transactions.
"""

from datetime import timedelta
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import Transaction, AuditLog


class TransactionService:

    # ── Registered purchase (buyer-initiated, product created inline) ─────────

    @staticmethod
    @db_transaction.atomic
    def create_registered_purchase(
        buyer,
        product_data: dict,
        seller_full_name: str,
        seller_id_number: str,
        seller_mobile: str,
        seller_city: str,
        price=None,
        seller_terms: str = '',
        notes: str = '',
    ) -> Transaction:
        """
        Single-step flow: register the device the buyer just bought AND
        document the purchase, in one atomic call — replaces the old two-step
        "register a product" then "document a purchase" flows.

        The buyer enters the seller's info exactly as before (the seller
        doesn't need a platform account). Unlike the old direct-purchase
        flow, the transaction is created PENDING, not auto-approved — the
        buyer shares the confirmation link (Transaction.link_token) with the
        seller, who reviews the deal and accepts/rejects it via
        confirm_by_seller() / reject_by_seller() below. No certificate is
        generated until the seller confirms.
        """
        from core.encryption import encrypt
        from core.hashing import hash_value, hash_phone
        from apps.products.services import ProductRegistrationService

        product = ProductRegistrationService.register(buyer, product_data)

        now = timezone.now()

        txn = Transaction.objects.create(
            product=product,
            initiator=buyer,
            recipient=None,
            transaction_type=Transaction.DIRECT_PURCHASE,
            price=price,
            device_condition=product_data.get('condition', ''),
            seller_terms=seller_terms,
            notes=notes,
            seller_full_name=seller_full_name,
            seller_id_number_encrypted=encrypt(seller_id_number),
            seller_id_number_hash=hash_value(seller_id_number),
            seller_mobile_encrypted=encrypt(seller_mobile),
            seller_mobile_hash=hash_phone(seller_mobile),
            seller_city=seller_city,
            status=Transaction.PENDING,
            expires_at=now + timedelta(hours=48),
        )

        AuditLog.objects.create(
            transaction=txn,
            actor=buyer,
            action='registered_purchase_submitted',
            old_status='',
            new_status=Transaction.PENDING,
        )

        return txn

    # ── Seller confirms / rejects via the public link (no account needed) ─────

    @staticmethod
    def _schedule_certificate(txn_id: str):
        def _generate_cert_after_commit():
            import threading

            def _bg():
                try:
                    from apps.certificates.tasks import generate_transfer_certificate_task
                    generate_transfer_certificate_task.delay(txn_id)
                    return
                except Exception:
                    pass
                try:
                    from apps.certificates.services import CertificateService
                    from apps.transactions.models import Transaction as _T
                    t = _T.objects.select_related('product', 'initiator').get(id=txn_id)
                    CertificateService.generate_transfer_certificate(t)
                except Exception:
                    pass

            threading.Thread(target=_bg, daemon=True).start()

        db_transaction.on_commit(_generate_cert_after_commit)

    @staticmethod
    @db_transaction.atomic
    def confirm_by_seller(txn: Transaction) -> Transaction:
        """
        The seller reviews the deal (via the public link) and confirms it.
        No login required — the seller doesn't need a platform account.
        """
        if txn.status != Transaction.PENDING:
            raise ValueError('هذه العملية ليست بانتظار الموافقة.')

        if txn.expires_at < timezone.now():
            txn.status = Transaction.EXPIRED
            txn.save(update_fields=['status', 'updated_at'])
            raise ValueError('انتهت صلاحية رابط التأكيد. اطلب من المشتري إنشاء عملية جديدة.')

        now = timezone.now()
        txn.status = Transaction.APPROVED
        txn.approved_at = now
        txn.save(update_fields=['status', 'approved_at', 'updated_at'])

        # AuditLog.actor is a required FK and the seller has no platform
        # account — attribute the log entry to the buyer/initiator, the
        # action name makes clear it was actually the seller who acted.
        AuditLog.objects.create(
            transaction=txn,
            actor=txn.initiator,
            action='seller_confirmed_via_link',
            old_status=Transaction.PENDING,
            new_status=Transaction.APPROVED,
        )

        from apps.products.services import TrustScoreService
        TrustScoreService.calculate(txn.product)

        TransactionService._schedule_certificate(str(txn.id))

        return txn

    @staticmethod
    @db_transaction.atomic
    def reject_by_seller(txn: Transaction) -> Transaction:
        """The seller disputes the deal via the public link — no ownership change."""
        if txn.status != Transaction.PENDING:
            raise ValueError('هذه العملية ليست بانتظار الموافقة.')

        txn.status = Transaction.REJECTED
        txn.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            transaction=txn,
            actor=txn.initiator,
            action='seller_rejected_via_link',
            old_status=Transaction.PENDING,
            new_status=Transaction.REJECTED,
        )

        return txn

    # ── Direct purchase (buyer-initiated) ────────────────────────────────────

    @staticmethod
    @db_transaction.atomic
    def create_direct_purchase(
        buyer,
        product_id: str,
        seller_full_name: str,
        seller_id_number: str,
        seller_mobile: str,
        seller_city: str,
        price=None,
        device_condition: str = '',
        seller_terms: str = '',
        notes: str = '',
    ) -> Transaction:
        """
        Record a completed direct purchase:
          - Buyer must be the registered owner of the product.
          - Seller info (name, ID, mobile, city) is entered by the buyer.
          - Transaction is immediately APPROVED — no link or approval step.
          - A certificate is generated automatically.
        """
        from core.encryption import encrypt
        from core.hashing import hash_value, hash_phone
        from apps.products.models import Product, OwnershipRecord

        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            raise ValueError('المنتج غير موجود أو غير نشط.')

        if not OwnershipRecord.objects.filter(
            product=product, owner=buyer, is_current=True
        ).exists():
            raise ValueError('لا يمكنك توثيق شراء منتج لا تمتلكه.')

        if Transaction.objects.filter(
            product=product, status=Transaction.PENDING
        ).exists():
            raise ValueError('يوجد معاملة معلّقة لهذا المنتج، أكملها أو ألغِها أولاً.')

        now = timezone.now()

        txn = Transaction.objects.create(
            product=product,
            initiator=buyer,
            recipient=None,
            transaction_type=Transaction.DIRECT_PURCHASE,
            price=price,
            device_condition=device_condition,
            seller_terms=seller_terms,
            notes=notes,
            seller_full_name=seller_full_name,
            seller_id_number_encrypted=encrypt(seller_id_number),
            seller_id_number_hash=hash_value(seller_id_number),
            seller_mobile_encrypted=encrypt(seller_mobile),
            seller_mobile_hash=hash_phone(seller_mobile),
            seller_city=seller_city,
            status=Transaction.APPROVED,
            expires_at=now + timedelta(hours=48),
            approved_at=now,
        )

        AuditLog.objects.create(
            transaction=txn,
            actor=buyer,
            action='direct_purchase_completed',
            old_status='',
            new_status=Transaction.APPROVED,
        )

        # Schedule certificate generation AFTER the DB commit so it never
        # blocks the HTTP response. A daemon thread handles the actual work.
        _txn_id = str(txn.id)

        def _generate_cert_after_commit():
            import threading

            def _bg():
                try:
                    from apps.certificates.tasks import generate_transfer_certificate_task
                    generate_transfer_certificate_task.delay(_txn_id)
                    return
                except Exception:
                    pass
                try:
                    from apps.certificates.services import CertificateService
                    from apps.transactions.models import Transaction as _T
                    t = _T.objects.select_related('product', 'initiator').get(id=_txn_id)
                    CertificateService.generate_transfer_certificate(t)
                except Exception:
                    pass

            threading.Thread(target=_bg, daemon=True).start()

        db_transaction.on_commit(_generate_cert_after_commit)

        return txn

    # ── Approve ───────────────────────────────────────────────────────────────

    @staticmethod
    @db_transaction.atomic
    def approve(txn: Transaction, actor) -> Transaction:
        """
        Recipient approves the transfer.

        On approval:
          1. Closes the initiator's current OwnershipRecord (sets end_date).
          2. Opens a new OwnershipRecord for the recipient.
          3. Marks the transaction APPROVED.
          4. Recalculates the product's trust score.
        """
        from apps.products.models import OwnershipRecord
        from apps.products.services import TrustScoreService

        if actor != txn.recipient:
            raise ValueError('فقط المُحوَّل إليه يمكنه قبول المعاملة.')

        if txn.status != Transaction.PENDING:
            raise ValueError('لا يمكن قبول معاملة بحالة غير "انتظار".')

        # Auto-expire and reject if link has timed out
        if txn.expires_at < timezone.now():
            txn.status = Transaction.EXPIRED
            txn.save(update_fields=['status', 'updated_at'])
            AuditLog.objects.create(
                transaction=txn, actor=actor,
                action='auto_expired', old_status=Transaction.PENDING,
                new_status=Transaction.EXPIRED,
            )
            raise ValueError('انتهت صلاحية رابط المعاملة (48 ساعة). أطلب من البائع إنشاء رابط جديد.')

        # ── Transfer ownership ────────────────────────────────────────────────
        now = timezone.now()

        # Close the seller's ownership record
        OwnershipRecord.objects.filter(
            product=txn.product, is_current=True
        ).update(end_date=now, is_current=False)

        # Map transaction type → ownership transfer type label
        transfer_type = {
            Transaction.INDIVIDUAL_TO_INDIVIDUAL: OwnershipRecord.PURCHASE,
            Transaction.BUSINESS_PURCHASE: OwnershipRecord.PURCHASE,
            Transaction.BUSINESS_SALE: OwnershipRecord.PURCHASE,
        }.get(txn.transaction_type, OwnershipRecord.PURCHASE)

        # Open new ownership record for the buyer
        OwnershipRecord.objects.create(
            product=txn.product,
            owner=txn.recipient,
            transfer_type=transfer_type,
            is_current=True,
            transaction=txn,
        )

        # Update transaction
        txn.status = Transaction.APPROVED
        txn.approved_at = now
        txn.save(update_fields=['status', 'approved_at', 'updated_at'])

        AuditLog.objects.create(
            transaction=txn, actor=actor,
            action='approved',
            old_status=Transaction.PENDING,
            new_status=Transaction.APPROVED,
        )

        # Recalculate trust score now that chain has a new verified link
        TrustScoreService.calculate(txn.product)

        # Generate Ownership Transfer Certificate (async if Celery is available)
        try:
            from apps.certificates.tasks import generate_transfer_certificate_task
            generate_transfer_certificate_task.delay(str(txn.id))
        except Exception:
            # Celery not running — generate synchronously so the certificate
            # is always produced regardless of task queue availability.
            try:
                from apps.certificates.services import CertificateService
                CertificateService.generate_transfer_certificate(txn)
            except Exception:
                pass  # Never let certificate failure roll back the ownership transfer

        return txn

    # ── Reject ────────────────────────────────────────────────────────────────

    @staticmethod
    @db_transaction.atomic
    def reject(txn: Transaction, actor) -> Transaction:
        """Recipient declines — no ownership change occurs."""
        if actor != txn.recipient:
            raise ValueError('فقط المُحوَّل إليه يمكنه رفض المعاملة.')

        if txn.status != Transaction.PENDING:
            raise ValueError('لا يمكن رفض معاملة بحالة غير "انتظار".')

        txn.status = Transaction.REJECTED
        txn.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            transaction=txn, actor=actor,
            action='rejected',
            old_status=Transaction.PENDING,
            new_status=Transaction.REJECTED,
        )

        return txn

    # ── Cancel ────────────────────────────────────────────────────────────────

    @staticmethod
    @db_transaction.atomic
    def cancel(txn: Transaction, actor) -> Transaction:
        """Initiator withdraws the request before the recipient acts."""
        if actor != txn.initiator:
            raise ValueError('فقط منشئ المعاملة يمكنه إلغاءها.')

        if txn.status != Transaction.PENDING:
            raise ValueError('يمكن إلغاء المعاملات في حالة الانتظار فقط.')

        txn.status = Transaction.CANCELLED
        txn.save(update_fields=['status', 'updated_at'])

        AuditLog.objects.create(
            transaction=txn, actor=actor,
            action='cancelled',
            old_status=Transaction.PENDING,
            new_status=Transaction.CANCELLED,
        )

        return txn

    # ── Bulk expire (called by Celery beat) ───────────────────────────────────

    @staticmethod
    def expire_stale() -> int:
        """
        Mark all pending transactions past their expiry date as EXPIRED.
        Returns the number of transactions expired.
        Called periodically by the Celery beat task in tasks.py.
        """
        stale = Transaction.objects.filter(
            status=Transaction.PENDING,
            expires_at__lt=timezone.now(),
        )
        count = stale.count()
        stale.update(status=Transaction.EXPIRED)
        return count
