from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from functools import wraps
from .models import Order


def is_admin(user):
    """Проверка, является ли пользователь администратором"""
    return user.is_superuser or user.groups.filter(name='Admin').exists()


def is_technician(user):
    """Проверка, является ли пользователь техником (или администратором)"""
    return user.is_superuser or user.groups.filter(name='Technician').exists() or is_admin(user)


def require_admin(view_func):
    """Декоратор: доступ только для администраторов"""
    decorated = user_passes_test(is_admin, login_url='login')(view_func)
    return wraps(view_func)(decorated)


def require_technician(view_func):
    """Декоратор: доступ для техников и администраторов"""
    decorated = user_passes_test(is_technician, login_url='login')(view_func)
    return wraps(view_func)(decorated)


def require_order_access(view_func):
    """
    Декоратор: проверяет, что пользователь имеет доступ к заказу
    (свой заказ для техника, любой заказ для администратора)
    """
    @wraps(view_func)
    def wrapper(request, order_id=None, *args, **kwargs):
        order = (Order.objects
         .select_related('customer', 'transport', 'employee')
         .prefetch_related('order_items__product')
         .filter(id=order_id)
         .first())
        if not order:
            raise PermissionDenied("Заказ не найден")

        # Администратор имеет доступ ко всем заказам
        if is_admin(request.user):
            return view_func(request, order, *args, **kwargs)

        # Техник имеет доступ только к своим заказам
        if order.employee == request.user:
            return view_func(request, order, *args, **kwargs)

        raise PermissionDenied("У вас нет доступа к этому заказу")
    return wrapper
