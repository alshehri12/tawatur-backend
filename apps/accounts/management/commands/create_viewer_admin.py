"""
Management command: create_viewer_admin

Creates a read-only admin account (مراقب) that can log into /admin/
and view all data but cannot add, change, or delete anything.

Usage:
    python manage.py create_viewer_admin --password <password>

The command is idempotent — running it again resets the password and
refreshes the group permissions without creating duplicates.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission, Group


class Command(BaseCommand):
    help = 'Creates a read-only admin viewer account (مراقب).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            required=True,
            help='Password the viewer will use to log into /admin/',
        )

    def handle(self, *args, **options):
        from apps.accounts.models import User

        password  = options['password']
        LOGIN_KEY = 'viewer-admin'   # used as the phone_hash to log in

        # ── 1. Build / refresh the مراقب group ───────────────────────────────
        group, _ = Group.objects.get_or_create(name='مراقب')
        view_perms = Permission.objects.filter(codename__startswith='view_')
        group.permissions.set(view_perms)
        self.stdout.write(f'  مجموعة "مراقب": {view_perms.count()} صلاحية عرض فقط')

        # ── 2. Create or update the viewer user ───────────────────────────────
        user, created = User.objects.get_or_create(
            phone_hash=LOGIN_KEY,
            defaults={
                'phone_number_encrypted': '',   # no real phone for this admin account
                'user_type': User.INDIVIDUAL,
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
            },
        )
        user.set_password(password)
        user.is_staff     = True
        user.is_superuser = False
        user.groups.set([group])
        user.save()

        action = 'تم إنشاء' if created else 'تم تحديث'
        self.stdout.write(self.style.SUCCESS(
            f'\n{action} حساب المراقب بنجاح:\n'
            f'  حقل تسجيل الدخول (Phone Hash): {LOGIN_KEY}\n'
            f'  كلمة المرور: {password}\n'
            f'  الصلاحيات: عرض فقط — لا يمكن الإضافة أو التعديل أو الحذف\n'
            f'\nرابط لوحة الإدارة: http://localhost:8000/admin/'
        ))
