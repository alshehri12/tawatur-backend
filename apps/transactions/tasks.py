"""
Celery tasks for the transactions app.

expire_pending_transactions:
  Runs every 30 minutes via django-celery-beat.
  Marks all PENDING transactions past their expires_at as EXPIRED.
  This keeps the database clean and prevents stale links from ever being acted on.
"""

from config.celery import app
from .services import TransactionService


@app.task(name='transactions.expire_pending')
def expire_pending_transactions():
    """Batch-expire stale pending transactions. Returns the count expired."""
    count = TransactionService.expire_stale()
    return f'{count} معاملة منتهية الصلاحية تم تحديثها.'
