from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard_router, name="index"),
    path('admin-dashboard', views.admin_dashboard, name='admin_dashboard'),
    path('dashboard', views.technician_dashboard, name='technician_dashboard'),
    path('action_logs', views.action_logs, name='action_logs'),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("my_salary", views.my_salary, name="my_salary"),
    path("salary_report", views.salary_report, name="salary_report"),
    path("suppliers", views.supplier_view, name="suppliers"),
    path("customers", views.customer_view, name="customers"),
    path("transports", views.transport_view, name="transports"),
    path("products", views.product_view, name="products"),
    path("orders", views.order_list, name="orders"),
    path("categories", views.category_view, name="categories"),
    path("casher", views.cash_register_list, name="cash_register_list"),
    path("create_customer", views.create_customer, name="create_customer"),
    path("cash_transaction_create", views.cash_transaction_create, name="cash_transaction_create"),
    path("create_supplier", views.create_supplier, name="create_supplier"),
    path("create_transport", views.create_transport, name="create_transport"),
    path("create_product", views.create_product, name="create_product"),
    path("create_order", views.create_order, name="create_order"),
    path("create_category", views.create_category, name="create_category"),
    path('upload_transport_photo/<int:transport_id>', views.upload_transport_photo, name='upload_transport_photo'),
    # path('api/customers/create/', views.api_create_customer, name='api_create_customer'),
    # path('api/transports/create/', views.api_create_transport, name='api_create_transport'),
    # Detail urls
    path('supplier/<int:id>', views.supplier_detail, name='supplier_detail'),
    path('customer/<int:customer_id>', views.customer_detail, name='customer_detail'),
    path('product/<int:product_id>', views.product_detail, name='product_detail'),
    path('order/<int:order_id>', views.order_detail, name='order_detail'),
    path("order_add_payment/<int:order_id>", views.order_add_payment, name="order_add_payment"),
    path('category/<int:id>', views.category_detail, name='category_detail'),
    path('transport_detail/<int:transport_id>', views.transport_detail, name='transport_detail'),
    # Edit urls
    path("cash_register_close_shift/<int:register_id>", views.cash_register_close_shift, name="cash_register_close_shift"),
    path('edit_supplier/<int:id>', views.edit_supplier, name='edit_supplier'),
    path('edit_customer/<int:customer_id>', views.edit_customer, name='edit_customer'),
    path('edit_order/<int:order_id>', views.edit_order, name='edit_order'),
    path('edit_product/<int:product_id>', views.edit_product, name='edit_product'),
    path('edit_category/<int:id>', views.edit_category, name='edit_category'),
    path('edit_transport/<int:transport_id>', views.edit_transport, name='edit_transport'),
    # Cancel url
    path('cancel_order_update/<int:order_id>', views.cancel_order_update, name='cancel_order_update'),
    path('change_order_status/<int:order_id>', views.change_order_status, name='change_order_status'),
    # Delete urls
    path('delete_supplier/<int:id>/', views.delete_supplier, name='delete_supplier'),
    path('delete_customer/<int:id>/', views.delete_customer, name='delete_customer'),
    path('delete_product/<int:id>/', views.delete_product, name='delete_product'),
    path('delete_order/<int:id>/', views.delete_order, name='delete_order'),
    path('delete_category/<int:id>/', views.delete_category, name='delete_category'),

    












]