from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.forms import SetPasswordForm
from django.conf import settings
from django.urls import reverse
from django.core.mail import send_mail
from django.core.exceptions import ObjectDoesNotExist
from django.utils.encoding import force_bytes, force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode, urlsafe_base64_encode
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.views.decorators.http import require_POST
import hashlib
import hmac
import json
import logging
import secrets
from types import SimpleNamespace
from datetime import datetime, timedelta
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from django.utils import timezone

from .models import (
    Department,
    Employee,
    Attendance,
    LeaveApplication,
    Product,
    Customer,
    Order,
    Payment,
    UploadedFile,
    Notification,
    ActivityLog,
    EmployeeInvitation,
)

from .forms import (
    LeaveApplicationForm,
    ProductForm,
    CustomerForm,
    FileUploadForm,
    UserProfileForm,
    EmployeeProfileForm,
    EmployeePromptForm,
    CustomPasswordChangeForm,
    EmployeeCreateForm,
)
from .permissions import demo_read_only, is_demo_user

logger = logging.getLogger(__name__)


def login_view(request):
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        username = identifier
        user_model = get_user_model()
        if not user_model.objects.filter(username__iexact=identifier).exists():
            username = user_model.objects.filter(email__iexact=identifier).values_list("username", flat=True).first() or identifier
        user = authenticate(username=username, password=request.POST.get("password"))
        if user:
            login(request, user)
            return redirect("dashboard")
        messages.error(request, "Invalid Username or Password")

    return render(request, "login.html")


@require_POST
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
    messages.info(request, "ERP access is managed by your company. Contact your administrator for an account.")
    return redirect("login")


def _invitation_token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_employee_invitation(employee):
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    invitation, _ = EmployeeInvitation.objects.update_or_create(
        employee=employee,
        defaults={
            "token_hash": _invitation_token_hash(token),
            "created_at": now,
            "expires_at": now + timedelta(hours=getattr(settings, "EMPLOYEE_INVITATION_EXPIRY_HOURS", 72)),
            "accepted_at": None,
        },
    )
    return invitation, token


def _send_employee_invitation(request, employee, token):
    activation_url = request.build_absolute_uri(
        reverse(
            "employee_activate",
            kwargs={"uidb64": urlsafe_base64_encode(force_bytes(employee.user_id)), "token": token},
        )
    )
    expiry_hours = getattr(settings, "EMPLOYEE_INVITATION_EXPIRY_HOURS", 72)
    subject = "Activate your ERP Suite account"
    body = (
        f"Hello {employee.user.get_full_name() or employee.name},\n\n"
        "Your company has created an ERP Suite account for you. "
        "Use the secure link below to set your password and activate your account:\n\n"
        f"{activation_url}\n\n"
        f"This link expires in {expiry_hours} hours and can only be used once. "
        "If you were not expecting this invitation, contact your company administrator."
    )

    try:
        sent = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [employee.user.email], fail_silently=False)
    except Exception:
        logger.exception("Unable to send ERP invitation to employee %s", employee.pk)
        return "failed"

    if not sent:
        return "failed"
    if settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        return "console"
    return "sent"


def employee_activate(request, uidb64, token):
    user_model = get_user_model()
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        employee = Employee.objects.select_related("user").get(user_id=user_id)
        invitation = employee.invitation
    except (ValueError, TypeError, OverflowError, user_model.DoesNotExist, Employee.DoesNotExist, ObjectDoesNotExist):
        return render(request, "employee_invitation_invalid.html", status=400)

    def is_valid_invitation(current_employee, current_invitation, current_user):
        return (
            current_invitation.accepted_at is None
            and current_invitation.expires_at > timezone.now()
            and current_employee.employment_status == "Active"
            and not current_user.is_active
            and not current_user.has_usable_password()
            and hmac.compare_digest(current_invitation.token_hash, _invitation_token_hash(token))
        )

    if not is_valid_invitation(employee, invitation, employee.user):
        return render(request, "employee_invitation_invalid.html", status=400)

    form = SetPasswordForm(employee.user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            invitation = EmployeeInvitation.objects.select_for_update().select_related("employee").get(pk=invitation.pk)
            employee = Employee.objects.select_related("user").get(pk=employee.pk)
            user = user_model.objects.select_for_update().get(pk=employee.user_id)
            if not is_valid_invitation(employee, invitation, user):
                return render(request, "employee_invitation_invalid.html", status=400)

            user.set_password(form.cleaned_data["new_password1"])
            user.is_active = True
            user.save(update_fields=["password", "is_active"])
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["accepted_at"])

        messages.success(request, "Your account is active. Sign in with your new password.")
        return redirect("login")

    return render(request, "employee_invitation_activate.html", {
        "form": form,
        "employee": employee,
        "expiry_hours": getattr(settings, "EMPLOYEE_INVITATION_EXPIRY_HOURS", 72),
    })


