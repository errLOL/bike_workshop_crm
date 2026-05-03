from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.contrib.auth.models import Group, Permission

from inventorymanager.models import Order, Product


class Command(BaseCommand):
    help = "Create admin and technician groups"

    def handle(self, *args, **options):
        technical_group, created = Group.objects.get_or_create(name="Technician")
        admin_group, created = Group.objects.get_or_create(name="Admin")

        order_ct = ContentType.objects.get_for_model(Order)
        technician_permissions = [
            Permission.objects.get(codename="add_order", content_type=order_ct),
            Permission.objects.get(codename="view_order", content_type=order_ct),
        ]
        technical_group.permissions.set(technician_permissions)

        admin_permissions = Permission.objects.filter(
            content_type__in=[order_ct, ContentType.objects.get_for_model(Product)]
        )
        admin_group.permissions.set(admin_permissions)

        self.stdout.write(self.style.SUCCESS("Groups was created"))