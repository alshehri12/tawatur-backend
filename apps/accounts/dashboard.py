from django.db.models import Q


def dashboard_callback(request, context):
    from apps.accounts.models import User
    from apps.products.models import Product
    from apps.transactions.models import Transaction
    from apps.certificates.models import Certificate
    from apps.fraud.models import FraudAlert

    users_total      = User.objects.count()
    users_individual = User.objects.filter(user_type='individual').count()
    users_business   = User.objects.filter(user_type='business').count()
    verified_users   = User.objects.filter(
        Q(absher_verified=True) | Q(wathiq_verified=True)
    ).count()

    context.update({
        "stat_users_total":           users_total,
        "stat_users_individual":      users_individual,
        "stat_users_business":        users_business,
        "stat_verified_users":        verified_users,
        "stat_products":              Product.objects.filter(is_active=True).count(),
        "stat_pending_transactions":  Transaction.objects.filter(status='pending').count(),
        "stat_approved_transactions": Transaction.objects.filter(status='approved').count(),
        "stat_valid_certificates":    Certificate.objects.filter(is_valid=True).count(),
        "stat_open_alerts":           FraudAlert.objects.filter(status='open').count(),
        "stat_critical_alerts":       FraudAlert.objects.filter(
                                          severity='critical', status='open'
                                      ).count(),
        "recent_alerts":       FraudAlert.objects.filter(status='open')
                                         .order_by('-created_at')[:5],
        "recent_transactions": Transaction.objects.select_related('product')
                                          .order_by('-created_at')[:6],
    })
    return context
