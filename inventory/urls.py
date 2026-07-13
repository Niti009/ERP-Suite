from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),

    path('leave/apply/', views.apply_leave, name='apply_leave'),
    path('leave/view/', views.view_leaves, name='view_leaves'),
    path('leave/approve/<int:leave_id>/', views.approve_leave, name='approve_leave'),
    path('leave/reject/<int:leave_id>/', views.reject_leave, name='reject_leave'),

    path('attendance/', views.attendance_history, name='attendance_history'),
    path('profile/', views.employee_profile, name='employee_profile'),

    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),

    path('customers/', views.customer_list, name='customer_list'),
    path('customers/add/', views.add_customer, name='add_customer'),

    path('upload/', views.upload_file, name='upload_file'),
]