def _employee_status_label(user):
    return "Active" if getattr(user, "is_active", True) else "Inactive"


def _employee_account_status(employee):
    if employee.user.is_active:
        return "Active"
    try:
        invitation = employee.invitation
    except EmployeeInvitation.DoesNotExist:
        return "Inactive"
    if invitation.accepted_at is None and invitation.expires_at > timezone.now():
        return "Invited"
    return "Inactive"


def _notify_admins(title, description, object_type, object_id, related_link):
    admin_user_model = get_user_model()
    notifications = [
        Notification(
            user=admin,
            notification_type="employee_activity",
            title=title,
            description=description,
            related_object_type=object_type,
            related_object_id=object_id,
            related_link=related_link,
        )
        for admin in admin_user_model.objects.filter(is_superuser=True, is_active=True)
    ]
    if notifications:
        Notification.objects.bulk_create(notifications)


def get_action_center_items(request):
    items = []

    if request.user.is_superuser:
        pending_leaves = LeaveApplication.objects.filter(status='Pending').select_related('employee')[:5]
        for leave in pending_leaves:
            items.append({
                'category': 'Leave',
                'title': 'Leave approval required',
                'entity': f"{leave.employee.username} — {leave.leave_type}",
                'detail': f"{leave.start_date} to {leave.end_date} ({leave.reason[:90]})",
                'url': reverse('view_leaves'),
                'link_label': 'Review request',
                'timestamp': leave.start_date,
            })

        pending_attendance = Attendance.objects.filter(approval_status='Pending').select_related('employee')[:5]
        for record in pending_attendance:
            items.append({
                'category': 'Attendance',
                'title': 'Attendance review',
                'entity': f"{record.employee.username}",
                'detail': f"Date: {record.date} — status: {record.status}",
                'url': reverse('attendance_approvals'),
                'link_label': 'Review attendance',
                'timestamp': record.date,
            })

        low_stock_products = []
        for product in Product.objects.all().order_by('name'):
            if product.get_stock_status() in ('low_stock', 'out_of_stock'):
                low_stock_products.append(product)
        for product in low_stock_products[:5]:
            items.append({
                'category': 'Inventory',
                'title': 'Low stock alert',
                'entity': product.name,
                'detail': f"Current quantity: {product.quantity} | Reorder level: {product.reorder_level}",
                'url': reverse('inventory_dashboard'),
                'link_label': 'View inventory',
                'timestamp': timezone.now().date(),
            })

        incomplete_profiles = Employee.objects.select_related('user').filter(
            Q(user__first_name='') | Q(user__last_name='') | Q(phone='') | Q(location='')
        )[:5]
        for employee in incomplete_profiles:
            items.append({
                'category': 'Employees',
                'title': 'Profile needs attention',
                'entity': employee.name,
                'detail': 'Employee profile has missing identity or contact details.',
                'url': reverse('employee_detail', kwargs={'employee_id': employee.pk}),
                'link_label': 'Review employee',
                'timestamp': timezone.now().date(),
            })
    else:
        my_pending_leaves = LeaveApplication.objects.filter(employee=request.user, status='Pending')[:3]
        for leave in my_pending_leaves:
            items.append({
                'category': 'Leave',
                'title': 'Leave request pending',
                'entity': leave.leave_type,
                'detail': f"{leave.start_date} to {leave.end_date}",
                'url': reverse('view_leaves'),
                'link_label': 'View request',
                'timestamp': leave.start_date,
            })

    return items


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

            attendance = Attendance.objects.create(
                employee=request.user,
                date=today,
                status="Present",
                approval_status="Pending",
                check_in=timezone.now().time()
            )
            _notify_admins(
                "Employee attendance submitted",
                f"{request.user.get_full_name() or request.user.username} checked in for {today}.",
                "attendance",
                attendance.pk,
                reverse("attendance_approvals"),
            )

        elif attendance.check_out is None:

            attendance.check_out = timezone.now().time()
            attendance.save()
            _notify_admins(
                "Employee attendance updated",
                f"{request.user.get_full_name() or request.user.username} checked out for {today}.",
                "attendance",
                attendance.pk,
                reverse("attendance_approvals"),
            )

        return redirect("dashboard")

    is_admin = request.user.is_superuser
    leave_records = LeaveApplication.objects.all()
    attendance_records = Attendance.objects.all()
    activity_records = ActivityLog.objects.select_related('user').all()
    if not is_admin:
        leave_records = leave_records.filter(employee=request.user)
        attendance_records = attendance_records.filter(employee=request.user)
        activity_records = activity_records.filter(user=request.user)

    total_employees = Employee.objects.count() if is_admin else 1
    total_products = Product.objects.count() if is_admin else 0
    total_customers = Customer.objects.count() if is_admin else 0
    total_leaves = leave_records.count()
    pending_leaves = leave_records.filter(status="Pending").count()
    total_attendance_today = attendance_records.filter(date=today).count()
    recent_leaves = leave_records.order_by("-id")[:5]
    approved = leave_records.filter(status="Approved").count()
    pending = leave_records.filter(status="Pending").count()
    rejected = leave_records.filter(status="Rejected").count()
    present = attendance_records.filter(status="Present").count()
    absent = max(total_employees - present, 0) if is_admin else 0
    pending_attendance_approvals = (
        Attendance.objects.filter(approval_status='Pending').count() if is_admin else 0
    )

    unread_notifications_count = request.user.notifications.filter(is_read=False).count()
    inventory_summary = get_inventory_summary() if is_admin else {}

    if not is_admin:
        if attendance is None:
            insight = "Your attendance has not been marked for today."
        elif pending_leaves:
            insight = "You have leave requests awaiting review."
        else:
            insight = "Your attendance and leave status are up to date."
    elif pending_leaves > 5:
        insight = "Multiple leave requests require approval."
    elif total_attendance_today < max(total_employees, 1):
        insight = "Attendance is lower than expected today."
    else:
        insight = "Business operations are running normally."

    recent_activity = activity_records.order_by('-timestamp')[:6]

    context = {
        "attendance": attendance,
        "total_employees": total_employees,
        "total_products": total_products,
        "total_customers": total_customers,
        "total_leaves": total_leaves,
        "pending_leaves": pending_leaves,
        "total_attendance_today": total_attendance_today,
        "recent_leaves": recent_leaves,
        "recent_activity": recent_activity,
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
        "present": present,
        "absent": absent,
        "pending_attendance_approvals": pending_attendance_approvals,
        "unread_notifications_count": unread_notifications_count,
        "inventory_summary": inventory_summary,
        "chart_data": json.dumps({
            "present": present,
            "absent": absent,
            "approved": approved,
            "pending": pending,
            "rejected": rejected,
        }),
        "insight": insight,
        "action_center_items": get_action_center_items(request),
        "current_user_status": _employee_status_label(request.user),
        "current_employee": Employee.objects.filter(user=request.user).first(),
    }

    if request.user.is_superuser:
        return render(request, "admin_dashboard.html", context)

    return render(request, "employee_dashboard.html", context)


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

            _notify_admins(
                "Employee leave request submitted",
                f"{request.user.get_full_name() or request.user.username} requested leave from {leave.start_date} to {leave.end_date}.",
                "leave",
                leave.pk,
                reverse("view_leaves"),
            )

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
@demo_read_only
def edit_profile(request):
    """Allow users to edit their own profile"""
    # Get or create Employee object
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
    
    if request.method == "POST":
        # Handle photo clearing
        if 'clear_photo' in request.POST and employee.profile_photo:
            employee.profile_photo.delete()
            employee.save()
            messages.success(request, "Profile photo removed successfully!")
            return redirect("edit_profile")
        
        user_form = UserProfileForm(request.POST, instance=request.user)
        employee_form = EmployeeProfileForm(request.POST, request.FILES, instance=employee)
        
        if user_form.is_valid() and employee_form.is_valid():
            user_form.save()
            
            # Validate file size for profile photo
            if 'profile_photo' in request.FILES:
                file = request.FILES['profile_photo']
                if file.size > 5 * 1024 * 1024:  # 5MB limit
                    messages.error(request, "Profile photo must be less than 5MB")
                    return render(request, "profile_form.html", {
                        "user_form": user_form,
                        "employee_form": employee_form,
                        "employee": employee,
                    })
            
            employee_form.save()
            if not request.user.is_superuser:
                _notify_admins(
                    "Employee profile updated",
                    f"{request.user.get_full_name() or request.user.username} updated their profile.",
                    "employee",
                    employee.pk,
                    reverse("employee_detail", kwargs={"employee_id": employee.pk}),
                )
            messages.success(request, "Your profile has been updated successfully!")
            return redirect("employee_profile")
    else:
        user_form = UserProfileForm(instance=request.user)
        employee_form = EmployeeProfileForm(instance=employee)
    
    context = {
        "user_form": user_form,
        "employee_form": employee_form,
        "employee": employee,
    }
    
    return render(request, "profile_form.html", context)


