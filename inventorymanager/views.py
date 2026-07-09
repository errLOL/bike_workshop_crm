from calendar import monthrange
from datetime import timedelta, datetime, date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout, get_user
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import inlineformset_factory
from django.views.decorators.http import require_http_methods

from .decorators import require_order_access, require_admin
from .models import Order, OrderItem
from .forms import *
from django.db.models import Sum, F, Q, Count, Avg, ExpressionWrapper, DecimalField
import json

from .utils import calculate_all_technicians_salary, calculate_technician_salary, get_period_range, get_services_total, \
    calculate_formset_totals


def log_action(request, action_type, model_name, object_id, object_repr, changes=None):
    """Простая функция для логирования действий"""
    ActionLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action_type=action_type,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr,
        ip_address=get_client_ip(request),
        changes=changes or {}
    )

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@require_admin
def admin_dashboard(request):
    # Authenticated users view the Dashboard

    months_ru = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }

    if request.user.is_authenticated:
        low_stock = Product.objects.filter(quantity_in_stock__lte=1, product_type='part')

        orders_total = OrderItem.objects.annotate(
            total_price=F("quantity") * F("unit_price")
        ).aggregate(sum_total=Sum("total_price"))["sum_total"]

        product_total_cost = OrderItem.objects.annotate(
            cost_calculation=F("quantity") * F("product__unit_cost")
        ).aggregate(total_cost_sum=Sum("cost_calculation"))["total_cost_sum"]

        net_revenue = float(orders_total) - float(product_total_cost)
        # Sales chart
        sales_data = (
            OrderItem.objects.values("order__created_at__month")
            .annotate(total_revenue=F("quantity") * F("unit_price"))
            .order_by("order__created_at__month")
        )

        sales_rev_labels = [
            months_ru.get(item["order__created_at__month"], f'Месяц {item["order__created_at__month"]}')
            for item in sales_data
        ]
        sales_rev_data = [float(item["total_revenue"]) for item in sales_data]

        # Top Selling Products Chart
        top_selling_products = (
            OrderItem.objects.filter(product__product_type='part').values("product__name")
            .annotate(total_quantity_sold=Sum("quantity"))
            .order_by("-total_quantity_sold")[:10]
        )
        tps_chart_labels = [item["product__name"] for item in top_selling_products]
        tps_chart_data = [item["total_quantity_sold"] for item in top_selling_products]

        # Inventory levels Chart
        inventory_levels = (
            Product.objects.filter(product_type="part").values("name")
            .annotate(total_qty_in_stock=Sum("quantity_in_stock"))
            .order_by("-total_qty_in_stock")
        )

        il_chart_labels = [item["name"] for item in inventory_levels]
        il_chart_data = [item["total_qty_in_stock"] for item in inventory_levels]

        # Supplier Contribution Chart

        supplier_contributions = (
            Product.objects.values("supplier__name")
            .annotate(total_quantity=Sum("quantity_in_stock"))
            .order_by("-total_quantity")
        )

        total_inventory = Product.objects.aggregate(
            total_quantity=Sum("quantity_in_stock")
        )["total_quantity"]
        sc_chart_labels = [item["supplier__name"] for item in supplier_contributions]
        sc_chart_data = [
            (
                round((item["total_quantity"] / total_inventory) * 100, 2)
                if total_inventory
                else 0
            )
            for item in supplier_contributions
        ]

        # Customer Orders Analysis

        customer_orders = (
            OrderItem.objects.values(
                "order__customer__name", "order__customer__phone"
            )
            .annotate(total_spending=Sum(F("quantity") * F("unit_price")))
            .order_by("-total_spending")[:5]
        )

        customer_orders_labels = [
            f"{item['order__customer__name']} {item['order__customer__phone']}"
            for item in customer_orders
        ]
        customer_orders_data = [
            float(item["total_spending"]) for item in customer_orders
        ]
        recent_actions = ActionLog.objects.select_related('user').all()[:10]

        context = {
            "low_stock": low_stock.count(),
            "products_total": product_total_cost,
            "orders_total": orders_total,
            "recent_actions": recent_actions,
            "revenue": net_revenue,
            "sales_rev_labels": (
                json.dumps(sales_rev_labels) if sales_rev_labels else json.dumps([])
            ),
            "sales_rev_data": (
                json.dumps(sales_rev_data) if sales_rev_data else json.dumps([])
            ),
            "tps_chart_labes": (
                json.dumps(tps_chart_labels) if tps_chart_labels else json.dumps([])
            ),
            "tps_chart_data": (
                json.dumps(tps_chart_data) if tps_chart_data else json.dumps([])
            ),
            "il_chart_labels": (
                json.dumps(il_chart_labels) if il_chart_labels else json.dumps([])
            ),
            "il_chart_data": (
                json.dumps(il_chart_data) if il_chart_data else json.dumps([])
            ),
            "sc_chart_labels": (
                json.dumps(sc_chart_labels) if sc_chart_labels else json.dumps([])
            ),
            "sc_chart_data": (
                json.dumps(sc_chart_data) if sc_chart_data else json.dumps([])
            ),
            "customer_orders_labels": (
                json.dumps(customer_orders_labels)
                if customer_orders_labels
                else json.dumps([])
            ),
            "customer_orders_data": (
                json.dumps(customer_orders_data)
                if customer_orders_data
                else json.dumps([])
            ),
        }

        return render(request, "inventorymanager/admin_dashboard.html", context)
    else:
        return redirect("login")


