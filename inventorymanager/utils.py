# utils.py
from decimal import Decimal

from django.db.models import Sum, F, Q, ExpressionWrapper, DecimalField, Value
from datetime import datetime, time, date, timedelta

from django.db.models.functions import Coalesce, Greatest

from .models import OrderItem, Order
from django.contrib.auth import get_user_model
from calendar import monthrange
from dateutil.relativedelta import relativedelta

from django.utils import timezone

def get_technician_orders_with_salary(
    technician=None,
    start_date=None,
    end_date=None,
    salary_percent=40,
):
    qs = Order.objects.filter(
        status='issued',
    )
    if technician:
        qs = Order.objects.filter(
            employee=technician,
            status='issued',
        )

    if start_date:
        qs = qs.filter(completed_at__gte=start_date)

    if end_date:
        qs = qs.filter(completed_at__lt=end_date)

    return (
        qs
        .annotate(
            total_db=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F('order_items__quantity') *
                        F('order_items__unit_price'),
                        output_field=DecimalField()
                    ),
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField()
            )
        ).annotate(
            services_total_db=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F('order_items__quantity') *
                        F('order_items__unit_price'),
                        output_field=DecimalField()
                    ),
                    filter=Q(
                        order_items__product__product_type='service'
                    )
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField()
            )
        )
        .annotate(
            services_after_discount=Greatest(
                ExpressionWrapper(
                    F("services_total_db") - F("service_discount"),
                    output_field=DecimalField()
                ),
                Value(Decimal("0.00"))
            )
        )
        .annotate(
            technician_salary=ExpressionWrapper(
                F("services_after_discount")
                * Value(Decimal(str(salary_percent)))
                / Value(Decimal("100")),
                output_field=DecimalField()
            )
        )
        .select_related(
            "customer",
            "transport",
        )
    )


def get_services_total_after_discount(
    technician=None,
    start_date=None,
    end_date=None,
):
    result = (
        get_technician_orders_with_salary(
            technician,
            start_date,
            end_date,
        )
        .aggregate(
            total=Sum("services_after_discount")
        )
    )

    return result["total"] or Decimal("0.00")


def get_salary_total(
    technician,
    start_date,
    end_date,
    salary_percent=40,
):
    result = (
        get_technician_orders_with_salary(
            technician,
            start_date,
            end_date,
            salary_percent,
        )
        .aggregate(
            total=Sum("technician_salary")
        )
    )

    return result["total"] or Decimal("0.00")


def get_completed_orders_count(
    technician,
    start_date,
    end_date,
):
    return (
        Order.objects.filter(
            employee=technician,
            status="issued",
            completed_at__gte=start_date,
            completed_at__lt=end_date,
        )
        .count()
    )


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

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

IGNORED_FIELDS = {
    'updated_at',
    'created_at',
    'id',
}

def build_changes(old_data: dict, new_data: dict, ignore: set | None = None) -> dict:
    """
    Сравнивает два словаря и возвращает словарь изменений.

    Формат:
      - обычное изменение: {'old': ..., 'new': ...}
      - добавление:        {'added': True, ...все поля нового элемента}
      - удаление:          {'deleted': True, ...все поля старого элемента}

    Для вложенных словарей (например, order_items) формирует ключи
    вида 'order_items.<product_id>.<field>' и корректно обрабатывает
    появление/исчезновение целых элементов.
    """
    ignore = ignore or IGNORED_FIELDS
    changes = {}

    def _is_leaf_dict(d):
        """Словарь считается листом, если все его значения — не dict."""
        return all(not isinstance(v, dict) for v in d.values())

    def _compare(prefix, old_val, new_val):
        # Оба — словари
        if isinstance(old_val, dict) and isinstance(new_val, dict):
            # Лист — сравниваем по полям
            if _is_leaf_dict(old_val) or _is_leaf_dict(new_val):
                all_keys = set(old_val.keys()) | set(new_val.keys())
                for k in all_keys:
                    if k in ignore:
                        continue
                    ov = old_val.get(k)
                    nv = new_val.get(k)
                    if ov != nv:
                        key = f'{prefix}.{k}' if prefix else str(k)
                        if "order_items" in prefix:
                            key = new_val.get("product_name")
                        changes[key] = {'old': ov, 'new': nv}
                return

            # Ветка (например, order_items) — рекурсивно
            all_keys = set(old_val.keys()) | set(new_val.keys())
            for k in all_keys:
                key = f'{prefix}.{k}' if prefix else str(k)
                _compare(key, old_val.get(k), new_val.get(k))
            return

        # Один из них — словарь, другой None/отсутствует → добавление/удаление
        if isinstance(old_val, dict) and new_val is None:
            changes[prefix] = {'deleted': True, **old_val}
            return
        if old_val is None and isinstance(new_val, dict):
            changes[prefix] = {'added': True, **new_val}
            return

        # Скаляры
        if old_val != new_val:
            changes[prefix] = {'old': old_val, 'new': new_val}

    all_top = set(old_data.keys()) | set(new_data.keys())
    for k in all_top:
        if k in ignore:
            continue
        _compare(str(k), old_data.get(k), new_data.get(k))

    return changes