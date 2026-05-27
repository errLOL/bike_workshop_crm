from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.db.models import F, Sum
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.urls import reverse

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract=True


class Supplier(models.Model):
    name = models.CharField(max_length=140, null = False)
    contact_name = models.CharField(max_length=75)
    contact_telegram = models.CharField(max_length=75)
    contact_phone = models.CharField(max_length=15)

    def __str__(self):
        return f'{self.name}'

class Category(models.Model):
    name = models.CharField(max_length=140, null = False)
    description = models.CharField(max_length=75)

    def __str__(self):
        return f'{self.name}'
    class Meta:
            verbose_name_plural = "Categories"

class Customer(BaseModel):
    name = models.CharField(max_length=75, null = False)
    telegram = models.CharField(max_length=75, blank=True, null=True)
    phone = models.CharField(max_length=15)

    def formatted_phone(self):
        if not self.phone or len(self.phone) != 11:
            return self.phone
        return f'+{self.phone[0]} ({self.phone[1:4]}) {self.phone[4:7]}-{self.phone[7:9]}-{self.phone[9:11]}'

    def __str__(self):
        return f'{self.name}'
    
class Product(BaseModel):
    PRODUCT_TYPES = [
        ("part", "Запчасть"),
        ("service", "Услуга")
    ]
    name = models.CharField(max_length=140, null = False)
    image = models.ImageField(upload_to='parts/', blank=True, null=True)
    product_type = models.CharField(max_length=48, choices=PRODUCT_TYPES, default="part")
    description = models.CharField(max_length=75, blank=True)
    unit_cost = models.FloatField(null = False)
    quantity_in_stock = models.IntegerField(null=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="products", default="Без категории")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="products", null=True, blank=True)

    def __str__(self):
        return f'{self.name}'


class Transport(BaseModel):
    TRANSPORT_TYPES = [
        ('scooter', 'Электросамокат'),
        ('ebike', 'Электровелосипед'),
        ('bicycle', 'Велосипед'),
        ('monowheel', 'Моноколесо'),
        ('other', 'Другое'),
    ]

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='transports',
        verbose_name='Клиент'
    )
    name = models.CharField(max_length=200, verbose_name='Название/модель')
    serial_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Серийный номер',
        help_text='Уникальный номер рамы или VIN'
    )
    transport_type = models.CharField(
        max_length=100,
        choices=TRANSPORT_TYPES,
        default='bicycle',
        verbose_name='Тип транспорта'
    )
    color = models.CharField(max_length=50, blank=True, null=True, verbose_name='Цвет')
    comment = models.TextField(blank=True, null=True, verbose_name='Комментарий')

    def __str__(self):
        return f"{self.name} ({self.get_transport_type_display()}) - {self.customer.name}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Транспорт'
        verbose_name_plural = 'Транспорт'


class Order(BaseModel):
    STATUS_CHOICES = [
        ('accepted', 'Принят'),
        ('in_work', 'В работе'),
        ('waiting_spareparts', 'Ожидает запчасти'),
        ('ready', 'Готов к выдаче'),
        ('issued', 'Выдан'),
        ('cancelled', 'Отменен'),
    ]
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    employee = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    transport = models.ForeignKey(
        Transport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Транспорт'
    )
    status = models.CharField(max_length=100, choices=STATUS_CHOICES, default='accepted')
    description = models.CharField(
        max_length=800,
        blank=True,
        null=True,
        verbose_name='Причина обращения'
    )
    ompleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата завершения')

    def total_amount(self):
        return sum(item.subtotal() for item in self.order_items.all())

    @property
    def total_paid(self):
        """Сколько уже оплачено по заказу"""
        return self.payments.aggregate(total=Sum('amount'))['total'] or 0

    @property
    def debt(self):
        """Текущий долг клиента"""
        return self.total_amount() - self.total_paid

    @property
    def payment_status(self):
        """Статус оплаты для отображения"""
        if self.debt <= 0:
            return 'paid'
        elif self.total_paid > 0:
            return 'partial'
        else:
            return 'unpaid'

    def add_payment(self,  amount, payment_method, employee, comment='', cash_register=None):
        with transaction.atomic():
            if cash_register is None:
                cash_register = CashRegister.objects.filter(is_active=True).first()

            payment = OrderPayment.objects.create(
                order=self,
                amount=amount,
                payment_method=payment_method,
                employee=employee,
                comment=comment,
            )

            CashTransaction.objects.create(
                order_payment=payment,
                order=self,
                employee=employee,
                operation_type='income',
                amount=amount,
                payment_method=payment_method,
                reason=f"Оплата заказа #{self.id}",
                comment=comment,
                cash_register=cash_register
            )
            return payment

    def __str__(self):
        transport_info = f" - {self.transport.name}" if self.transport else ""
        return f"Заказ #{self.id} от {self.created_at.strftime('%d.%m.%Y')}{transport_info}"