@login_required
def technician_dashboard(request):

    user = request.user
    salary_percent = 40


    today = timezone.now().replace(hour=0, minute=0, second=0)

    # Выручка от услуг за сегодня
    today_services = OrderItem.objects.filter(
        order__employee=user,
        order__status='issued',
        order__completed_at__gte=today,
        product__product_type='service'
    ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

    # Мои активные заказы
    my_active_orders = Order.objects.filter(
        employee=user
    ).filter(
        Q(status='accepted') | Q(status='in_work')
    ).select_related('customer', 'transport').order_by('created_at')[:10]

    # Заказы, ожидающие запчасти
    awaiting_parts = Order.objects.filter(
        employee=user,
        status='waiting_spareparts'
    ).select_related('customer', 'transport', 'employee').order_by('created_at')[:10]

    # Завершенные заказы за неделю
    week_ago = timezone.now() - timedelta(days=7)
    my_completed_orders = (
        Order.objects
        .filter(
            employee=user,
            status='issued',
            completed_at__gte=week_ago
        )
        .annotate(
            services_total=Sum(
                ExpressionWrapper(
                    F('order_items__quantity') *
                    F('order_items__unit_price'),
                    output_field=DecimalField()
                ),
                filter=Q(
                    order_items__product__product_type='service'
                )
            )
        )
        .select_related(
            'customer',
            'transport'
        )
    )

    for order in my_completed_orders:

        order.technician_earnings = (
            order.services_total_after_discount
            * Decimal(salary_percent / 100)
        )

    orders_qs = Order.objects.filter(
        employee=user
    )
    total_my_orders = orders_qs.count()
    my_completed_count = orders_qs.filter(status='issued').count()
    my_in_progress_count = orders_qs.filter(status='in_work').count()
    my_awaiting_parts_count = orders_qs.filter(status='waiting_spareparts').count()

    if total_my_orders > 0:
        completion_rate = round((my_completed_count / total_my_orders) * 100, 1)
    else:
        completion_rate = 0

    completed_orders = (
        Order.objects
        .filter(
            employee=user,
            status='issued'
        )
        .annotate(
            order_total=Sum(
                F('order_items__quantity') *
                F('order_items__unit_price')
            )
        )
    )

    avg_order_value = (
        completed_orders.aggregate(
            avg=Avg('order_total')
        )['avg']
        or 0
    )

    unique_customers_count = orders_qs.values('customer').distinct().count()
    context = {
        'my_active_orders': my_active_orders,
        'awaiting_parts': awaiting_parts,
        'total_my_orders': total_my_orders,
        'my_completed_count': my_completed_count,
        'my_completed_orders': my_completed_orders,
        'my_in_progress_count': my_in_progress_count,
        'my_awaiting_parts_count': my_awaiting_parts_count,
        'completion_rate': completion_rate,
        'today_services': today_services,
        'today_salary': today_services * Decimal(salary_percent / 100),
        'salary_percent': salary_percent,
        'avg_order_value': avg_order_value,
        'unique_customers_count': unique_customers_count,
        'current_date': timezone.now(),
    }
    return render(request, "inventorymanager/technician_dashboard.html", context)


@login_required
def dashboard_router(request):
    if request.user.is_superuser or request.user.groups.filter(name='Admin').exists():
        return redirect('admin_dashboard')
    else:
        return redirect('technician_dashboard')


def login_view(request):
    if request.method == "POST":

        email = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=email, password=password)

        # Check if authentication successful
        if user is not None:
            login(request, user)
            return redirect("index")
        else:
            return render(
                request,
                "inventorymanager/login.html",
                {"message": "Неверный логин или пароль"},
            )
    else:
        return render(request, "inventorymanager/login.html")

def logout_view(request):
    logout(request)
    return redirect("login")

