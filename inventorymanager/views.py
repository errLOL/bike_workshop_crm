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
from django.db.models import Sum, F, Q, Count, Avg
import json

from .utils import calculate_all_technicians_salary, calculate_technician_salary

@require_admin
def admin_dashboard(request):
    # Authenticated users view the Dashboard

    months_ru = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }

    if request.user.is_authenticated:
        low_stock = Product.objects.filter(quantity_in_stock__lte=3)

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
            OrderItem.objects.values("product__name")
            .annotate(total_quantity_sold=Sum("quantity"))
            .order_by("-total_quantity_sold")[:3]
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
            .order_by("-total_spending")[:3]
        )

        customer_orders_labels = [
            f"{item['order__customer__name']} {item['order__customer__phone']}"
            for item in customer_orders
        ]
        customer_orders_data = [
            float(item["total_spending"]) for item in customer_orders
        ]

        context = {
            "low_stock": low_stock.count(),
            "products_total": product_total_cost,
            "orders_total": orders_total,
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
    """Дашборд техника — активные заказы и быстрая статистика"""
    user = request.user
    salary_percent = 40

    # Быстрая статистика за сегодня/неделю (маленький виджет)
    today = timezone.now().replace(hour=0, minute=0, second=0)

    # Выручка от услуг за сегодня
    today_services = OrderItem.objects.filter(
        order__employee=user,
        order__status='issued',
        order__updated_at__gte=today,
        product__product_type='service'
    ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

    # Мои активные заказы
    my_active_orders = Order.objects.filter(
        employee=user
    ).filter(
        Q(status='accepted') | Q(status='in_work')
    ).select_related('customer', 'transport').order_by('-created_at')[:10]

    # Заказы, ожидающие запчасти
    awaiting_parts = Order.objects.filter(
        employee=user,
        status='waiting_spareparts'
    ).select_related('customer', 'transport', 'employee').order_by('-created_at')[:10]

    # Завершенные заказы за неделю
    week_ago = timezone.now() - timedelta(days=7)
    my_completed_orders = Order.objects.filter(
        employee=user,
        status='issued',
        created_at__gte=week_ago
    ).select_related('customer', 'transport').order_by('-created_at')

    # Добавляем доход техника для каждого заказа
    for order in my_completed_orders:
        services_total = order.order_items.filter(product__product_type='service').aggregate(
            total=Sum(F('quantity') * F('unit_price'))
        )['total'] or 0
        order.technician_earnings = services_total * Decimal(salary_percent / 100)

    # Статистика
    total_my_orders = Order.objects.filter(employee=user).count()
    my_completed_count = Order.objects.filter(employee=user, status='issued').count()
    my_in_progress_count = Order.objects.filter(employee=user, status='in_work').count()
    my_awaiting_parts_count = Order.objects.filter(employee=user, status='waiting_spareparts').count()

    if total_my_orders > 0:
        completion_rate = round((my_completed_count / total_my_orders) * 100, 1)
    else:
        completion_rate = 0

    avg_order_value = Order.objects.filter(employee=user, status='issued').aggregate(
        avg=Avg(F('order_items__quantity') * F('order_items__unit_price'))
    )['avg'] or 0

    # Уникальные клиенты
    unique_customers_count = Order.objects.filter(employee=user).values('customer').distinct().count()
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
    """Роутер для дашборда — перенаправляет на нужную версию"""
    if request.user.is_superuser or request.user.groups.filter(name='Admin').exists():
        return redirect('admin_dashboard')
    else:
        return redirect('technician_dashboard')


def login_view(request):
    if request.method == "POST":

        # Attempt to sign user in
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
                {"message": "Invalid email and/or password."},
            )
    else:
        return render(request, "inventorymanager/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")

@require_admin
@login_required
def salary_report(request):
    """Отчёт по зарплатам техников с графиками и выбором периода"""
    User = get_user_model()
    # Параметры периода
    period_type = request.GET.get('period', 'month')
    selected_date = request.GET.get('date')

    # Получаем список всех техников
    technicians = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name='Technician')
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

    # Определяем дату начала и конца периода
    if selected_date:
        if period_type == 'week':
            current_date = datetime.strptime(selected_date, '%Y-%m-%d')
        elif period_type == 'month':
            current_date = datetime.strptime(selected_date, '%Y-%m')
        elif period_type == 'quarter':
            year, quarter = selected_date.split('-Q')
            year = int(year)
            quarter = int(quarter)
            month = (quarter - 1) * 3 + 1
            current_date = date(year, month, 1)
        else:  # year
            current_date = datetime.strptime(selected_date, '%Y')
    else:
        current_date = timezone.now()

    # Рассчитываем start_date и end_date
    if period_type == 'week':
        start_date = current_date - timedelta(days=current_date.weekday())
        end_date = start_date + timedelta(days=6)
        period_label = f"Неделя {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"

        # Данные для графика по дням
        chart_labels = []
        chart_services_data = []
        chart_salary_data = []

        for i in range(7):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
            chart_labels.append(day_start.strftime('%a, %d.%m'))

            day_services = OrderItem.objects.filter(
                order__status='issued',
                order__created_at__gte=day_start,
                order__created_at__lte=day_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(day_services))
            chart_salary_data.append(float(day_services))  # TODO: посчитать зарплату по техникам

    elif period_type == 'month':
        start_date = current_date.replace(day=1, hour=0, minute=0, second=0)
        last_day = monthrange(current_date.year, current_date.month)[1]
        end_date = current_date.replace(day=last_day, hour=23, minute=59, second=59)
        period_label = f"Месяц {current_date.strftime('%B %Y')}"

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
                order__created_at__gte=week_start,
                order__created_at__lte=week_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(week_services))
            chart_salary_data.append(float(week_services))

    elif period_type == 'quarter':
        quarter = (current_date.month - 1) // 3 + 1
        start_date = current_date.replace(month=(quarter - 1) * 3 + 1, day=1)
        if quarter == 4:
            end_date = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_date = current_date.replace(month=quarter * 3 + 1, day=1) - timedelta(days=1)
        period_label = f"Квартал {quarter} {current_date.year}"

        # Данные для графика по месяцам
        chart_labels = [f"{i+1} месяц" for i in range(3)]
        chart_services_data = []
        chart_salary_data = []

        for i in range(3):
            month_start = start_date + relativedelta(months=i)
            month_end = month_start + relativedelta(months=1) - timedelta(days=1)

            month_services = OrderItem.objects.filter(
                order__status='issued',
                order__created_at__gte=month_start,
                order__created_at__lte=month_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(month_services))
            chart_salary_data.append(float(month_services))

    else:  # year
        start_date = current_date.replace(month=1, day=1)
        end_date = current_date.replace(month=12, day=31)
        period_label = f"Год {current_date.year}"

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
                order__created_at__gte=month_start,
                order__created_at__lte=month_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(month_services))
            chart_salary_data.append(float(month_services))

    end_date = end_date.replace(hour=23, minute=59, second=59)
    start_date = start_date.replace(hour=0, minute=0, second=0)

    # Собираем данные по каждому технику
    salary_data = []
    total_services_all = 0
    total_salary_all = 0
    technician_services = {}  # для графика по техникам

    for tech in technicians:
        percent = technician_percents.get(tech.id, 40)

        # Выручка от услуг за период
        services_total = OrderItem.objects.filter(
            order__employee=tech,
            order__status='issued',
            order__created_at__gte=start_date,
            order__created_at__lte=end_date,
            product__product_type='service'
        ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

        salary = services_total * Decimal(percent / 100)

        orders_count = Order.objects.filter(
            employee=tech,
            status='issued',
            created_at__gte=start_date,
            created_at__lte=end_date
        ).count()

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
    avg_order_value = services_total / orders_count if orders_count > 0 else 0
    # Собираем доступные даты для селектов
    available_weeks = []
    available_months = []
    available_quarters = []
    available_years = []

    order_dates = Order.objects.filter(
        status='issued'
    ).order_by('created_at')

    if order_dates.exists():
        first_order = order_dates.first().created_at
        last_order = order_dates.last().created_at

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
            quarter = (order.created_at.month - 1) // 3 + 1
            quarter_key = f"{order.created_at.year}-Q{quarter}"
            if quarter_key not in quarters_seen:
                quarters_seen.add(quarter_key)
                available_quarters.append({
                    'value': quarter_key,
                    'label': f"{order.created_at.year} - Квартал {quarter}"
                })

        # Годы
        years_seen = set()
        for order in order_dates:
            if order.created_at.year not in years_seen:
                years_seen.add(order.created_at.year)
                available_years.append({
                    'value': str(order.created_at.year),
                    'label': str(order.created_at.year)
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

    if selected_date:
        if period_type == 'week':
            current_date = datetime.strptime(selected_date, '%Y-%m-%d')
        elif period_type == 'month':
            current_date = datetime.strptime(selected_date, '%Y-%m')
        elif period_type == 'quarter':
            year, quarter = selected_date.split('-Q')
            year = int(year)
            quarter = int(quarter)
            month = (quarter - 1) * 3 + 1
            current_date = date(year, month, 1)
        else:  # year
            current_date = datetime.strptime(selected_date, '%Y')
    else:
        current_date = timezone.now()

    # Рассчитываем start_date и end_date
    if period_type == 'week':
        start_date = current_date - timedelta(days=current_date.weekday())
        end_date = start_date + timedelta(days=6)
        period_label = f"Неделя {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"

        # Для графика нужны дни недели
        chart_labels = []
        for i in range(7):
            day = start_date + timedelta(days=i)
            chart_labels.append(day.strftime('%a, %d.%m'))
    elif period_type == 'month':
        start_date = current_date.replace(day=1, hour=0, minute=0, second=0)
        last_day = monthrange(current_date.year, current_date.month)[1]
        end_date = current_date.replace(day=last_day, hour=23, minute=59, second=59)
        period_label = f"Месяц {current_date.strftime('%B %Y')}"

        # Для графика нужны недели месяца
        chart_labels = [f"{i+1}-я неделя" for i in range(4)]
    elif period_type == 'quarter':
        quarter = (current_date.month - 1) // 3 + 1
        start_date = current_date.replace(month=(quarter - 1) * 3 + 1, day=1)
        if quarter == 4:
            end_date = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_date = current_date.replace(month=quarter * 3 + 1, day=1) - timedelta(days=1)
        period_label = f"Квартал {quarter} {current_date.year}"

        # Для графика нужны месяцы квартала
        months_in_quarter = [f"{m} месяц" for m in range(1, 4)]
        chart_labels = months_in_quarter
    else:  # year
        start_date = current_date.replace(month=1, day=1)
        end_date = current_date.replace(month=12, day=31)
        period_label = f"Год {current_date.year}"

        # Для графика нужны месяцы года
        chart_labels = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

    end_date = end_date.replace(hour=23, minute=59, second=59)
    start_date = start_date.replace(hour=0, minute=0, second=0)

    # Данные для графика
    chart_services_data = []
    chart_salary_data = []

    if period_type == 'week':
        # Понедельная детализация по дням
        for i in range(7):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1) - timedelta(seconds=1)

            day_services = OrderItem.objects.filter(
                order__employee=user,
                order__status='issued',
                order__created_at__gte=day_start,
                order__created_at__lte=day_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(day_services))
            chart_salary_data.append(float(day_services * Decimal(salary_percent / 100)))

    elif period_type == 'month':
        # Помесячная детализация по неделям
        days_in_month = (end_date - start_date).days + 1
        week_size = days_in_month // 4
        for week_num in range(4):
            week_start = start_date + timedelta(days=week_num * week_size)
            if week_num == 3:
                week_end = end_date
            else:
                week_end = start_date + timedelta(days=(week_num + 1) * week_size - 1)

            week_services = OrderItem.objects.filter(
                order__employee=user,
                order__status='issued',
                order__created_at__gte=week_start,
                order__created_at__lte=week_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(week_services))
            chart_salary_data.append(float(week_services * Decimal(salary_percent / 100)))

    elif period_type == 'quarter':
        # Поквартальная детализация по месяцам
        for i in range(3):
            month_start = start_date + relativedelta(months=i)
            month_end = month_start + relativedelta(months=1) - timedelta(days=1)

            month_services = OrderItem.objects.filter(
                order__employee=user,
                order__status='issued',
                order__created_at__gte=month_start,
                order__created_at__lte=month_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(month_services))
            chart_salary_data.append(float(month_services * Decimal(salary_percent / 100)))

    else:  # year
        # Годовая детализация по месяцам
        for i in range(12):
            month_start = start_date.replace(month=i+1)
            if i+1 == 12:
                month_end = month_start.replace(month=12, day=31)
            else:
                month_end = month_start.replace(month=i+2, day=1) - timedelta(days=1)

            month_services = OrderItem.objects.filter(
                order__employee=user,
                order__status='issued',
                order__created_at__gte=month_start,
                order__created_at__lte=month_end,
                product__product_type='service'
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or 0

            chart_services_data.append(float(month_services))
            chart_salary_data.append(float(month_services * Decimal(salary_percent / 100)))

    # Итоги за период
    period_services_total = sum(chart_services_data)
    period_salary = period_services_total * (salary_percent / 100)
    period_orders_count = Order.objects.filter(
        employee=user,
        status='issued',
        created_at__gte=start_date,
        created_at__lte=end_date
    ).count()

    # Список доступных дат для селектов
    available_weeks = []
    available_months = []
    available_quarters = []
    available_years = []

    # Собираем доступные периоды из заказов техника
    order_dates = Order.objects.filter(employee=user).order_by('created_at')

    if order_dates.exists():
        first_order = order_dates.first().created_at
        last_order = order_dates.last().created_at

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
            quarter = (order.created_at.month - 1) // 3 + 1
            quarter_key = f"{order.created_at.year}-Q{quarter}"
            if quarter_key not in quarters_seen:
                quarters_seen.add(quarter_key)
                available_quarters.append({
                    'value': quarter_key,
                    'label': f"{order.created_at.year} - Квартал {quarter}"
                })

        # Годы
        years_seen = set()
        for order in order_dates:
            if order.created_at.year not in years_seen:
                years_seen.add(order.created_at.year)
                available_years.append({
                    'value': str(order.created_at.year),
                    'label': str(order.created_at.year)
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

            # Если есть параметр next, редиректим туда
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
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
                return redirect(next_url)
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
    orders = Order.objects.select_related(
        'customer',
        'transport',
        'employee'
    ).prefetch_related(
        'order_items__product'
    ).annotate(
        total_value=Sum(F('order_items__quantity') * F('order_items__unit_price'))
    ).order_by('-created_at')

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

    # Фильтр по дате (от)
    date_from = request.GET.get('date_from', '')
    if date_from:
        orders = orders.filter(created_at__date__gte=date_from)

    # Фильтр по дате (до)
    date_to = request.GET.get('date_to', '')
    if date_to:
        orders = orders.filter(created_at__date__lte=date_to)

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
    }

    return render(request, 'inventorymanager/orders.html', context)


@login_required
def create_order(request):
    products = Product.objects.all().order_by('product_type', 'name')
    customers = Customer.objects.all().order_by('name')
    transports = Transport.objects.select_related('customer').all().order_by('-created_at')

    if request.method == 'POST':
        form = OrderForm(request.POST)
        formset = OrderItemFormSet(request.POST)
        initial_customer = request.POST.get('customer')
        initial_transport = request.POST.get('transport')

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                customer_id = initial_customer
                transport_id = initial_transport
                if not customer_id or not transport_id:
                    messages.error(request, 'Выберите клиента' if not customer_id else 'Выберите технику')
                    return render(request, 'inventory/createOrder.html', {
                                                                            'form': form,
                                                                            'formset': formset,
                                                                            'products': products,
                                                                            'customers': customers,
                                                                            'transports': transports,
                                                                            'initial_customer': initial_customer or '',
                                                                            'initial_transport': transport_id or '',
                                                                            'title': 'Создание заказа',
                                                                        })

                customer = get_object_or_404(Customer, id=customer_id)
                transport = get_object_or_404(Transport, id=transport_id)
                order = form.save(commit=False)
                order.customer = customer
                order.transport = transport
                order.employee = request.user
                order.save()

                # Сохраняем позиции заказа (OrderItem)
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
        'initial_customer': initial_customer or '',
        'initial_transport': initial_transport or '',
        'title': 'Создание заказа',
    }
    return render(request, 'inventorymanager/createOrder.html', context)


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
@require_order_access
def edit_order(request, order):
    customers = Customer.objects.all().order_by('name')
    transports = Transport.objects.select_related('customer').all()
    products = Product.objects.all().order_by('product_type', 'name')

    if request.method == 'POST':
        if order.status in ('in_work', 'ready'):
            old_items = {
                item.product_id: item.quantity
                for item in order.order_items.select_related('product').all()
                if item.product.product_type == 'part'
            }
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                # 1. Сохраняем заказ
                order = form.save(commit=False)
                customer_id = request.POST.get('customer')
                transport_id = request.POST.get('transport')
                if customer_id:
                    order.customer_id = customer_id
                if transport_id:
                    order.transport_id = transport_id
                order.save()

                formset.instance = order
                formset.save()

                if order.status in ('in_work', 'ready'):
                    # Используем логику DIFF для корректировки склада
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
                        print(old_qty, new_qty, diff)

                        if diff == 0:
                            continue

                        product = Product.objects.select_for_update().get(id=product_id)

                        if diff > 0:
                            # ➖ списание
                            if product.quantity_in_stock < diff:
                                messages.error(request,
                                    f'Недостаточно "{product.name}". '
                                    f'Доступно: {product.quantity_in_stock}, нужно: {diff}'
                                )
                                return redirect('order_detail', order_id=order.id)
                            product.quantity_in_stock = F('quantity_in_stock') - diff
                        else:
                            # ➕ возврат
                            product.quantity_in_stock = F('quantity_in_stock') + abs(diff)

                        product.save()

                    messages.success(request, f'Заказ #{order.id} обновлён')
                    return redirect('order_detail', order_id=order.id)
    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order)

    return render(request, 'inventorymanager/editOrder.html', {
        'form': form,
        'formset': formset,
        'order': order,
        'customers': customers,
        'transports': transports,
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
        order.delete()
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
        return redirect('orders')

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

    order.status = status
    order.save()
    messages.success(request, f'Заказ #{order.id} отмечен как "{order.get_status_display()}"')
    return redirect('orders')


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
    """Список кассовых операций"""
    # Определяем текущую кассу (по умолчанию первую активную)
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
    """Создание кассовой операции"""
    if request.method == 'POST':
        form = CashTransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.employee = request.user
            transaction.save()
            messages.success(request, f'Операция "{transaction.reason}" создана')
            return redirect('cash_register_list')
    else:
        # Предзаполнение кассы
        initial = {}
        cash_register = CashRegister.objects.filter(is_active=True).first()
        if cash_register:
            initial['cash_register'] = cash_register.id
        form = CashTransactionForm(initial=initial)

    return render(request, 'inventorymanager/cash_transaction_form.html', {'form': form, 'title': 'Новая операция'})


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
    """AJAX-обработчик для добавления оплаты через модалку"""
    order = get_object_or_404(Order, pk=order_id)
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount')))
        payment_method = data.get('payment_method')
        comment = data.get('comment', '')

        # Валидация
        if not amount or amount <= 0:
            return JsonResponse({'success': False, 'error': 'Введите корректную сумму'})

        if amount > order.debt:
            return JsonResponse({'success': False, 'error': f'Сумма превышает долг ({order.debt} ₽)'})

        if not payment_method:
            return JsonResponse({'success': False, 'error': 'Выберите способ оплаты'})

        # Добавляем оплату
        order.add_payment(amount, payment_method, request.user, comment)

        return JsonResponse({
            'success': True,
            'total_paid': float(order.total_paid),
            'debt': float(order.debt),
            'payment_status': order.payment_status
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})