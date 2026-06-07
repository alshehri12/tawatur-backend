"""
Celery task for async certificate generation.
Called from TransactionService.approve() after ownership transfer.
"""

from config.celery import app


@app.task(name='certificates.generate_transfer_certificate', bind=True, max_retries=3)
def generate_transfer_certificate_task(self, transaction_id: str):
    """
    Async task: generate the Ownership Transfer Certificate for an approved transaction.
    Retries up to 3 times on failure (e.g. temporary file-system issue).
    """
    try:
        from apps.transactions.models import Transaction
        from apps.certificates.services import CertificateService

        txn = Transaction.objects.get(id=transaction_id)
        CertificateService.generate_transfer_certificate(txn)
    except Exception as exc:
        # Retry with exponential backoff: 60s, 120s, 240s
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