@require_admin
@login_required
def salary_report(request):
    User = get_user_model()
    period_type = request.GET.get('period', 'month')
    selected_date = request.GET.get('date')

    # Получаем список всех техников
    technicians = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Technician') & Q(is_active = True)
    ).distinct().order_by('first_name', 'username')

    # Получаем процент каждого техника (для графика)
    technician_percents = {}
    for tech in technicians:
        try:
            if hasattr(tech, 'technician_profile'):
                technician_percents[tech.id] = tech.technician_profile.service_percent
            else:
                technician_percents[tech.id] = 40
        except:
            technician_percents[tech.id] = 40

    start_date, end_date = get_period_range(
        period_type,
        selected_date
    )

    # Рассчитываем start_date и end_date
    if period_type == 'week':
        period_label = f"Неделя {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"
        chart_labels = []
        chart_services_data = []
        chart_salary_data = []

        for i in range(7):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
            chart_labels.append(day_start.strftime('%a, %d.%m'))

            day_services = OrderItem.objects.filter(
                order__status='issued',
                order__completed_at__gte=day_start,
                order__completed_at__lt=end_date,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(day_services))
            chart_salary_data.append(float(day_services))  # TODO: посчитать зарплату по техникам

    elif period_type == 'month':
        period_label = f"Месяц {start_date.strftime('%B %Y')}"

        # Данные для графика по неделям
        days_in_month = (end_date - start_date).days + 1
        week_size = days_in_month // 4
        chart_labels = [f"{i+1}-я неделя" for i in range(4)]
        chart_services_data = []
        chart_salary_data = []

        for week_num in range(4):
            week_start = start_date + timedelta(days=week_num * week_size)
            if week_num == 3:
                week_end = end_date
            else:
                week_end = start_date + timedelta(days=(week_num + 1) * week_size - 1)

            week_services = OrderItem.objects.filter(
                order__status='issued',
                order__completed_at__gte=week_start,
                order__completed_at__lt=end_date,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(week_services))
            chart_salary_data.append(float(week_services))

    elif period_type == 'quarter':
        quarter = (start_date.month - 1) // 3 + 1
        period_label = f"Квартал {quarter} {start_date.year}"

        # Данные для графика по месяцам
        chart_labels = [f"{i+1} месяц" for i in range(3)]
        chart_services_data = []
        chart_salary_data = []

        for i in range(3):
            month_start = start_date + relativedelta(months=i)
            month_end = month_start + relativedelta(months=1) - timedelta(days=1)

            month_services = OrderItem.objects.filter(
                order__status='issued',
                order__completed_at__gte=month_start,
                order__completed_at__lt=end_date,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(month_services))
            chart_salary_data.append(float(month_services))

    else:  # year
        period_label = f"Год {start_date.year}"

        # Данные для графика по месяцам
        chart_labels = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
        chart_services_data = []
        chart_salary_data = []

        for i in range(12):
            month_start = start_date.replace(month=i+1)
            if i+1 == 12:
                month_end = month_start.replace(month=12, day=31)
            else:
                month_end = month_start.replace(month=i+2, day=1) - timedelta(days=1)

            month_services = OrderItem.objects.filter(
                order__status='issued',
                order__completed_at__gte=month_start,
                order__completed_at__lt=end_date,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(month_services))
            chart_salary_data.append(float(month_services))

    # Собираем данные по каждому технику
    salary_data = []
    total_services_all = 0
    total_salary_all = 0
    technician_services = {}  # для графика по техникам

    print(start_date)
    print(end_date)
    for tech in technicians:
        percent = technician_percents.get(tech.id, 40)
        # Выручка от услуг за период
        services_total = OrderItem.objects.filter(
            order__employee=tech,
            order__status='issued',
            order__completed_at__gte=start_date,
            order__completed_at__lt=end_date,
            product__product_type='service'
        ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0
        print(tech)
        print(f"Total: {services_total}")

        salary = services_total * Decimal(percent / 100)

        orders_count = Order.objects.filter(
            employee=tech,
            status='issued',
            completed_at__gte=start_date,
            completed_at__lt=end_date
        ).count()
        print(f"orders count: {orders_count}")

        salary_data.append({
            'user': tech,
            'percent': percent,
            'services_total': services_total,
            'salary': salary,
            'orders_count': orders_count,
        })

        technician_services[tech.get_full_name() or tech.username] = float(services_total)
        total_services_all += services_total
        total_salary_all += salary
    # Сортируем по зарплате
    salary_data.sort(key=lambda x: x['salary'], reverse=True)

    # Топ-5 техников для графика
    top_technicians = dict(sorted(technician_services.items(), key=lambda x: x[1], reverse=True)[:5])

    avg_service_per_technician = total_services_all / len(technicians) if len(technicians) > 0 else 0
    total_orders = sum(
        row["orders_count"]
        for row in salary_data
    )

    avg_order_value = (
        total_services_all / total_orders
        if total_orders
        else 0
    )
    # Собираем доступные даты для селектов
    available_weeks = []
    available_months = []
    available_quarters = []
    available_years = []

    order_dates = (
        Order.objects
        .filter(
            status='issued',
            completed_at__isnull=False
        )
        .order_by('completed_at')
    )

    if order_dates.exists():
        first_order = order_dates.first().completed_at
        last_order = order_dates.last().completed_at

        # Недели (последние 12)
        for i in range(12):
            week_date = last_order - timedelta(weeks=i)
            week_start = week_date - timedelta(days=week_date.weekday())
            week_end = week_start + timedelta(days=6)
            available_weeks.append({
                'value': week_start.strftime('%Y-%m-%d'),
                'label': f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m')}"
            })

        # Месяцы
        current = first_order.replace(day=1)
        while current <= last_order:
            available_months.append({
                'value': current.strftime('%Y-%m'),
                'label': current.strftime('%B %Y')
            })
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        # Кварталы
        quarters_seen = set()
        for order in order_dates:
            quarter = (order.completed_at.month - 1) // 3 + 1
            quarter_key = f"{order.completed_at.year}-Q{quarter}"
            if quarter_key not in quarters_seen:
                quarters_seen.add(quarter_key)
                available_quarters.append({
                    'value': quarter_key,
                    'label': f"{order.completed_at.year} - Квартал {quarter}"
                })

        # Годы
        years_seen = set()
        for order in order_dates:
            if order.completed_at.year not in years_seen:
                years_seen.add(order.completed_at.year)
                available_years.append({
                    'value': str(order.completed_at.year),
                    'label': str(order.completed_at.year)
                })

        available_months.sort(key=lambda x: x['value'])
        available_quarters.sort(key=lambda x: x['value'])
        available_years.sort(key=lambda x: x['value'])

    context = {
        'salary_data': salary_data,
        'total_services': total_services_all,
        'total_salary': total_salary_all,
        'period_label': period_label,
        'period_type': period_type,
        'start_date': start_date,
        'end_date': end_date,
        'avg_order_value': avg_order_value,
        'technicians_count': len(technicians),
        'avg_service_per_technician': avg_service_per_technician,
        'available_weeks': available_weeks,
        'available_months': available_months,
        'available_quarters': available_quarters,
        'available_years': available_years,
        # Данные для графиков
        'chart_labels': json.dumps(chart_labels),
        'chart_services_data': json.dumps(chart_services_data),
        'chart_salary_data': json.dumps(chart_salary_data),
        'top_technicians_labels': json.dumps(list(top_technicians.keys())),
        'top_technicians_data': json.dumps(list(top_technicians.values())),
    }
    return render(request, "inventorymanager/salary_report.html", context)


@login_required
def my_salary(request):
    """Детальная страница зарплаты техника с выбором периода и графиками"""
    user = request.user
    salary_percent = 40

    period_type = request.GET.get('period', 'month')  # week, month, quarter, year
    selected_date = request.GET.get('date')
    start_date, end_date = get_period_range(
        period_type,
        selected_date
    )

    period_start = start_date.date()

    if period_type == 'week':
        week_end = (end_date - timedelta(days=1)).date()
        period_label = (
            f"Неделя "
            f"{period_start.strftime('%d.%m')} - "
            f"{week_end.strftime('%d.%m.%Y')}"
        )
        chart_labels = [
            (period_start + timedelta(days=i)).strftime('%a, %d.%m')
            for i in range(7)
        ]
    elif period_type == 'month':
        period_label = period_start.strftime('Месяц %B %Y')
        chart_labels = [
            f"{i + 1}-я неделя"
            for i in range(4)
        ]
    elif period_type == 'quarter':
        quarter = (period_start.month - 1) // 3 + 1
        period_label = f"Квартал {quarter} {period_start.year}"
        chart_labels = [
            "1 месяц",
            "2 месяц",
            "3 месяц",
        ]
    else:
        period_label = f"Год {period_start.year}"
        chart_labels = [
            'Янв', 'Фев', 'Мар', 'Апр',
            'Май', 'Июн', 'Июл', 'Авг',
            'Сен', 'Окт', 'Ноя', 'Дек'
        ]

    chart_services_data = []
    chart_salary_data = []

    if period_type == 'week':
        # Понедельная детализация по дням
        for i in range(7):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            day_services = get_services_total(
                OrderItem.objects.filter(
                    order__employee=user,
                    order__status='issued',
                    order__completed_at__gte=day_start,
                    order__completed_at__lt=day_end,
                    product__product_type='service'
                )
            )
            chart_services_data.append(float(day_services))
            chart_salary_data.append(
                float(day_services * Decimal(salary_percent / 100))
            )

    elif period_type == 'month':
        # Помесячная детализация по неделям
        days_in_month = (end_date - start_date).days
        week_size = max(days_in_month // 4, 1)

        for week_num in range(4):

            week_start = start_date + timedelta(
                days=week_num * week_size
            )

            if week_num == 3:
                week_end = end_date
            else:
                week_end = start_date + timedelta(
                    days=(week_num + 1) * week_size
                )

            week_services = get_services_total(
                OrderItem.objects.filter(
                    order__employee=user,
                    order__status='issued',
                    order__completed_at__gte=week_start,
                    order__completed_at__lt=week_end,
                    product__product_type='service'
                )
            )

            chart_services_data.append(float(week_services))

            chart_salary_data.append(
                float(week_services * Decimal(salary_percent / 100))
            )

    elif period_type == 'quarter':
        # Поквартальная детализация по месяцам
        for i in range(3):
            month_start = start_date + relativedelta(months=i)
            month_end = month_start + relativedelta(months=1)
            month_services = get_services_total(
                OrderItem.objects.filter(
                    order__employee=user,
                    order__status='issued',
                    order__completed_at__gte=month_start,
                    order__completed_at__lt=month_end,
                    product__product_type='service'
                )
            )
            chart_services_data.append(float(month_services))
            chart_salary_data.append(
                float(month_services * Decimal(salary_percent / 100))
            )
    else:
        # Годовая детализация по месяцам
        for i in range(12):
            month_start = start_date + relativedelta(months=i)
            month_end = month_start + relativedelta(months=1)
            month_services = get_services_total(
                OrderItem.objects.filter(
                    order__employee=user,
                    order__status='issued',
                    order__completed_at__gte=month_start,
                    order__completed_at__lt=month_end,
                    product__product_type='service'
                )
            )
            chart_services_data.append(float(month_services))
            chart_salary_data.append(
                float(month_services * Decimal(salary_percent / 100))
            )


    period_services_total = sum(chart_services_data)
    period_salary = period_services_total * (salary_percent / 100)
    period_orders_count = Order.objects.filter(
        employee=user,
        status='issued',
        completed_at__gte=start_date,
        completed_at__lt=end_date
    ).count()

    # Список доступных дат для селектов
    available_weeks = []
    available_months = []
    available_quarters = []
    available_years = []

    # Собираем доступные периоды из заказов техника
    order_dates = (
    Order.objects
        .filter(
            employee=user,
            status='issued',
            completed_at__isnull=False
        )
        .order_by('completed_at')
    )

    if order_dates.exists():
        first_order = order_dates.first().completed_at
        last_order = order_dates.last().completed_at

        # Недели (последние 12)
        for i in range(12):
            week_date = last_order - timedelta(weeks=i)
            week_start = week_date - timedelta(days=week_date.weekday())
            week_end = week_start + timedelta(days=6)
            available_weeks.append({
                'value': week_start.strftime('%Y-%m-%d'),
                'label': f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m')}"
            })

        # Месяцы
        current = first_order.replace(day=1)
        while current <= last_order:
            available_months.append({
                'value': current.strftime('%Y-%m'),
                'label': current.strftime('%B %Y')
            })
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        # Кварталы
        quarters_seen = set()
        for order in order_dates:
            quarter = (order.completed_at.month - 1) // 3 + 1
            quarter_key = f"{order.completed_at.year}-Q{quarter}"
            if quarter_key not in quarters_seen:
                quarters_seen.add(quarter_key)
                available_quarters.append({
                    'value': quarter_key,
                    'label': f"{order.completed_at.year} - Квартал {quarter}"
                })

        # Годы
        years_seen = set()
        for order in order_dates:
            if order.completed_at.year not in years_seen:
                years_seen.add(order.completed_at.year)
                available_years.append({
                    'value': str(order.completed_at.year),
                    'label': str(order.completed_at.year)
                })

        # Сортируем
        available_months.sort(key=lambda x: x['value'])
        available_quarters.sort(key=lambda x: x['value'])
        available_years.sort(key=lambda x: x['value'])

    context = {
        'salary_percent': salary_percent,
        'period_services_total': period_services_total,
        'period_salary': period_salary,
        'period_orders_count': period_orders_count,
        'period_label': period_label,
        'period_type': period_type,
        'start_date': start_date,
        'end_date': end_date,
        'available_weeks': available_weeks,
        'available_months': available_months,
        'available_quarters': available_quarters,
        'available_years': available_years,
        'chart_labels': json.dumps(chart_labels),
        'chart_services_data': json.dumps(chart_services_data),
        'chart_salary_data': json.dumps(chart_salary_data),
    }
    return render(request, "inventorymanager/my_salary.html", context)

@require_admin
@login_required
def create_supplier(request):
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier created successfully")
            return redirect("suppliers")

        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = SupplierForm()

    return render(request, "inventorymanager/createSupplier.html", {"form": form})



@login_required
def supplier_view(request):
    suppliers = Supplier.objects.all()

    return render(request, "inventorymanager/suppliers.html", {"suppliers": suppliers})


@login_required
def customer_view(request):
    customers = Customer.objects.annotate(
        orders_count=Count('orders', distinct=True),
        transports_count=Count('transports', distinct=True)
    ).order_by('name')

    # Поиск
    search_query = request.GET.get('search', '')
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(telegram__icontains=search_query)
        )

    # Пагинация
    paginator = Paginator(customers, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Статистика
    total_customers = Customer.objects.count()
    active_customers = Customer.objects.filter(orders__isnull=False).distinct().count()
    total_orders = Order.objects.count()

    context = {
        'customers': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'search_query': search_query,
        'total_customers': total_customers,
        'active_customers': active_customers,
        'total_orders': total_orders,
    }
    return render(request, 'inventorymanager/customers.html', context)


@login_required
def transport_view(request):
    transports = Transport.objects.select_related('customer').annotate(
        orders_count=Count('orders')
    ).order_by('-created_at')

    # Поиск
    search_query = request.GET.get('search', '')
    if search_query:
        transports = transports.filter(
            Q(name__icontains=search_query) |
            Q(serial_number__icontains=search_query) |
            Q(customer__name__icontains=search_query)
        )

    # Фильтр по типу
    transport_type = request.GET.get('transport_type', '')
    if transport_type:
        transports = transports.filter(transport_type=transport_type)

    # Фильтр по клиенту
    selected_customer = request.GET.get('customer', '')
    if selected_customer:
        transports = transports.filter(customer_id=selected_customer)

    # Пагинация
    paginator = Paginator(transports, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Статистика
    total_transports = Transport.objects.count()
    total_customers = Customer.objects.filter(transports__isnull=False).distinct().count()
    total_orders = Order.objects.filter(transport__isnull=False).count()

    # Список всех клиентов для фильтра
    customers = Customer.objects.all().order_by('name')

    context = {
        'transports': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'search_query': search_query,
        'transport_type': transport_type,
        'selected_customer': selected_customer,
        'customers': customers,
        'total_transports': total_transports,
        'total_customers': total_customers,
        'total_orders': total_orders,
    }
    return render(request, 'inventorymanager/transports.html', context)


@login_required
def create_customer(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Клиент успешно добавлен')

            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url+ f"?customer={form.instance.id}")
            return redirect('customers')
    else:
        form = CustomerForm()

    return render(request, 'inventorymanager/createCustomer.html', {'form': form})

@login_required
def create_transport(request):
    if request.method == 'POST':
        form = TransportForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Техника успешно добавлена')

            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url + f"&transport={form.instance.id}")
            return redirect('transports')
    else:
        # Предзаполнение клиента, если передан параметр
        initial = {}
        customer_id = request.GET.get('customer_id')
        if customer_id:
            initial['customer'] = customer_id
        form = TransportForm(initial=initial)

    return render(request, 'inventorymanager/createTransport.html', {'form': form})


@login_required
def product_view(request):
    # products = Product.objects.annotate(
    #     total_value=Sum(F('quantity_in_stock') * F('unit_cost'))
    # )
    products = Product.objects.select_related("supplier", "category").annotate(
        total_value=Sum(F("quantity_in_stock") * F("unit_cost"))
    )
    search_query = request.GET.get('search', '')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(category__name__icontains=search_query) |
            Q(supplier__name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Фильтр по типу (запчасть/услуга)
    product_type_filter = request.GET.get('product_type', '')
    if product_type_filter:
        products = products.filter(product_type=product_type_filter)

    # Фильтр по категории
    category_filter = request.GET.get('category', '')
    if category_filter:
        products = products.filter(category_id=category_filter)

    # Пагинация
    paginator = Paginator(products, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Список категорий для фильтра
    categories = Category.objects.all().order_by('name')
    # low_stock = Product.objects.filter(quantity_in_stock__lte=3)

    # if low_stock.count() > 0:
    #     if low_stock.count() > 1:
    #         messages.error(request, f"{low_stock.count()} items have low stock")
    #     else:
    #         messages.error(request, f"{low_stock.count()} item has low stock")

    low_stock_count = Product.objects.filter(quantity_in_stock__lte=1, product_type='part').count()

    if low_stock_count > 0:
        if low_stock_count > 1:
            messages.error(request, f"{low_stock_count} товары заканчивают на складе")
        else:
            messages.error(request, f"{low_stock_count} товар заканчивают на складе")

    context = {
        'products': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'search_query': search_query,
        'product_type_filter': product_type_filter,
        'category_filter': category_filter,
        'categories': categories,
    }
    return render(
        request,
        "inventorymanager/products.html",
        context,
    )


@require_admin
@login_required
def create_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Товар успешно добавлен')
            return redirect('products')
    else:
        form = ProductForm()

    return render(request, 'inventorymanager/edit_product.html', {'form': form})


@login_required
def order_list(request):
    orders = (Order.objects.select_related(
        'customer',
        'transport',
        'employee'
    )
    .prefetch_related(
        'order_items__product'
    ).annotate(
        total_value=Sum(F('order_items__quantity') * F('order_items__unit_price'))
    ).order_by('-created_at'))

    # Поиск по номеру заказа, клиенту, транспорту или серийному номеру
    search_query = request.GET.get('search', '')
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(transport__name__icontains=search_query) |
            Q(transport__serial_number__icontains=search_query)
        )

    # Фильтр по статусу
    status = request.GET.get('status', '')
    if status:
        orders = orders.filter(status=status)
    else:
        orders = orders.exclude(status__in=("issued", "cancelled"))

    # Фильтр по дате (от)
    date_from = request.GET.get('date_from', '')
    if date_from:
        orders = orders.filter(created_at__date__gte=date_from)

    # Фильтр по дате (до)
    date_to = request.GET.get('date_to', '')
    if date_to:
        orders = orders.filter(created_at__date__lte=date_to)

    # Фильтр по технику
    employee = request.GET.get('employee', '')
    if employee:
        orders = orders.filter(employee=employee)
    # Статистика для виджетов
    total_orders = Order.objects.count()
    accepted_count = Order.objects.filter(status='accepted').count()
    issued_count = Order.objects.filter(status='issued').count()
    in_work_count = Order.objects.filter(status='in_work').count()
    ready_count = Order.objects.filter(status='ready').count()
    waiting_spareparts_count = Order.objects.filter(status='waiting_spareparts').count()

    # Выручка (сумма всех завершённых заказов)
    total_revenue = Order.objects.filter(status='issued').aggregate(
        total=Sum(F('order_items__quantity') * F('order_items__unit_price'))
    )['total'] or 0

    # Пагинация (15 заказов на страницу)
    paginator = Paginator(orders, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    User = get_user_model()
    technicians = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Technician')
    ).distinct().order_by('first_name', 'username')

    context = {
        'orders': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'total_orders': total_orders,
        'accepted_count': accepted_count,
        'issued_count': issued_count,
        'in_work_count': in_work_count,
        'ready_count': ready_count,
        'waiting_spareparts_count': waiting_spareparts_count,
        'total_revenue': total_revenue,
        'search_query': search_query,
        'status_filter': status,
        'date_from': date_from,
        'date_to': date_to,
        'technicians': technicians,
    }

    return render(request, 'inventorymanager/orders.html', context)

@login_required
def create_order(request):
    products = Product.objects.all().order_by('product_type', 'name')
    customers = Customer.objects.all().order_by('name')
    transports = Transport.objects.select_related('customer').all().order_by('-created_at')
    User = get_user_model()
    technicians = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Technician') & Q(is_active=True)
    ).distinct().order_by('first_name', 'username')

    if request.method == 'POST':
        form = OrderForm(request.POST)
        formset = OrderItemFormSet(request.POST)
        initial_customer = request.POST.get('customer')
        initial_transport = request.POST.get('transport')
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                customer_id = initial_customer
                transport_id = initial_transport
                employee_id = request.POST.get('employee')
                context = {'form': form,
                            'formset': formset,
                            'products': products,
                            'customers': customers,
                            'transports': transports,
                            'initial_customer': initial_customer or '',
                            'initial_transport': transport_id or '',
                            'title': 'Создание заказа',
                        }
                if not customer_id or not transport_id:
                    messages.error(request, 'Выберите клиента' if not customer_id else 'Выберите технику')
                    return render(request, 'inventorymanager/order_form.html', context)

                customer = get_object_or_404(Customer, id=customer_id)
                transport = get_object_or_404(Transport, id=transport_id)
                order = form.save(commit=False)
                order.customer = customer
                order.transport = transport
                order.service_discount = Decimal(
                    request.POST.get('service_discount') or 0
                )
                order.parts_discount = Decimal(
                    request.POST.get('parts_discount') or 0
                )
                services_total, parts_total = calculate_formset_totals(formset)

                if order.service_discount > services_total:
                    messages.error(
                        request,
                        "Скидка превышает стоимость работ."
                    )
                    return render(request, 'inventorymanager/order_form.html', context)

                if order.parts_discount > parts_total:
                    messages.error(
                        request,
                        "Скидка превышает стоимость запчастей."
                    )
                    return render(request, 'inventorymanager/order_form.html', context)

                if employee_id:
                    order.employee_id = employee_id
                else:
                    order.employee = request.user
                order.description = request.POST.get('description', '')
                order.save()


                for item_form in formset:
                    if item_form.cleaned_data and not item_form.cleaned_data.get('DELETE', False):
                        product = item_form.cleaned_data['product']
                        quantity = item_form.cleaned_data['quantity']

                        # if product.product_type == 'part' and product.quantity_in_stock < quantity:
                        #     messages.error(request, f'Недостаточно {product.name} на складе!')
                        #     raise transaction.rollback()

                        OrderItem.objects.create(
                            order=order,
                            product=product,
                            quantity=quantity,
                            unit_price=product.unit_cost
                        )

                        # if product.product_type == 'part':
                        #     product.quantity_in_stock -= quantity
                        #     product.save()
                log_action(
                    request,
                    'create',
                    'Order',
                    order.id,
                    f"Заказ #{order.id}"
                )
                messages.success(request, f'Заказ #{order.id} успешно создан!')
                return redirect('order_detail', order_id=order.id)
    else:
        form = OrderForm()
        formset = OrderItemFormSet()
        initial_customer = request.GET.get('customer')
        initial_transport = request.GET.get('transport')
    context = {
        'form': form,
        'formset': formset,
        'products': products,
        'customers': customers,
        'transports': transports,
        'technicians': technicians,
        'initial_customer': initial_customer or '',
        'initial_transport': initial_transport or '',
        'title': 'Создание заказа',
    }
    return render(request, 'inventorymanager/order_form.html', context)


@login_required
def category_view(request):
    categories = Category.objects.all()
    return render(
        request, "inventorymanager/categories.html", {"categories": categories}
    )


@require_admin
@login_required
def create_category(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Category created successfully")
            return redirect("categories")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CategoryForm()

    return render(request, "inventorymanager/createCategory.html", {"form": form})


@login_required
def supplier_detail(request, id):
    supplier = get_object_or_404(Supplier, id=id)
    return render(
        request, "inventorymanager/supplier_detail.html", {"supplier": supplier}
    )


@login_required
def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    transports = Transport.objects.filter(customer=customer)
    orders = Order.objects.filter(customer=customer).order_by('-created_at')

    # Общая сумма заказов
    total_spent = orders.filter(status='completed').aggregate(
        total=Sum('order_items__unit_price')
    )['total'] or 0

    context = {
        'customer': customer,
        'transports': transports,
        'orders': orders,
        'total_spent': total_spent,
    }
    return render(request, 'inventorymanager/customer_detail.html', context)


@login_required
def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    form = ProductForm(instance=product)
    return render(
        request,
        "inventorymanager/product_detail.html",
        {"product": product, "form": form},
    )


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    return render(
        request,
        "inventorymanager/order_detail.html",
        {"order": order},
    )


@login_required
def category_detail(request, id):
    category = get_object_or_404(Category, id=id)
    form = CategoryForm(instance=category)
    return render(
        request,
        "inventorymanager/category_detail.html",
        {"category": category, "form": form},
    )


@login_required
def transport_detail(request, transport_id):
    transport = get_object_or_404(Transport.objects.select_related('customer'), id=transport_id)
    orders = Order.objects.filter(transport=transport).order_by('-created_at')

    context = {
        'transport': transport,
        'orders': orders,
    }
    return render(request, 'inventorymanager/transport_detail.html', context)


@require_admin
@login_required
def edit_supplier(request, id):
    if request.method == "POST":
        data = json.loads(request.body)
        edit_suppl = get_object_or_404(Supplier, id=id)
        edit_suppl.name = data["name"]
        edit_suppl.contact_name = data["contact_name"]
        edit_suppl.contact_email = data["contact_email"]
        edit_suppl.contact_phone = data["contact_phone"]
        edit_suppl.save()
        return JsonResponse(
            {
                "message": "changes successfully made",
                "name": edit_suppl.name,  # Return the updated supplier details
                "contact_name": edit_suppl.contact_name,
                "contact_email": edit_suppl.contact_email,
                "contact_phone": edit_suppl.contact_phone,
            }
        )


@login_required
def edit_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, f'Клиент "{customer.name}" успешно обновлён')
            return redirect('customer_detail', customer_id=customer.id)
    else:
        form = CustomerForm(instance=customer)

    return render(request, 'inventorymanager/createCustomer.html', {'form': form})


@login_required
def edit_transport(request, transport_id):
    transport = get_object_or_404(Transport, id=transport_id)

    if request.method == 'POST':
        form = TransportForm(request.POST, instance=transport)
        if form.is_valid():
            form.save()
            messages.success(request, f'Техника "{transport.name}" успешно обновлена')
            return redirect('transport_detail', transport_id=transport.id)
    else:
        form = TransportForm(instance=transport)

    return render(request, 'inventorymanager/createTransport.html', {'form': form})

@require_admin
@login_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            if request.POST.get('clear_image'):
                product.image.delete()
                product.image = None
            form.save()
            messages.success(request, f'Товар "{product.name}" успешно обновлён')
            return redirect('product_detail', product_id=product.id)
    else:
        form = ProductForm(instance=product)

    return render(request, 'inventorymanager/edit_product.html', {
        'form': form,
        'product': product,
    })


@login_required
# @require_order_access
def edit_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    customers = Customer.objects.all().order_by('name')
    transports = Transport.objects.select_related('customer').all()
    products = Product.objects.all().order_by('product_type', 'name')
    User = get_user_model()
    technicians = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Technician')
    ).distinct().order_by('first_name', 'username')
    if request.method == 'POST':
        old_items = {}
        if order.status in ('in_work', 'ready'):
            old_items = {
                item.product_id: item.quantity
                for item in order.order_items.select_related('product').all()
                if item.product.product_type == 'part'
            }

        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    if order.status in ('in_work', 'ready'):
                        new_items = {}
                        for form_item in formset.forms:
                            if form_item.cleaned_data.get('DELETE'):
                                continue

                            product = form_item.cleaned_data.get('product')
                            quantity = form_item.cleaned_data.get('quantity')
                            if product and quantity and product.product_type == 'part':
                                new_items[product.id] = quantity

                        all_ids = set(old_items.keys()) | set(new_items.keys())
                        for product_id in all_ids:
                            old_qty = old_items.get(product_id, 0)
                            new_qty = new_items.get(product_id, 0)
                            diff = new_qty - old_qty
                            if diff <= 0:
                                continue
                            product = Product.objects.select_for_update().get(id=product_id)

                            if product.quantity_in_stock < diff:
                                messages.error(
                                    request,
                                    f'Недостаточно "{product.name}". '
                                    f'Доступно: {product.quantity_in_stock}, нужно: {diff}'
                                )
                                transaction.set_rollback(True)
                                return redirect('order_detail', order_id=order.id)

                    order = form.save(commit=False)
                    customer_id = request.POST.get('customer')
                    transport_id = request.POST.get('transport')
                    employee_id = request.POST.get('employee')
                    order.description = request.POST.get('description', '')
                    order.service_discount = Decimal(
                        request.POST.get('service_discount') or 0
                    )
                    order.parts_discount = Decimal(
                        request.POST.get('parts_discount') or 0
                    )
                    services_total, parts_total = calculate_formset_totals(formset)
                    if order.service_discount > services_total:
                        messages.error(request, "Скидка превышает стоимость работ.")
                        return redirect('order_detail', order_id=order.id)

                    if order.parts_discount > parts_total:
                        messages.error(request,"Скидка превышает стоимость запчастей.")
                        return redirect('order_detail', order_id=order.id)

                    if customer_id:
                        order.customer_id = customer_id
                    if transport_id:
                        order.transport_id = transport_id
                    if employee_id:
                        order.employee_id = employee_id

                    order.save()

                    formset.instance = order
                    formset.save()

                    if order.status in ('in_work', 'ready'):
                        new_items = {
                            item.product_id: item.quantity
                            for item in order.order_items.select_related('product').all()
                            if item.product.product_type == 'part'
                        }

                        all_ids = set(old_items.keys()) | set(new_items.keys())

                        for product_id in all_ids:
                            old_qty = old_items.get(product_id, 0)
                            new_qty = new_items.get(product_id, 0)
                            diff = new_qty - old_qty

                            if diff == 0:
                                continue

                            product = Product.objects.select_for_update().get(id=product_id)

                            if diff > 0:
                                product.quantity_in_stock = (
                                    F('quantity_in_stock') - diff
                                )
                            else:
                                product.quantity_in_stock = (
                                    F('quantity_in_stock') + abs(diff)
                                )

                            product.save()

                    log_action(
                        request,
                        'edit',
                        'Order',
                        order.id,
                        f"Заказ #{order.id}"
                    )
                    messages.success(
                        request,
                        f'Заказ #{order.id} обновлён'
                    )
                    return redirect('order_detail', order_id=order.id)

            except Exception as e:
                messages.error(
                    request,
                    f'Ошибка при обновлении заказа: {str(e)}'
                )
                return redirect('order_detail', order_id=order.id)
    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order)

    return render(request, 'inventorymanager/order_form.html', {
        'title': f'Редактирование заказа #{order.id}',
        'form': form,
        'formset': formset,
        'order': order,
        'customers': customers,
        'transports': transports,
        'technicians': technicians,
        'initial_customer': order.customer.id or '',
        'initial_transport': order.transport.id or '',
        'products': products,
    })


