from .models import LeaveApplication
from django.urls import reverse


BREADCRUMB_ROUTES = {
    "dashboard": [("Home", None)],
    "employee_profile": [("Home", "dashboard"), ("My Work", None), ("My Profile", None)],
    "edit_profile": [("Home", "dashboard"), ("My Work", None), ("My Profile", "employee_profile"), ("Edit Profile", None)],
    "change_password": [("Home", "dashboard"), ("My Work", None), ("Account", "employee_profile"), ("Change Password", None)],
    "employee_list": [("Home", "dashboard"), ("People", None), ("Employees", None)],
    "employee_create": [("Home", "dashboard"), ("People", None), ("Employees", "employee_list"), ("Add Employee", None)],
    "employee_detail": [("Home", "dashboard"), ("People", None), ("Employees", "employee_list"), ("Employee Details", None)],
    "employee_edit": [("Home", "dashboard"), ("People", None), ("Employees", "employee_list"), ("Edit Employee", None)],
    "attendance_history": [("Home", "dashboard"), ("My Work", None), ("My Attendance", None)],
    "attendance_approvals": [("Home", "dashboard"), ("People", None), ("Attendance", None)],
    "approve_attendance": [("Home", "dashboard"), ("People", None), ("Attendance", "attendance_approvals"), ("Review", None)],
    "reject_attendance": [("Home", "dashboard"), ("People", None), ("Attendance", "attendance_approvals"), ("Reject", None)],
    "apply_leave": [("Home", "dashboard"), ("My Work", None), ("Leave", "view_leaves"), ("Apply Leave", None)],
    "view_leaves": [("Home", "dashboard"), ("My Work", None), ("My Leave", None)],
    "leave_calendar": [("Home", "dashboard"), ("People", None), ("Leave Management", None)],
    "approve_leave": [("Home", "dashboard"), ("People", None), ("Leave Management", "leave_calendar"), ("Review", None)],
    "reject_leave": [("Home", "dashboard"), ("People", None), ("Leave Management", "leave_calendar"), ("Reject", None)],
    "product_list": [("Home", "dashboard"), ("Operations", None), ("Products", None)],
    "add_product": [("Home", "dashboard"), ("Operations", None), ("Products", "product_list"), ("Add Product", None)],
    "inventory_dashboard": [("Home", "dashboard"), ("Operations", None), ("Inventory", None)],
    "order_list": [("Home", "dashboard"), ("Operations", None), ("Orders", None)],
    "payment_list": [("Home", "dashboard"), ("Operations", None), ("Payments", None)],
    "customer_list": [("Home", "dashboard"), ("Operations", None), ("Customers", None)],
    "add_customer": [("Home", "dashboard"), ("Operations", None), ("Customers", "customer_list"), ("Add Customer", None)],
    "upload_file": [("Home", "dashboard"), ("Documents", None), ("Files", None)],
    "activity_log": [("Home", "dashboard"), ("Insights", None), ("Activity Log", None)],
    "global_search": [("Home", "dashboard"), ("Search", None)],
    "notifications_list": [("Home", "dashboard"), ("My Work", None), ("Notifications", None)],
    "mark_notification_read": [("Home", "dashboard"), ("My Work", None), ("Notifications", "notifications_list"), ("Notification", None)],
}

PAGE_COPY = {
    "dashboard": ("Dashboard", "Your workspace overview and current priorities."),
    "employee_profile": ("My Profile", "Your contact, employment, and account information."),
    "edit_profile": ("Edit Profile", "Update the information you are permitted to manage."),
    "change_password": ("Change Password", "Update your ERP account password securely."),
    "employee_list": ("Employee Directory", "Search and manage employee records."),
    "employee_create": ("Add Employee", "Create an employee record and initiate account activation."),
    "employee_detail": ("Employee Details", "Employment, account, attendance, and leave information."),
    "employee_edit": ("Edit Employee", "Update employee and employment information."),
    "attendance_history": ("My Attendance", "Review your attendance history and status."),
    "attendance_approvals": ("Attendance Approvals", "Review attendance records that require administrator action."),
    "apply_leave": ("Apply Leave", "Submit a leave request for review."),
    "view_leaves": ("My Leave", "Review your leave requests and their status."),
    "leave_calendar": ("Leave Management", "Review organization leave schedules and requests."),
    "product_list": ("Products", "Review products and current stock levels."),
    "add_product": ("Add Product", "Add a product to the inventory catalog."),
    "inventory_dashboard": ("Inventory", "Monitor stock levels and products that need attention."),
    "customer_list": ("Customers", "Search the customer directory."),
    "add_customer": ("Add Customer", "Add a customer record to the ERP."),
    "order_list": ("Orders", "Review recorded customer orders and totals."),
    "payment_list": ("Payments", "Review recorded payments and linked orders."),
    "upload_file": ("Files & Documents", "Access documents available to your account."),
    "activity_log": ("Activity Log", "Review recorded ERP activity."),
    "global_search": ("Global Search", "Search records available to your account."),
    "notifications_list": ("Notifications", "Review updates and items that need attention."),
}

INTERNAL_PAGE_HEADINGS = {
    "change_password",
    "attendance_history",
    "attendance_approvals",
    "view_leaves",
    "leave_calendar",
    "product_list",
    "inventory_dashboard",
    "customer_list",
    "notifications_list",
    "global_search",
    "activity_log",
    "edit_profile",
}


def pending_leave_notifications(request):
    if not request.user.is_authenticated:
        return {}

    pending_leaves = LeaveApplication.objects.filter(status="Pending")
    if not request.user.is_superuser:
        pending_leaves = pending_leaves.filter(employee=request.user)
    pending_leaves = pending_leaves.order_by("-start_date")[:5]

    route_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    breadcrumb_items = [
        {"label": label, "url": reverse(route) if route else None}
        for label, route in BREADCRUMB_ROUTES.get(route_name, [("Home", "dashboard")])
    ]

    return {
        "pending_leave_requests": pending_leaves,
        "pending_leave_count": pending_leaves.count(),
        "unread_notifications_count": request.user.notifications.filter(is_read=False).count(),
        "erp_breadcrumbs": breadcrumb_items,
        "erp_page_title": PAGE_COPY.get(route_name, ("ERP Suite", "Operational visibility and team productivity."))[0],
        "erp_page_subtitle": PAGE_COPY.get(route_name, ("ERP Suite", "Operational visibility and team productivity."))[1],
        "erp_hide_page_heading": route_name in INTERNAL_PAGE_HEADINGS,
    }
