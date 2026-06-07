"""
Custom DRF permission classes for the accounts domain.
"""

from rest_framework.permissions import BasePermission


class IsVerifiedUser(BasePermission):
    """
    Grants access only to users who have completed identity verification
    (identity_submitted for individuals / cr_submitted for businesses).

    This permission is required for any endpoint that creates or approves
    transactions (Phase 2+). It is intentionally not applied to auth endpoints.
    """
    message = 'يجب إكمال التحقق من هويتك للقيام بهذه العملية.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.can_transact
        )


class IsIndividualUser(BasePermission):
    """Grants access only to individual (non-business) accounts."""
    message = 'هذه الخاصية متاحة للأفراد فقط.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'individual'
        )


class IsBusinessUser(BasePermission):
    """Grants access only to verified business accounts."""
    message = 'هذه الخاصية متاحة للجهات التجارية فقط.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == 'business'
        )