@login_required
@require_order_access
def cancel_order_update(request, order):

    if request.method == "GET":
        if order.status == "issued":
            messages.warning(request, f'Невозможно отменить заказ со статусом {order.get_status_display()}')
            return redirect("orders")

        for order_item in order.order_items.all():
            # Restoring current quantity in stock
            order_item.product.quantity_in_stock -= order_item.quantity
            order_item.product.save()
        log_action(
            request,
            'status_change',
            'Order',
            order.id,
            f"Заказ #{order.id}",
            {'old_status': order.status, 'new_status': "cancelled"}
        )
        order.status = "cancelled"
        order.save()
        messages.success(request, f'Заказ #{order.id} отменён, запчасти возвращены на склад')
    return redirect("orders")


@login_required
# @require_order_access
def change_order_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    status = request.GET.get('status')
    valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]

    if status not in valid_statuses or order.status == status:
        messages.warning(request, f"Недопустимый статус заказа.")
        return redirect('order_detail', order_id=order.id)

    if status == 'in_work'  and order.status in ('accepted', 'waiting_spareparts'):
        with transaction.atomic():
            missing_parts = []
            for item in order.order_items.all():
                if item.product.product_type == 'part':
                    if item.product.quantity_in_stock >= item.quantity:
                        item.product.quantity_in_stock -= item.quantity
                        item.product.save()
                    else:
                        missing_parts.append({
                            'name': item.product.name,
                            'available': item.product.quantity_in_stock,
                            'required': item.quantity
                        })

            if missing_parts:
                for part in missing_parts:
                    messages.error(request, f'Недостаточно "{part["name"]}" на складе. Доступно: {part["available"]}, требуется: {part["required"]}')
                return redirect('order_detail', order_id=order.id)

    if order.status in ('in_work', 'ready') and status in ('accepted', 'waiting_spareparts'):
        for item in order.order_items.all():
            if item.product.product_type == 'part':
                item.product.quantity_in_stock += item.quantity
                item.product.save()
        messages.info(request, 'Запчасти возвращены на склад')

    if order.status != 'issued' and status == 'issued':
        if order.debt > 0:
            messages.error(request, f"Ошибка! Не закрытый долг до заказу. Сумма {order.debt}")
            return redirect('order_detail', order_id=order.id)
        order.completed_at = timezone.now()

    log_action(
            request,
            'status_change',
            'Order',
            order.id,
            f"Заказ #{order.id}",
            {'old_status': order.status, 'new_status': status}
        )
    order.status = status
    order.save()
    messages.success(request, f'Заказ #{order.id} отмечен как "{order.get_status_display()}"')
    return redirect('order_detail', order_id=order.id)


