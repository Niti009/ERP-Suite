from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
import json
from types import SimpleNamespace

from django.utils import timezone

from .models import (
    Employee,
    Attendance,
    LeaveApplication,
    Product,
    Customer,
    UploadedFile,
)

from .forms import (
    LeaveApplicationForm,
    ProductForm,
    CustomerForm,
    FileUploadForm,
)
from .permissions import demo_read_only, is_demo_user


def login_view(request):

    if request.method == "POST":

        user = authenticate(
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )

        if user:

            login(request, user)

            return redirect("dashboard")

        messages.error(request, "Invalid Username or Password")

    return render(request, "login.html")


def logout_view(request):

    logout(request)

    return redirect("login")


def _get_or_create_demo_user():
    """Provision the dedicated demo account and keep it read-only."""
    user_model = get_user_model()

    try:
        demo_user = user_model.objects.get(username=settings.DEMO_LOGIN_USERNAME)
    except user_model.DoesNotExist:
        try:
            demo_user = user_model.objects.create_user(
                username=settings.DEMO_LOGIN_USERNAME,
                password=settings.DEMO_LOGIN_PASSWORD,
                is_staff=False,
                is_superuser=False,
            )
        except Exception:
            return None

    changed_fields = []
    for field_name, expected_value in (
        ("is_active", True),
        ("is_staff", False),
        ("is_superuser", False),
    ):
        if getattr(demo_user, field_name) != expected_value:
            setattr(demo_user, field_name, expected_value)
            changed_fields.append(field_name)

    if changed_fields:
        demo_user.save(update_fields=changed_fields)

    # A pre-existing account must not retain elevated or explicitly granted access.
    demo_user.groups.clear()
    demo_user.user_permissions.clear()

    if not demo_user.check_password(settings.DEMO_LOGIN_PASSWORD):
        demo_user.set_password(settings.DEMO_LOGIN_PASSWORD)
        demo_user.save(update_fields=["password"])

    return demo_user


def demo_login_view(request):
    """Authenticate using Django's auth system and log in the dedicated demo user."""
    if _get_or_create_demo_user() is None:
        messages.error(
            request,
            "The demo account is currently unavailable. Please try again later or use a regular login.",
        )
        return redirect("login")

    demo_user = authenticate(
        username=settings.DEMO_LOGIN_USERNAME,
        password=settings.DEMO_LOGIN_PASSWORD,
    )

    if demo_user is None:
        messages.error(
            request,
            "The demo account is currently unavailable. Please try again later or use a regular login.",
        )
        return redirect("login")

    login(request, demo_user)
    messages.success(request, "You are now exploring the demo account.")
    return redirect("dashboard")


def signup_view(request):

    form = UserCreationForm(request.POST or None)

    if request.method == "POST":

        if form.is_valid():

            form.save()

            messages.success(request, "Account Created Successfully")

            return redirect("login")

    return render(request, "signup.html", {"form": form})


@login_required
def dashboard(request):

    today = timezone.now().date()

    attendance = Attendance.objects.filter(
        employee=request.user,
        date=today
    ).first()

    if request.method == "POST":

        if is_demo_user(request.user):
            messages.error(
                request,
                "Demo mode is read-only. Please sign in with a full account to make changes.",
            )
            return redirect("dashboard")

        if attendance is None:

            Attendance.objects.create(
                employee=request.user,
                date=today,
                status="Present",
                check_in=timezone.now().time()
            )

        elif attendance.check_out is None:

            attendance.check_out = timezone.now().time()
            attendance.save()

        return redirect("dashboard")

    total_employees = Employee.objects.count()
    total_products = Product.objects.count()
    total_customers = Customer.objects.count()

    total_leaves = LeaveApplication.objects.count()

    pending_leaves = LeaveApplication.objects.filter(
        status="Pending"
    ).count()

    total_attendance_today = Attendance.objects.filter(
        date=today
    ).count()

    recent_leaves = LeaveApplication.objects.order_by("-id")[:5]

    approved = LeaveApplication.objects.filter(
        status="Approved"
    ).count()

    pending = LeaveApplication.objects.filter(
        status="Pending"
    ).count()

    rejected = LeaveApplication.objects.filter(
        status="Rejected"
    ).count()

    present = Attendance.objects.filter(
        status="Present"
    ).count()

    absent = max(total_employees - present, 0)

    if pending_leaves > 5:

        insight = "Multiple leave requests require approval."

    elif total_attendance_today < total_employees:

        insight = "Attendance is lower than expected today."

    else:

        insight = "Business operations are running normally."

    context = {

        "attendance": attendance,

        "total_employees": total_employees,

        "total_products": total_products,

        "total_customers": total_customers,

        "total_leaves": total_leaves,

        "pending_leaves": pending_leaves,

        "total_attendance_today": total_attendance_today,

        "recent_leaves": recent_leaves,

        "approved": approved,

        "pending": pending,

        "rejected": rejected,

        "present": present,

        "absent": absent,

    "chart_data": json.dumps({
        "present": present,
        "absent": absent,
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
    }),

    "insight": insight,

}

    if request.user.is_superuser:

        return render(
            request,
            "admin_dashboard.html",
            context,
        )

    return render(
        request,
        "employee_dashboard.html",
        context,
    )


