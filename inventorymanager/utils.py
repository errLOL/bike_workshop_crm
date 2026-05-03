# utils.py
from decimal import Decimal

from django.db.models import Sum, F, Q
from datetime import datetime, timedelta
from .models import OrderItem, Order
from django.contrib.auth import get_user_model


def calculate_technician_salary(user, start_date=None, end_date=None):
    """
    Рассчитывает зарплату техника за период
    - 40% от стоимости услуг (не запчастей)
    - Запчасти не учитываются
    """

    if start_date is None:
        start_date = datetime.now().replace(day=1, hour=0, minute=0, second=0)
    if end_date is None:
        end_date = datetime.now().replace(day=30, hour=23, minute=59, second=59)

    # Получаем процент техника (по умолчанию 40%)
    service_percent = 40

    # Считаем только завершённые заказы техника
    services_total = OrderItem.objects.filter(
        order__employee=user,
        order__status='issued',
        order__created_at__gte=start_date,
        order__created_at__lte=end_date,
        product__product_type='service'  # только услуги!
    ).aggregate(
        total=Sum(F('quantity') * F('unit_price'))
    )['total'] or 0

    # Зарплата = процент от услуг
    salary = services_total * Decimal(service_percent / 100)

    return {
        'services_total': services_total,
        'salary': salary,
        'percent': service_percent,
        'start_date': start_date,
        'end_date': end_date,
    }


def calculate_all_technicians_salary(start_date=None, end_date=None):
    """Рассчитывает зарплату всех техников за период"""

    User = get_user_model()

    technicians = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Technician')
    ).distinct()

    results = []
    for tech in technicians:
        results.append({
            'user': tech,
            **calculate_technician_salary(tech, start_date, end_date)
        })

    return results