@login_required
@require_admin
def action_logs(request):
    logs = ActionLog.objects.select_related('user').all().order_by('-created_at')
    action_type = request.GET.get('action_type', '')
    if action_type:
        logs = logs.filter(action_type=action_type)

    user_id = request.GET.get('user', '')
    if user_id:
        logs = logs.filter(user_id=user_id)

    model_name = request.GET.get('model', '')
    if model_name:
        logs = logs.filter(model_name=model_name)

    date_from = request.GET.get('date_from', '')
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)

    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Список пользователей для фильтра
    users = get_user_model().objects.filter(actionlog__isnull=False).distinct().order_by('first_name', 'username')

    context = {
        'logs': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'action_types': ActionLog.ACTION_TYPES,
        'users': users,
        'selected_action': action_type,
        'selected_user': user_id,
        'selected_model': model_name,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'inventorymanager/action_logs.html', context)


@require_admin
@login_required
def edit_category(request, id):
    category = get_object_or_404(Category, id=id)
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            updated_category = form.save()

            return JsonResponse(
                {
                    "success": True,
                    "name": updated_category.name,
                    "description": updated_category.description,
                }
            )
    else:
        form = CategoryForm(instance=category)
        return render(request, "inventorymanager/category_detail.html", {"form": form})


@login_required
@require_admin
def delete_supplier(request, id):
    supplier = get_object_or_404(Supplier, id=id)
    supplier.delete()
    messages.success(request, "Supplier deleted successfully")
    return redirect("suppliers")


