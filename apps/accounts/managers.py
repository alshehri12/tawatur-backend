"""
Custom manager for the User model.
Handles user creation while taking care of phone hashing and encryption
so that no caller ever has to remember to do those steps manually.
"""

from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):

    def create_user(self, phone_number: str, user_type: str, **extra_fields):
        """
        Create and persist a regular user.
        Password-based auth is not used — authentication is OTP-only.
        """
        if not phone_number:
            raise ValueError('رقم الجوال مطلوب.')
        if not user_type:
            raise ValueError('نوع الحساب مطلوب.')

        from core.hashing import hash_phone, normalize_phone
        from core.encryption import encrypt

        # Normalize → hash → encrypt the phone number
        normalized = normalize_phone(phone_number)
        phone_hash = hash_phone(normalized)
        phone_encrypted = encrypt(normalized)

        user = self.model(
            phone_hash=phone_hash,
            phone_number_encrypted=phone_encrypted,
            user_type=user_type,
            **extra_fields,
        )
        # No password — OTP is the only login method for regular users
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number: str, user_type: str = 'individual',
                         password: str = None, **extra_fields):
        """
        Create a superuser who can access the Django admin.
        Superusers get a real password so they can log in via the admin UI.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        # Auto-mark superusers as verified so they can transact in tests
        extra_fields.setdefault('identity_submitted', True)
        extra_fields.setdefault('absher_verified', True)

        user = self.create_user(phone_number, user_type, **extra_fields)

        if password:
            user.set_password(password)
            user.save(using=self._db)

        return user
