from django.urls import path
from . import views
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    path('login/', views.login_view, name='login'),
    path('demo-login/', views.demo_login_view, name='demo_login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),

    # Password Reset URLs (Django built-in)
    path('password-reset/', PasswordResetView.as_view(template_name='password_reset_form.html'), name='password_reset'),
    path('password-reset/done/', PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset/complete/', PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),

    # Profile URLs
    path('profile/', views.employee_profile, name='employee_profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/change-password/', views.change_password_view, name='change_password'),

    path('leave/apply/', views.apply_leave, name='apply_leave'),
    path('leave/view/', views.view_leaves, name='view_leaves'),
    path('leave/approve/<int:leave_id>/', views.approve_leave, name='approve_leave'),
    path('leave/reject/<int:leave_id>/', views.reject_leave, name='reject_leave'),
    path('leave/calendar/', views.leave_calendar, name='leave_calendar'),

    path('attendance/', views.attendance_history, name='attendance_history'),
    path('attendance/approvals/', views.attendance_approvals, name='attendance_approvals'),
    path('attendance/approve/<int:attendance_id>/', views.approve_attendance, name='approve_attendance'),
    path('attendance/reject/<int:attendance_id>/', views.reject_attendance, name='reject_attendance'),

    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('inventory/', views.inventory_dashboard, name='inventory_dashboard'),

    path('customers/', views.customer_list, name='customer_list'),
    path('customers/add/', views.add_customer, name='add_customer'),

    path('upload/', views.upload_file, name='upload_file'),

    # Feature 2: Notifications
    path('notifications/', views.notifications_list, name='notifications_list'),
    path('notifications/<int:notification_id>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),

    # Feature 3: Search
    path('search/', views.global_search, name='global_search'),

    # Feature 4: Activity Log
    path('activity-log/', views.activity_log, name='activity_log'),
]