@login_required
@require_admin
def delete_customer(request, id):
    customer = get_object_or_404(Customer, id=id)
    customer.delete()
    messages.success(request, "Customer deleted successfully")
    return redirect("customers")


@login_required
@require_admin
def delete_product(request, id):
    product = get_object_or_404(Product, id=id)
    product.delete()
    messages.success(request, "Product deleted successfully")
    return redirect("products")


@login_required
@require_order_access
def delete_order(request, id):
    order = get_object_or_404(Order, id=id)

    for order_item in order.order_items.all():
        order_item.delete()

    order.delete()
    messages.success(request, "Order deleted successfully")
    return redirect("orders")


@login_required
@require_admin
def delete_category(request, id):
    category = get_object_or_404(Category, id=id)
    category.delete()
    messages.success(request, "Category deleted successfully")
    return redirect("categories")


@login_required
@require_admin
def cash_register_list(request):
    cash_register = CashRegister.objects.filter(is_active=True).first()

    transactions = CashTransaction.objects.filter(
        cash_register=cash_register
    ).select_related('order', 'employee').order_by('-created_at')

    # Фильтры
    operation_type = request.GET.get('operation_type', '')
    if operation_type:
        transactions = transactions.filter(operation_type=operation_type)

    payment_method = request.GET.get('payment_method', '')
    if payment_method:
        transactions = transactions.filter(payment_method=payment_method)

    date_from = request.GET.get('date_from', '')
    if date_from:
        transactions = transactions.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        transactions = transactions.filter(created_at__date__lte=date_to)

    # Пагинация
    paginator = Paginator(transactions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Статистика
    total_income = transactions.filter(operation_type='income').aggregate(total=Sum('amount'))['total'] or 0
    total_expense = transactions.filter(operation_type='expense').aggregate(total=Sum('amount'))['total'] or 0
    current_balance = cash_register.current_balance() if cash_register else 0

    context = {
        'transactions': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'cash_register': cash_register,
        'total_income': total_income,
        'total_expense': total_expense,
        'current_balance': current_balance,
        'operation_type_filter': operation_type,
        'payment_method_filter': payment_method,
        'date_from': date_from,
        'date_to': date_to,
    }
    return render(request, 'inventorymanager/cash_register_list.html', context)


@login_required
def cash_transaction_create(request):
    if request.method == 'POST':
        form = CashTransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.employee = request.user
            transaction.save()

            # Логируем действие
            log_action(request, 'create', 'CashTransaction', transaction.id,
                      f"Кассовая операция #{transaction.id}: {transaction.get_operation_type_display()} {transaction.amount}₽")

            messages.success(request, f'Операция "{transaction.reason}" создана')
            return redirect('cash_register_list')
    else:
        initial = {}
        cash_register = CashRegister.objects.filter(is_active=True).first()
        if cash_register:
            initial['cash_register'] = cash_register.id
        form = CashTransactionForm(initial=initial)

    return render(request, 'inventorymanager/createCashTransaction.html', {'form': form, 'title': 'Новая операция'})

@login_required
@require_admin
def cash_register_settings(request):
    """Настройки касс"""
    registers = CashRegister.objects.all()

    if request.method == 'POST' and 'create_register' in request.POST:
        form = CashRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Касса создана')
            return redirect('cash_register_settings')

    form = CashRegisterForm()

    context = {
        'registers': registers,
        'form': form,
    }
    return render(request, 'inventorymanager/cash_register_settings.html', context)


@login_required
@require_admin
def cash_register_close_shift(request, register_id):
    """Закрытие смены (Z-отчёт)"""
    cash_register = get_object_or_404(CashRegister, id=register_id)

    # Получаем операции за текущий день
    today = timezone.now().date()
    today_transactions = CashTransaction.objects.filter(
        cash_register=cash_register,
        created_at__date=today
    )

    income_today = today_transactions.filter(operation_type='income').aggregate(total=Sum('amount'))['total'] or 0
    expense_today = today_transactions.filter(operation_type='expense').aggregate(total=Sum('amount'))['total'] or 0

    closing_balance = cash_register.current_balance()

    if request.method == 'POST':
        # Экспорт в PDF или просто сохранение отчёта
        messages.success(request, f'Смена в кассе "{cash_register.name}" закрыта. Остаток: {closing_balance}₽')
        return redirect('cash_register_list')

    context = {
        'cash_register': cash_register,
        'income_today': income_today,
        'expense_today': expense_today,
        'closing_balance': closing_balance,
        'transactions': today_transactions[:20],
    }
    return render(request, 'inventorymanager/cash_register_close_shift.html', context)


@require_http_methods(["POST"])
def api_create_customer(request):
    try:
        data = json.loads(request.body) if request.body else request.POST
        name = data.get('name')
        if not name:
            return JsonResponse({'success': False, 'error': 'Имя обязательно'}, status=400)

        customer = Customer.objects.create(
            name=name,
            phone=data.get('phone', ''),
            telegram=data.get('telegram', '')
        )

        return JsonResponse({
            'success': True,
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'telegram': customer.telegram
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def upload_transport_photo(request, transport_id):
    transport = get_object_or_404(Transport, id=transport_id)
    order_id = request.POST.get('order_id')
    order = get_object_or_404(Order, id=order_id) if order_id else None

    if request.method == 'POST' and request.FILES.get('image'):
        image = request.FILES['image']
        description = request.POST.get('description', '')

        TransportImage.objects.create(
            transport=transport,
            order=order,
            image=image,
            description=description,
            uploaded_by=request.user
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})

        messages.success(request, f'Фото добавлено к транспорту "{transport.name}"')
        return redirect('order_detail', order_id=order_id)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Нет фото'})

    return redirect('order_detail', order_id=order_id)


@require_http_methods(["POST"])
def api_create_transport(request):
    try:
        data = json.loads(request.body) if request.body else request.POST
        customer_id = data.get('customer_id')
        name = data.get('name')

        if not customer_id or not name:
            return JsonResponse({'success': False, 'error': 'Клиент и название обязательны'}, status=400)

        customer = Customer.objects.get(id=customer_id)

        transport = Transport.objects.create(
            customer=customer,
            name=name,
            serial_number=data.get('serial_number', ''),
            transport_type=data.get('transport_type', 'bicycle'),
            color=data.get('color', ''),
            comment=data.get('comment', '')
        )

        return JsonResponse({
            'success': True,
            'transport': {
                'id': transport.id,
                'name': transport.name,
                'customer_id': transport.customer.id,
                'customer_name': transport.customer.name,
                'type': transport.transport_type,
                'type_display': transport.get_transport_type_display(),
                'serial_number': transport.serial_number,
                'color': transport.color
            }
        })
    except Customer.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Клиент не найден'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
# @require_order_access
def order_add_payment(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount')))
        payment_method = data.get('payment_method')
        comment = data.get('comment', '')

        if not amount or amount <= 0:
            return JsonResponse({'success': False, 'error': 'Введите корректную сумму'})

        if amount > order.debt:
            return JsonResponse({'success': False, 'error': f'Сумма превышает долг ({order.debt} ₽)'})

        if not payment_method:
            return JsonResponse({'success': False, 'error': 'Выберите способ оплаты'})

        payment = order.add_payment(amount, payment_method, request.user, comment)
        log_action(
            request,
            'create',
            'Payment',
            order.id,
            f"Оплата #{payment.id}"
        )
        return JsonResponse({
            'success': True,
            'total_paid': float(order.total_paid),
            'debt': float(order.debt),
            'payment_status': order.payment_status
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def cash_transaction_detail(request, transaction_id):
    transaction = get_object_or_404(CashTransaction, id=transaction_id)
    return JsonResponse({
        'id': transaction.id,
        'created_at': transaction.created_at.strftime('%d.%m.%Y %H:%M'),
        'operation_type_display': transaction.get_operation_type_display(),
        'amount': f"{transaction.amount:,.2f}".replace(',', ' '),
        'payment_method_display': transaction.get_payment_method_display(),
        'reason': transaction.reason,
        'comment': transaction.comment,
        'employee': transaction.employee.get_full_name() or transaction.employee.username if transaction.employee else '—',
        'order': transaction.order.id if transaction.order else None,
        'cash_register': transaction.cash_register.name if transaction.cash_register else '—',
    })

@login_required
def order_print(request, order_id):
    order = get_object_or_404(Order.objects.select_related('customer', 'transport', 'employee'), id=order_id)

    context = {
        'order': order,
        'company_name': 'Spica Bike',
        'company_address': 'г. Казань, ул. Максимова, д. 20',
        'company_phone': '+7 (987) 864-77-80',
        'company_email': 'info@spicabike.ru',
        'current_date': timezone.now(),
    }
    return render(request, 'inventorymanager/order_print.html', context)