@login_required
@demo_read_only
def change_password_view(request):
    """Allow users to change their password"""
    if request.method == "POST":
        form = CustomPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Update the session to prevent logout
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
            messages.success(request, "Your password has been changed successfully!")
            return redirect("employee_profile")
    else:
        form = CustomPasswordChangeForm(request.user)
    
    return render(request, "change_password.html", {"form": form})


@login_required
def employee_list(request):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can access the employee directory.')
        return redirect('dashboard')

    pending_invitation = EmployeeInvitation.objects.filter(
        employee_id=OuterRef('pk'),
        accepted_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    employees = Employee.objects.select_related('user', 'department', 'invitation').annotate(
        invitation_pending=Exists(pending_invitation)
    ).order_by('name')

    query = request.GET.get('q', '').strip()
    department_id = request.GET.get('department', '')
    status = request.GET.get('status', '')
    location = request.GET.get('location', '').strip()

    if query:
        employees = employees.filter(
            Q(name__icontains=query) |
            Q(employee_id__icontains=query) |
            Q(position__icontains=query) |
            Q(user__username__icontains=query)
        )
    if department_id:
        employees = employees.filter(department_id=department_id)
    if status == 'Active':
        employees = employees.filter(user__is_active=True)
    elif status == 'Invited':
        employees = employees.filter(
            user__is_active=False,
            employment_status='Active',
            invitation_pending=True,
        )
    elif status == 'Inactive':
        employees = employees.filter(user__is_active=False).filter(
            Q(employment_status='Inactive') | Q(invitation_pending=False)
        )
    if location:
        employees = employees.filter(location__icontains=location)

    paginator = Paginator(employees, 12)
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    for employee in page_obj:
        employee.account_status = _employee_account_status(employee)

    departments = Department.objects.all().order_by('name')
    return render(request, 'employee_list.html', {
        'employees': page_obj,
        'departments': departments,
        'query': query,
        'selected_department': department_id,
        'selected_status': status,
        'selected_location': location,
    })


@login_required
def employee_detail(request, employee_id):
    employee = get_object_or_404(Employee.objects.select_related('user', 'department'), pk=employee_id)

    if not request.user.is_superuser and employee.user != request.user:
        messages.error(request, 'You do not have access to that employee profile.')
        return redirect('dashboard')

    attendance_records = Attendance.objects.filter(employee=employee.user).order_by('-date')[:10]
    leave_records = LeaveApplication.objects.filter(employee=employee.user).order_by('-start_date')[:5]

    return render(request, 'employee_detail.html', {
        'employee': employee,
        'attendance_records': attendance_records,
        'leave_records': leave_records,
        'status_label': _employee_account_status(employee),
        'prompt_form': EmployeePromptForm() if request.user.is_superuser else None,
    })


@login_required
@demo_read_only
@require_POST
def send_employee_prompt(request, employee_id):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can send employee prompts.')
        return redirect('dashboard')

    employee = get_object_or_404(Employee.objects.select_related('user'), pk=employee_id)
    form = EmployeePromptForm(request.POST)
    if form.is_valid():
        Notification.objects.create(
            user=employee.user,
            notification_type='admin_prompt',
            title=form.cleaned_data['title'],
            description=form.cleaned_data['message'],
            related_object_type='employee',
            related_object_id=employee.pk,
            related_link=reverse('employee_profile'),
        )
        messages.success(request, f"Your message was sent to {employee.name}.")
    else:
        messages.error(request, 'Enter a subject and message before sending.')
    return redirect('employee_detail', employee_id=employee.pk)


@login_required
@demo_read_only
def employee_create(request):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can create employees from the ERP.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = EmployeeCreateForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user, employee = form.save()
                    invitation_token = None
                    if employee.employment_status == 'Active':
                        _, invitation_token = _issue_employee_invitation(employee)
            except IntegrityError:
                form.add_error(None, 'An account or employee ID with those details already exists.')
            else:
                if invitation_token:
                    delivery = _send_employee_invitation(request, employee, invitation_token)
                    if delivery == 'sent':
                        messages.success(request, f'Employee {employee.name} was created and the invitation email was sent.')
                    elif delivery == 'console':
                        messages.info(request, 'Employee created. The invitation is printed to the development console; it was not sent to the recipient.')
                    else:
                        messages.warning(request, 'Employee created, but the invitation email could not be sent. Configure email and resend the invitation.')
                else:
                    messages.warning(request, 'Employee created as inactive. No activation invitation was sent.')
            return redirect('employee_detail', employee_id=employee.pk)
    else:
        form = EmployeeCreateForm(initial={
            'employment_status': 'Active',
        })

    return render(request, 'employee_form.html', {
        'form': form,
        'title': 'Add Employee',
    'submit_label': 'Create Employee & Send Invitation',
        'is_edit': False,
    })


@login_required
@demo_read_only
def employee_edit(request, employee_id):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can edit employee records.')
        return redirect('dashboard')

    employee = get_object_or_404(Employee.objects.select_related('user', 'department'), pk=employee_id)
    if request.method == 'POST':
        form = EmployeeCreateForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            with transaction.atomic():
                previous_email = employee.user.email
                previous_employment_status = employee.employment_status
                employee.user.first_name = form.cleaned_data['first_name'].strip()
                employee.user.last_name = form.cleaned_data['last_name'].strip()
                employee.user.email = form.cleaned_data['email'].strip()
                employee.user.username = form.cleaned_data['username'].strip()
                if form.cleaned_data['employment_status'] == 'Inactive':
                    employee.user.is_active = False
                employee.user.save(update_fields=['first_name', 'last_name', 'email', 'username', 'is_active'])

                employee.name = f"{employee.user.first_name} {employee.user.last_name}".strip() or employee.user.username
                employee.phone = form.cleaned_data.get('phone', '')
                employee.date_of_birth = form.cleaned_data.get('date_of_birth')
                employee.gender = form.cleaned_data.get('gender', '')
                employee.position = form.cleaned_data['position']
                employee.employment_status = form.cleaned_data['employment_status']
                employee.department = form.cleaned_data.get('department')
                employee.joining_date = form.cleaned_data['joining_date']
                employee.employee_id = form.cleaned_data['employee_id']
                employee.location = form.cleaned_data.get('location', '')
                employee.bio = form.cleaned_data.get('address', employee.bio)
                if form.cleaned_data.get('profile_photo'):
                    employee.profile_photo = form.cleaned_data['profile_photo']
                employee.save()
                if (
                    not employee.user.is_active
                    and not employee.user.has_usable_password()
                    and (previous_email != employee.user.email or previous_employment_status != employee.employment_status)
                ):
                    EmployeeInvitation.objects.filter(employee=employee, accepted_at__isnull=True).update(
                        accepted_at=timezone.now()
                    )
            messages.success(request, 'Employee details updated successfully.')
            return redirect('employee_detail', employee_id=employee.pk)
    else:
        form = EmployeeCreateForm(instance=employee, initial={
            'first_name': employee.user.first_name,
            'last_name': employee.user.last_name,
            'username': employee.user.username,
            'email': employee.user.email,
            'phone': employee.phone,
            'location': employee.location,
            'employee_id': employee.employee_id,
            'department': employee.department,
            'position': employee.position,
            'joining_date': employee.joining_date,
            'employment_status': employee.employment_status,
            'date_of_birth': employee.date_of_birth,
            'gender': employee.gender,
        })

    return render(request, 'employee_form.html', {
        'form': form,
        'title': 'Edit Employee',
        'submit_label': 'Save Changes',
        'is_edit': True,
        'employee': employee,
    })


@login_required
@demo_read_only
@require_POST
def toggle_employee_status(request, employee_id):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can activate or deactivate employees.')
        return redirect('dashboard')

    employee = get_object_or_404(Employee.objects.select_related('user'), pk=employee_id)
    if employee.user.is_active:
        employee.user.is_active = False
    elif employee.employment_status != 'Active':
        messages.error(request, 'Set the employment status to Active before enabling this account.')
        return redirect('employee_detail', employee_id=employee.pk)
    elif not employee.user.has_usable_password():
        messages.error(request, 'This account must be activated through its invitation link. Resend the invitation instead.')
        return redirect('employee_detail', employee_id=employee.pk)
    else:
        employee.user.is_active = True
    employee.user.save(update_fields=['is_active'])
    messages.success(request, f"Employee status updated to {'Active' if employee.user.is_active else 'Inactive'}.")
    return redirect('employee_detail', employee_id=employee.pk)


@login_required
@demo_read_only
@require_POST
def resend_employee_invitation(request, employee_id):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can resend employee invitations.')
        return redirect('dashboard')

    employee = get_object_or_404(Employee.objects.select_related('user'), pk=employee_id)
    if employee.user.is_active or employee.user.has_usable_password() or employee.employment_status != 'Active':
        messages.error(request, 'This employee is not eligible for an activation invitation.')
        return redirect('employee_detail', employee_id=employee.pk)

    invitation, token = _issue_employee_invitation(employee)
    delivery = _send_employee_invitation(request, employee, token)
    if delivery == 'sent':
        messages.success(request, f'Invitation resent to {employee.user.email}.')
    elif delivery == 'console':
        messages.info(request, 'The new invitation is printed to the development console; it was not sent to the recipient.')
    else:
        messages.warning(request, 'The invitation could not be sent. Check email configuration and retry.')
    return redirect('employee_detail', employee_id=employee.pk)


@login_required
def product_list(request):
    query = request.GET.get('q', '').strip()
    products = Product.objects.all().order_by("name")
    if query:
        products = products.filter(name__icontains=query)

    return render(
        request,
        "product_list.html",
        {
            "products": products,
            "query": query,
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
def order_list(request):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can view organization orders.')
        return redirect('dashboard')

    query = request.GET.get('q', '').strip()
    orders = Order.objects.select_related('customer').prefetch_related('orderitem_set').order_by('-date', '-pk')
    if query:
        filters = Q(customer__name__icontains=query)
        if query.isdigit():
            filters |= Q(pk=int(query))
        filters |= Q(orderitem__product__name__icontains=query)
        orders = orders.filter(filters).distinct()
    return render(request, 'order_list.html', {'orders': orders[:200], 'query': query})


@login_required
def payment_list(request):
    if not request.user.is_superuser:
        messages.error(request, 'Only administrators can view organization payments.')
        return redirect('dashboard')

    query = request.GET.get('q', '').strip()
    payments = Payment.objects.select_related('order__customer').order_by('-payment_date', '-pk')
    if query:
        filters = Q(order__customer__name__icontains=query) | Q(payment_method__icontains=query)
        if query.isdigit():
            filters |= Q(order_id=int(query)) | Q(pk=int(query))
        payments = payments.filter(filters)
    return render(request, 'payment_list.html', {'payments': payments[:200], 'query': query})


@login_required
def customer_list(request):
    query = request.GET.get('q', '').strip()
    customers = Customer.objects.all().order_by("name")
    if query:
        customers = customers.filter(
            Q(name__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query)
        )

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

            _notify_admins(
                "Employee document uploaded",
                f"{request.user.get_full_name() or request.user.username} uploaded {uploaded.file.name}.",
                "document",
                uploaded.pk,
                reverse("upload_file"),
            )

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
            Q(uploaded_by=request.user) | Q(uploaded_by__isnull=True)
        ).order_by("-uploaded_at")

    return render(
        request,
        "upload_file.html",
        {
            "form": form,
            "uploaded_files": uploaded_files,
        },
    )


# ==================== FEATURE 1: ATTENDANCE APPROVAL ====================

@login_required
def attendance_approvals(request):
    """Admin view for approving/rejecting pending attendance"""
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to access this page.")
        return redirect('dashboard')
    
    # Get all pending attendance records
    pending_attendance = Attendance.objects.filter(
        approval_status='Pending'
    ).select_related('employee').order_by('-date')
    
    # Get counts for dashboard
    total_pending = pending_attendance.count()
    approved_count = Attendance.objects.filter(approval_status='Approved').count()
    rejected_count = Attendance.objects.filter(approval_status='Rejected').count()
    
    context = {
        'pending_attendance': pending_attendance,
        'total_pending': total_pending,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
    }
    
    return render(request, 'attendance_approvals.html', context)


@login_required
@demo_read_only
def approve_attendance(request, attendance_id):
    """Approve pending attendance"""
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect('dashboard')
    
    attendance = get_object_or_404(Attendance, id=attendance_id)
    
    attendance.approval_status = 'Approved'
    attendance.approved_at = timezone.now()
    attendance.approved_by = request.user
    attendance.save()
    
    # Create notification for employee
    Notification.objects.create(
        user=attendance.employee,
        notification_type='attendance_approved',
        title='Attendance Approved',
        description=f'Your attendance for {attendance.date} has been approved.',
        related_object_type='attendance',
        related_object_id=attendance.id,
        related_link=f'/attendance/'
    )
    
    # Log activity
    ActivityLog.objects.create(
        user=request.user,
        action_type='attendance_approved',
        object_type='attendance',
        object_id=attendance.id,
        description=f'Approved attendance for {attendance.employee.username} on {attendance.date}'
    )
    
    messages.success(request, f"Attendance approved for {attendance.employee.username}")
    return redirect('attendance_approvals')


@login_required
@demo_read_only
def reject_attendance(request, attendance_id):
    """Reject pending attendance"""
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect('dashboard')
    
    attendance = get_object_or_404(Attendance, id=attendance_id)
    
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason', '')
        
        attendance.approval_status = 'Rejected'
        attendance.rejection_reason = reason
        attendance.approved_at = timezone.now()
        attendance.approved_by = request.user
        attendance.save()
        
        # Create notification for employee
        Notification.objects.create(
            user=attendance.employee,
            notification_type='attendance_rejected',
            title='Attendance Rejected',
            description=f'Your attendance for {attendance.date} has been rejected. Reason: {reason}',
            related_object_type='attendance',
            related_object_id=attendance.id,
            related_link=f'/attendance/'
        )
        
        # Log activity
        ActivityLog.objects.create(
            user=request.user,
            action_type='attendance_rejected',
            object_type='attendance',
            object_id=attendance.id,
            description=f'Rejected attendance for {attendance.employee.username} on {attendance.date}. Reason: {reason}'
        )
        
        messages.success(request, f"Attendance rejected for {attendance.employee.username}")
        return redirect('attendance_approvals')
    
    return render(request, 'reject_attendance.html', {'attendance': attendance})


# ==================== FEATURE 2: NOTIFICATION CENTER ====================

@login_required
def notifications_list(request):
    """Show user's notifications"""
    notifications = request.user.notifications.all()[:50]
    unread_count = request.user.notifications.filter(is_read=False).count()
    
    context = {
        'notifications': notifications,
        'unread_count': unread_count,
    }
    
    return render(request, 'notifications.html', context)


@login_required
@require_POST
def mark_notification_read(request, notification_id):
    """Mark single notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    
    # Redirect to related link if available
    if notification.related_link and url_has_allowed_host_and_scheme(
        notification.related_link,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(notification.related_link)
    
    return redirect('notifications_list')


@login_required
@require_POST
def mark_all_notifications_read(request):
    """Mark all notifications as read"""
    request.user.notifications.filter(is_read=False).update(is_read=True)
    messages.success(request, "All notifications marked as read")
    return redirect('notifications_list')


# ==================== FEATURE 3: GLOBAL ERP SEARCH ====================

@login_required
def global_search(request):
    """Global search across all ERP data"""
    results = {
        'employees': [],
        'products': [],
        'customers': [],
        'leaves': [],
        'attendance': [],
        'documents': [],
        'orders': [],
        'payments': [],
    }
    
    query = request.GET.get('q', '').strip()
    
    if query and len(query) >= 2:
        # Search employees
        if request.user.is_superuser:
            results['employees'] = Employee.objects.select_related('user').filter(
                Q(name__icontains=query) |
                Q(employee_id__icontains=query) |
                Q(position__icontains=query) |
                Q(user__username__icontains=query) |
                Q(user__first_name__icontains=query) |
                Q(user__last_name__icontains=query)
            )[:10]
        
        # Search products
        results['products'] = Product.objects.filter(
            name__icontains=query
        )[:10]
        
        # Search customers
        if request.user.is_superuser:
            results['customers'] = Customer.objects.filter(
                Q(name__icontains=query) | Q(email__icontains=query)
            )[:10]
        
        # Search leave applications
        leave_query = Q(leave_type__icontains=query) | Q(status__icontains=query) | Q(reason__icontains=query)
        if request.user.is_superuser:
            leave_query |= Q(employee__username__icontains=query) | Q(employee__first_name__icontains=query) | Q(employee__last_name__icontains=query)
            results['leaves'] = LeaveApplication.objects.filter(leave_query).select_related('employee')[:10]
        else:
            results['leaves'] = LeaveApplication.objects.filter(employee=request.user).filter(leave_query)[:10]
        
        # Search attendance
        attendance_query = Q(status__icontains=query) | Q(approval_status__icontains=query)
        if request.user.is_superuser:
            attendance_query |= Q(employee__username__icontains=query) | Q(employee__first_name__icontains=query) | Q(employee__last_name__icontains=query)
            results['attendance'] = Attendance.objects.filter(attendance_query).select_related('employee')[:10]
        else:
            results['attendance'] = Attendance.objects.filter(employee=request.user).filter(attendance_query)[:10]
        
        # Search uploaded files
        documents = UploadedFile.objects.filter(file__icontains=query)
        if not request.user.is_superuser:
            documents = documents.filter(uploaded_by=request.user)
        results['documents'] = documents[:10]

        if request.user.is_superuser:
            order_query = Q(customer__name__icontains=query) | Q(orderitem__product__name__icontains=query)
            payment_query = Q(order__customer__name__icontains=query) | Q(payment_method__icontains=query)
            if query.isdigit():
                order_query |= Q(pk=int(query))
                payment_query |= Q(order_id=int(query)) | Q(pk=int(query))
            results['orders'] = Order.objects.filter(order_query).select_related('customer').distinct()[:10]
            results['payments'] = Payment.objects.filter(payment_query).select_related('order__customer')[:10]
    
    context = {
        'query': query,
        'results': results,
        'has_results': any(results.values()),
    }
    
    return render(request, 'global_search.html', context)


# ==================== FEATURE 4: ACTIVITY LOG ====================

@login_required
def activity_log(request):
    """View activity log - admins see all, employees see their own"""
    if request.user.is_superuser:
        logs = ActivityLog.objects.all()
    else:
        logs = ActivityLog.objects.filter(user=request.user)
    
    # Filter by action type if provided
    action_type = request.GET.get('action_type', '')
    if action_type:
        logs = logs.filter(action_type=action_type)
    
    # Filter by date if provided
    date_from = request.GET.get('date_from', '')
    if date_from:
        try:
            date_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            logs = logs.filter(timestamp__date__gte=date_obj)
        except:
            pass
    
    logs = logs.order_by('-timestamp')[:200]
    
    context = {
        'logs': logs,
        'action_types': ActivityLog.ACTION_TYPES,
        'selected_action': action_type,
        'selected_date': date_from,
    }
    
    return render(request, 'activity_log.html', context)


# ==================== FEATURE 5: LEAVE CALENDAR ====================

@login_required
def leave_calendar(request):
    """Show leave calendar - organization-wide for admins, personal for employees"""
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Get approved leaves for the month
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    if request.user.is_superuser:
        leaves = LeaveApplication.objects.filter(
            start_date__lte=end_date,
            end_date__gte=start_date
        ).select_related('employee')
    else:
        leaves = LeaveApplication.objects.filter(
            employee=request.user,
            start_date__lte=end_date,
            end_date__gte=start_date
        )
    
    # Get today's leaves
    today = timezone.now().date()
    today_leaves = LeaveApplication.objects.filter(
        status='Approved',
        start_date__lte=today,
        end_date__gte=today
    ).select_related('employee') if request.user.is_superuser else LeaveApplication.objects.filter(
        employee=request.user,
        status='Approved',
        start_date__lte=today,
        end_date__gte=today
    )
    
    # Get upcoming leaves (next 7 days)
    week_later = today + timedelta(days=7)
    upcoming_leaves = LeaveApplication.objects.filter(
        status='Approved',
        start_date__gte=today,
        start_date__lte=week_later
    ).select_related('employee').order_by('start_date') if request.user.is_superuser else []
    
    # Get pending requests
    pending_count = LeaveApplication.objects.filter(status='Pending').count()
    
    context = {
        'year': year,
        'month': month,
        'leaves': leaves,
        'today_leaves': today_leaves,
        'upcoming_leaves': upcoming_leaves,
        'pending_count': pending_count,
        'month_name': datetime(year, month, 1).strftime('%B %Y'),
    }
    
    return render(request, 'leave_calendar.html', context)


# ==================== FEATURE 6: INVENTORY INTELLIGENCE ====================

def get_inventory_summary():
    """Helper function to get inventory health summary"""
    products = Product.objects.all()
    
    healthy = 0
    low_stock = 0
    out_of_stock = 0
    
    for product in products:
        status = product.get_stock_status()
        if status == 'healthy':
            healthy += 1
        elif status == 'low_stock':
            low_stock += 1
        else:
            out_of_stock += 1
    
    return {
        'healthy': healthy,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'total': products.count(),
    }


@login_required
def inventory_dashboard(request):
    """Inventory intelligence and status page"""
    products = Product.objects.all().order_by('name')
    inventory_summary = get_inventory_summary()
    
    # Low stock products
    low_stock_products = [p for p in products if p.get_stock_status() == 'low_stock']
    out_of_stock_products = [p for p in products if p.get_stock_status() == 'out_of_stock']
    
    context = {
        'products': products,
        'inventory_summary': inventory_summary,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
    }
    
    return render(request, 'inventory_dashboard.html', context)
