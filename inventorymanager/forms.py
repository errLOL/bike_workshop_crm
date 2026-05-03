import re

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Field
from django.forms import inlineformset_factory, Select
from django import forms
from .models import *


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = "__all__"
    
    # def __init__(self, *args, **kwargs):
    #     super(SupplierForm, self).__init__(*args, **kwargs)
    #     # Set specific fields as not required
    #     self.fields['contact_name'].required = False
    #     self.fields['contact_email'].required = False
    #     self.fields['contact_phone'].required = False

class CustomerForm(forms.ModelForm):
    phone = forms.CharField(
        max_length=20,
        required=False,
        label='Телефон',
        help_text='Формат: +7 (XXX) XXX-XX-XX',
        widget=forms.TextInput(attrs={
            'class': 'phone-mask',
            'placeholder': '+7 (___) ___-__-__'
        })
    )

    class Meta:
        model = Customer
        fields = "__all__"
        labels = {
            'name': 'Имя',
            'telegram': 'Telegram (без @)',
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '')
        if not phone:
            return ''

        digits = re.sub(r'\D', '', phone)

        if len(digits) == 11 and digits[0] in ['7', '8']:
            if digits[0] == '8':
                digits = '7' + digits[1:]
            return digits
        elif len(digits) == 10:
            return '7' + digits
        else:
            raise forms.ValidationError('Некорректный номер телефона')


class TransportForm(forms.ModelForm):
    class Meta:
        model = Transport
        fields = "__all__"


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"
        # exclude = ['image',]
        labels = {
            'name': 'Название товара',
            'description': 'Описание',
            'product_type': 'Тип',
            'category': 'Категория',
            'supplier': 'Поставщик',
            'unit_cost': 'Цена (₽)',
            'quantity_in_stock': 'Количество на складе',
            'image': 'Изображение',
        }

    def clean_unit_cost(self):
        unit_cost = self.cleaned_data.get('unit_cost')
        if unit_cost is not None and unit_cost < 0:
            raise forms.ValidationError('Unit cost must be greater than or equal to zero')
        return unit_cost

    def clean_quantity_in_stock(self):
        quantity_in_stock = self.cleaned_data.get('quantity_in_stock')
        if quantity_in_stock is not None and quantity_in_stock < 0:
            raise forms.ValidationError('Quantity in stock must be greater than or equal to zero')
        return quantity_in_stock

    def __init__(self, *args, **kwargs):
        super(ProductForm, self).__init__(*args, **kwargs)
        self.fields['category'].required = False
        self.fields['supplier'].required = False

class OrderForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        # Если есть поле employee, добавляем его в layout
        # self.helper.layout = Layout(
            # Field('employee', wrapper_class='mb-3'),
            # другие crispy-поля, если есть
        # )

    class Meta:
        model = Order
        fields = ['status']
        labels = {'status': 'Статус'}


class OrderItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False

        self.fields['product'].queryset = Product.objects.all()
        self.fields['product'].widget.attrs.update({
            'class': 'product-select form-select',
            'data-price': 'true'
        })
        self.fields['quantity'].widget.attrs.update({
            'min': 1,
            'class': 'quantity-input form-control',
            'value': 1
        })

    class Meta:
        model = OrderItem
        fields = ['product', 'quantity']
        labels = {
            'product': 'Товар/услуга',
            'quantity': 'Количество',
        }

    def clean_unit_price(self):
        unit_price = self.cleaned_data.get('unit_price')
        if not unit_price or unit_price < 0:
            raise forms.ValidationError('Unit price must be greater than or equal to zero')
        return unit_price

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        product = self.cleaned_data.get('product')
        
        if not quantity or quantity < 0:
            raise forms.ValidationError('Quantity must be greater than or equal to zero')

        if product and product.product_type == 'part':
            current_quantity = self.instance.quantity if self.instance.pk else 0
            available = product.quantity_in_stock + current_quantity

            if quantity > available:
                raise forms.ValidationError(
                    f'Недостаточно {product.name} на складе. Доступно: {available} шт.'
                )

        return quantity

OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
    error_messages={
        'min_num': 'Добавьте хотя бы одну позицию в заказ',
    }
)

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = "__all__"


class CashTransactionForm(forms.ModelForm):
    class Meta:
        model = CashTransaction
        fields = ['operation_type', 'amount', 'payment_method', 'reason', 'comment', 'order', 'cash_register']
        widgets = {
            'comment': forms.Textarea(attrs={'rows': 3}),
            'order': forms.Select(attrs={'class': 'form-select'}),
            'cash_register': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'operation_type': 'Тип операции',
            'amount': 'Сумма (₽)',
            'payment_method': 'Способ оплаты',
            'reason': 'Основание',
            'comment': 'Комментарий',
            'order': 'Заказ (опционально)',
            'cash_register': 'Касса',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False

        # Ограничиваем выбор заказов только незакрытыми
        self.fields['order'].queryset = Order.objects.filter(status__in=['draft', 'in_progress', 'awaiting_parts'])


class CashRegisterForm(forms.ModelForm):
    class Meta:
        model = CashRegister
        fields = ['name', 'location', 'is_active', 'initial_balance']
        labels = {
            'name': 'Название кассы',
            'location': 'Расположение',
            'is_active': 'Активна',
            'initial_balance': 'Начальный остаток (₽)',
        }


class OrderPaymentForm(forms.ModelForm):
    class Meta:
        model = OrderPayment
        fields = ['amount', 'payment_method', 'comment']
        labels = {
            'amount': 'Сумма оплаты (₽)',
            'payment_method': 'Способ оплаты',
            'comment': 'Комментарий',
        }
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'comment': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: предоплата 50%'}),
        }

class TransportImageForm(forms.ModelForm):
    class Meta:
        model = TransportImage
        fields = ['image', 'description']
        labels = {
            'image': 'Фото',
            'description': 'Описание',
        }
        widgets = {
            'image': forms.ClearableFileInput(attrs={
                'accept': 'image/*',
                'capture': 'environment',
                'class': 'form-control'
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Например: повреждение рамы, серийный номер...'
            }),
        }