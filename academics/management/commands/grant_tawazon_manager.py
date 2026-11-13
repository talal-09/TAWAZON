from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


MANAGER_PERMISSIONS = {
    ('academics', 'add_course'),
    ('academics', 'change_course'),
    ('academics', 'delete_course'),
    ('academics', 'view_course'),
    ('academics', 'add_academicterm'),
    ('optimizer', 'add_optimizationrun'),
    ('optimizer', 'view_optimizationrun'),
}


class Command(BaseCommand):
    help = 'Grant an existing user the limited TAWAZON management permissions.'

    def add_arguments(self, parser):
        parser.add_argument('username', help='Existing account username')

    @transaction.atomic
    def handle(self, *args, **options):
        username = options['username']
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f'User {username!r} does not exist. Register first.')

        permissions = list(Permission.objects.filter(
            content_type__app_label__in={'academics', 'optimizer'},
            codename__in={code for _, code in MANAGER_PERMISSIONS},
        ).select_related('content_type'))
        granted = {(item.content_type.app_label, item.codename) for item in permissions}
        if granted != MANAGER_PERMISSIONS:
            raise CommandError('Required permissions are missing. Run migrate first.')

        user.is_staff = True
        user.save(update_fields=['is_staff'])
        user.user_permissions.add(*permissions)
        self.stdout.write(self.style.SUCCESS(f'Granted TAWAZON manager permissions to {username}.'))
