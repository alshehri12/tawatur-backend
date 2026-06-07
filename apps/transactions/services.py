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

    # ── Create ────────────────────────────────────────────────────────────────

    @staticmethod
    @db_transaction.atomic
    def create(initiator, product_id: str, recipient_phone: str,
               transaction_type: str, price=None, notes: str = '') -> Transaction:
        """
        Open a new ownership transfer request.

        Rules enforced:
          - Initiator must be the current owner of the product.
          - Recipient must exist, be verified, and differ from the initiator.
          - No other PENDING transaction may exist for the same product.
        """
        from core.hashing import hash_phone
        from apps.accounts.models import User
        from apps.products.models import Product, OwnershipRecord

        # ── Validate product + ownership ──────────────────────────────────────
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            raise ValueError('المنتج غير موجود أو غير نشط.')

        owns_product = OwnershipRecord.objects.filter(
            product=product, owner=initiator, is_current=True
        ).exists()
        if not owns_product:
            raise ValueError('لا يمكنك تحويل منتج لا تمتلكه.')

        # ── Prevent duplicate pending transactions ────────────────────────────
        if Transaction.objects.filter(product=product, status=Transaction.PENDING).exists():
            raise ValueError('يوجد طلب تحويل نشط لهذا المنتج. أكمله أو ألغِه أولاً.')

        # ── Resolve recipient ─────────────────────────────────────────────────
        try:
            recipient = User.objects.get(phone_hash=hash_phone(recipient_phone), is_active=True)
        except User.DoesNotExist:
            raise ValueError('لا يوجد مستخدم مسجل بهذا الرقم على تواتر.')

        if recipient == initiator:
            raise ValueError('لا يمكنك تحويل المنتج إلى نفسك.')

        if not recipient.can_transact:
            raise ValueError('المستخدم المُحوَّل إليه لم يُكمل التحقق من هويته على المنصة.')

        # ── Create transaction (expires in 48 hours) ──────────────────────────
        txn = Transaction.objects.create(
            product=product,
            initiator=initiator,
            recipient=recipient,
            transaction_type=transaction_type,
            price=price,
            notes=notes,
            status=Transaction.PENDING,
            expires_at=timezone.now() + timedelta(hours=48),
        )

        # Immutable audit trail entry
        AuditLog.objects.create(
            transaction=txn,
            actor=initiator,
            action='created',
            old_status='',
            new_status=Transaction.PENDING,
        )

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