@login_required
@demo_read_only
def apply_leave(request):

    if request.method == "POST":

        form = LeaveApplicationForm(request.POST)

        if form.is_valid():

            leave = form.save(commit=False)

            leave.employee = request.user
            leave.leave_type = "Casual"
            leave.status = "Pending"

            leave.save()

            messages.success(
                request,
                "Leave Application Submitted Successfully"
            )

            return redirect("view_leaves")

    else:

        form = LeaveApplicationForm()

    return render(
        request,
        "leave_application.html",
        {
            "form": form
        },
    )


@login_required
def view_leaves(request):

    if request.user.is_superuser:

        leaves = LeaveApplication.objects.all().order_by("-start_date")

    else:

        leaves = LeaveApplication.objects.filter(
            employee=request.user
        ).order_by("-start_date")

    return render(
        request,
        "view_leaves.html",
        {
            "leaves": leaves,
        },
    )


@login_required
@demo_read_only
def approve_leave(request, leave_id):

    if not request.user.is_superuser:

        messages.error(
            request,
            "Only administrators can approve leave requests."
        )

        return redirect("view_leaves")

    leave = get_object_or_404(
        LeaveApplication,
        id=leave_id
    )

    leave.status = "Approved"
    leave.save()

    messages.success(
        request,
        "Leave Approved Successfully."
    )

    return redirect("view_leaves")


@login_required
@demo_read_only
def reject_leave(request, leave_id):

    if not request.user.is_superuser:

        messages.error(
            request,
            "Only administrators can reject leave requests."
        )

        return redirect("view_leaves")

    leave = get_object_or_404(
        LeaveApplication,
        id=leave_id
    )

    leave.status = "Rejected"
    leave.save()

    messages.success(
        request,
        "Leave Rejected Successfully."
    )

    return redirect("view_leaves")


@login_required
def attendance_history(request):

    if request.user.is_superuser:

        records = Attendance.objects.select_related(
            "employee"
        ).all().order_by("-date")

    else:

        records = Attendance.objects.filter(
            employee=request.user
        ).order_by("-date")

    present_days = records.filter(
        status="Present"
    ).count()

    total_days = records.count()

    attendance_percentage = (
        round((present_days / total_days) * 100)
        if total_days > 0 else 0
    )

    return render(
        request,
        "attendance_history.html",
        {
            "records": records,
            "attendance_percentage": attendance_percentage,
        },
    )


@login_required
def employee_profile(request):
    if is_demo_user(request.user):
        employee = SimpleNamespace(
            name=request.user.username,
            phone="",
            position="Demo Viewer",
            salary=0.00,
            joining_date=timezone.now().date(),
            department=None,
        )
    else:
        employee, created = Employee.objects.get_or_create(
            user=request.user,
            defaults={
                "name": request.user.username,
                "phone": "",
                "position": "Not Assigned",
                "salary": 0.00,
                "joining_date": timezone.now().date(),
                "department": None,
            },
        )

    records = Attendance.objects.filter(employee=request.user).order_by("-date")
    recent_records = records[:10]

    present_days = records.filter(status="Present").count()
    total_days = records.count()
    attendance_percentage = round((present_days / total_days) * 100) if total_days else 0

    pending_leaves = LeaveApplication.objects.filter(employee=request.user, status="Pending").count()
    approved_leaves = LeaveApplication.objects.filter(employee=request.user, status="Approved").count()
    rejected_leaves = LeaveApplication.objects.filter(employee=request.user, status="Rejected").count()

    return render(
        request,
        "employee_profile.html",
        {
            "employee": employee,
            "records": recent_records,
            "attendance_percentage": attendance_percentage,
            "present_days": present_days,
            "total_days": total_days,
            "pending_leaves": pending_leaves,
            "approved_leaves": approved_leaves,
            "rejected_leaves": rejected_leaves,
        },
    )


@login_required
def product_list(request):

    products = Product.objects.all().order_by("name")

    return render(
        request,
        "product_list.html",
        {
            "products": products,
        },
    )


@login_required
@demo_read_only
def add_product(request):

    if request.method == "POST":

        form = ProductForm(request.POST)

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Product added successfully."
            )

            return redirect("product_list")

    else:

        form = ProductForm()

    return render(
        request,
        "add_product.html",
        {
            "form": form,
        },
    )


@login_required
def customer_list(request):

    customers = Customer.objects.all().order_by("name")

    return render(
        request,
        "customer_list.html",
        {
            "customers": customers,
        },
    )


@login_required
@demo_read_only
def add_customer(request):

    if request.method == "POST":

        form = CustomerForm(request.POST)

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Customer added successfully."
            )

            return redirect("customer_list")

    else:

        form = CustomerForm()

    return render(
        request,
        "add_customer.html",
        {
            "form": form,
        },
    )


@login_required
@demo_read_only
def upload_file(request):

    if request.method == "POST":

        form = FileUploadForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            uploaded = form.save(commit=False)

            uploaded.uploaded_by = request.user

            uploaded.save()

            messages.success(
                request,
                "Document uploaded successfully."
            )

            return redirect("upload_file")

    else:

        form = FileUploadForm()

    if request.user.is_superuser:

        uploaded_files = UploadedFile.objects.all().order_by("-uploaded_at")

    else:

        uploaded_files = UploadedFile.objects.filter(
            uploaded_by=request.user
        ).order_by("-uploaded_at")

    return render(
        request,
        "upload_file.html",
        {
            "form": form,
            "uploaded_files": uploaded_files,
        },
    )