class TransportImage(BaseModel):
    transport = models.ForeignKey(
        Transport,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Транспорт'
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transport_images',
        verbose_name='Заказ (в котором добавили фото)'
    )
    image = models.ImageField(
        upload_to='transport_photos/%Y/%m/%d/',
        verbose_name='Фото'
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name='Описание'
    )
    uploaded_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Кто загрузил'
    )

    def __str__(self):
        return f"Фото {self.transport.name} - {self.created_at.strftime('%d.%m.%Y')}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Фото транспорта'
        verbose_name_plural = 'Фотографии транспорта'

class OrderItem(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="product_items")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="order_items")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def subtotal(self):
        """Calculate the total price for this order item"""
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        if not self.unit_price and self.product:
            self.unit_price = self.product.unit_cost
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OrderItem for product {self.product.name} with quantity {self.quantity}"


class CashRegister(models.Model):
    name = models.CharField(max_length=100, verbose_name='Название кассы')
    location = models.CharField(max_length=200, blank=True, null=True, verbose_name='Расположение')
    is_active = models.BooleanField(default=True, verbose_name='Активна')
    initial_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Начальный остаток')
    created_at = models.DateTimeField(auto_now_add=True)

    def current_balance(self):
        transactions = self.transactions.all()
        income = transactions.filter(operation_type='income').aggregate(total=Sum('amount'))['total'] or 0
        expense = transactions.filter(operation_type='expense').aggregate(total=Sum('amount'))['total'] or 0
        return self.initial_balance + income - expense

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Касса'
        verbose_name_plural = 'Кассы'


class CashTransaction(models.Model):
    OPERATION_TYPES = [
        ('income', 'Приход'),
        ('expense', 'Расход'),
    ]

    PAYMENT_METHODS = [
        ('cash', 'Наличные'),
        ('card', 'Карта'),
        ('transfer', 'Перевод'),
    ]
    cash_register = models.ForeignKey(CashRegister, on_delete=models.CASCADE, related_name='transactions', verbose_name='Касса')
    order_payment = models.OneToOneField('OrderPayment', on_delete=models.CASCADE, null=True, blank=True, related_name='cash_transaction', verbose_name='Оплата заказа')
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Заказ (для расходов)')
    employee = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, related_name='cash_transactions', verbose_name='Сотрудник')
    operation_type = models.CharField(max_length=10, choices=OPERATION_TYPES, verbose_name='Тип операции')
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Сумма')
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, verbose_name='Способ оплаты')
    reason = models.CharField(max_length=200, verbose_name='Основание')
    comment = models.TextField(blank=True, null=True, verbose_name='Комментарий')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата операции')

    def __str__(self):
        return f"{self.get_operation_type_display()} - {self.amount}₽ - {self.reason}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Кассовая операция'
        verbose_name_plural = 'Кассовые операции'


class OrderPayment(models.Model):
    PAYMENT_METHODS = [
        ('cash', 'Наличные'),
        ('card', 'Карта'),
        ('transfer', 'Перевод'),
        ('online', 'Онлайн'),
    ]

    order = models.ForeignKey('Order', on_delete=models.CASCADE, related_name='payments', verbose_name='Заказ')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Сумма')
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, verbose_name='Способ оплаты')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата оплаты')
    employee = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, verbose_name='Принял оплату')
    comment = models.CharField(max_length=200, blank=True, verbose_name='Комментарий')

    def __str__(self):
        return f"Заказ #{self.order.id} - {self.amount}₽"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Оплата заказа'
        verbose_name_plural = 'Оплаты заказов'


class ActionLog(BaseModel):
    ACTION_TYPES = [
        ('create', 'Создание'),
        ('edit', 'Редактирование'),
        ('delete', 'Удаление'),
        ('status_change', 'Смена статуса'),
        ('payment', 'Оплата'),
        ('stock_change', 'Изменение склада'),
        ('login', 'Вход в систему'),
        ('logout', 'Выход'),
    ]

    user = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, verbose_name='Пользователь')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES, verbose_name='Тип действия')
    model_name = models.CharField(max_length=100, verbose_name='Модель')
    object_id = models.IntegerField(null=True, blank=True, verbose_name='ID объекта')
    object_repr = models.CharField(max_length=200, verbose_name='Объект')
    changes = models.JSONField(default=dict, verbose_name='Изменения')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP адрес')

    def get_absolute_url(self):
        """Возвращает ссылку на просмотр объекта"""
        if self.model_name == 'Order' and self.object_id:
            return reverse('order_detail', args=[self.object_id])
        elif self.model_name == 'Customer' and self.object_id:
            return reverse('customer_detail', args=[self.object_id])
        elif self.model_name == 'Product' and self.object_id:
            return reverse('product_detail', args=[self.object_id])
        return '#'

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Лог действия'
        verbose_name_plural = 'Логи действий'