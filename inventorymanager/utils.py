# utils.py
from decimal import Decimal

from django.db.models import Sum, F, Q
from datetime import datetime, time, date, timedelta
from .models import OrderItem, Order
from django.contrib.auth import get_user_model
from calendar import monthrange
from dateutil.relativedelta import relativedelta

from django.utils import timezone

def calculate_technician_salary(user, start_date=None, end_date=None):

    if start_date is None:
        start_date = datetime.now().replace(day=1, hour=0, minute=0, second=0)
    if end_date is None:
        end_date = datetime.now().replace(day=30, hour=23, minute=59, second=59)

    service_percent = 40

    # Считаем только завершённые заказы техника
    services_total = OrderItem.objects.filter(
        order__employee=user,
        order__status='issued',
        order__completed_at__gte=start_date,
        order__completed_at__lte=end_date,
        product__product_type='service'
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




def make_aware(dt):
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)

    return dt


def get_period_range(period_type: str, selected_date: str | None):
    """
    Возвращает:
    start_date - включительно
    end_date   - НЕ включительно

    Поэтому в запросах используем:
    completed_at__gte=start_date
    completed_at__lt=end_date
    """

    if selected_date:
        if period_type == "week":
            current = datetime.strptime(selected_date, "%Y-%m-%d").date()

        elif period_type == "month":
            current = datetime.strptime(selected_date, "%Y-%m").date()

        elif period_type == "quarter":
            year, quarter = selected_date.split("-Q")

            current = date(
                int(year),
                (int(quarter) - 1) * 3 + 1,
                1
            )

        else:  # year
            current = datetime.strptime(selected_date, "%Y").date()

    else:
        current = timezone.localdate()

    # ---------------- WEEK ----------------

    if period_type == "week":

        start = current - timedelta(days=current.weekday())
        end = start + timedelta(days=7)

    # ---------------- MONTH ----------------

    elif period_type == "month":

        start = current.replace(day=1)

        if current.month == 12:
            end = current.replace(
                year=current.year + 1,
                month=1,
                day=1
            )
        else:
            end = current.replace(
                month=current.month + 1,
                day=1
            )

    # ---------------- QUARTER ----------------

    elif period_type == "quarter":

        quarter = (current.month - 1) // 3 + 1

        start_month = (quarter - 1) * 3 + 1

        start = current.replace(
            month=start_month,
            day=1
        )

        end = start + relativedelta(months=3)

    # ---------------- YEAR ----------------

    else:

        start = current.replace(
            month=1,
            day=1
        )

        end = current.replace(
            year=current.year + 1,
            month=1,
            day=1
        )

    start_dt = make_aware(
        datetime.combine(start, time.min)
    )

    end_dt = make_aware(
        datetime.combine(end, time.min)
    )

    return start_dt, end_dt

def get_services_total(queryset):
    return (
        queryset.aggregate(
            total=Sum(F('quantity') * F('unit_price'))
        )['total']
        or 0
    )

def calculate_formset_totals(formset):
    services_total = Decimal("0.00")
    parts_total = Decimal("0.00")

    for item_form in formset:
        if not item_form.cleaned_data or item_form.cleaned_data.get("DELETE"):
            continue

        product = item_form.cleaned_data["product"]
        quantity = item_form.cleaned_data["quantity"]

        subtotal = product.unit_cost * quantity

        if product.product_type == "service":
            services_total += Decimal(subtotal)
        else:
            parts_total += Decimal(subtotal)

    return services_total, parts_total