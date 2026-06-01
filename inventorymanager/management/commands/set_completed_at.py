
from django.core.management import BaseCommand
from django.utils import timezone

from inventorymanager.models import Order


class Command(BaseCommand):
    help = "Set completed_at field for issued orders"

    def handle(self, *args, **options):
        orders = Order.objects.filter(status="issued")
        for order in orders:
            order.completed_at = timezone.make_aware(order.updated_at)
        Order.objects.bulk_update(orders, fields=["completed_at"])