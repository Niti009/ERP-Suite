from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
import re
import tempfile
from datetime import timedelta
from unittest.mock import patch

from .models import (
    Attendance,
    Customer,
    Department,
    Employee,
    EmployeeInvitation,
    LeaveApplication,
    Notification,
    Order,
    OrderItem,
    Payment,
    Product,
    UploadedFile,
)


class EmployeeProfileTests(TestCase):
    def test_profile_page_creates_missing_employee_profile(self):
        user = get_user_model().objects.create_user(
            username="tester", password="testpass123"
        )

        response = self.client.login(username="tester", password="testpass123")
        self.assertTrue(response)

        response = self.client.get(reverse("employee_profile"))

        self.assertEqual(response.status_code, 200)


class DashboardDataScopeTests(TestCase):
    def test_employee_dashboard_metrics_are_scoped_to_the_current_user(self):
        user_model = get_user_model()
        employee_user = user_model.objects.create_user(username="scope.employee", password="ScopePass!2026")
        other_user = user_model.objects.create_user(username="scope.other", password="ScopePass!2026")
        today = timezone.now().date()
        Attendance.objects.create(employee=employee_user, date=today, status="Present")
        Attendance.objects.create(employee=other_user, date=today, status="Present")
        Attendance.objects.create(employee=other_user, date=today - timedelta(days=1), status="Present")
        LeaveApplication.objects.create(
            employee=employee_user,
            leave_type="Casual",
            start_date=today,
            end_date=today,
            reason="Personal appointment",
        )
        LeaveApplication.objects.create(
            employee=other_user,
            leave_type="Casual",
            start_date=today,
            end_date=today,
            reason="Private request",
        )
        self.client.force_login(employee_user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["present"], 1)
        self.assertEqual(response.context["pending_leaves"], 1)
        self.assertEqual(response.context["total_attendance_today"], 1)


class DashboardGreetingTests(TestCase):
    def test_dashboard_greeting_tracks_local_time_for_employee_and_admin(self):
        user_model = get_user_model()
        employee = user_model.objects.create_user(username="greeting.employee", password="GreetingPass!2026")
        admin = user_model.objects.create_superuser(
            username="greeting.admin", email="greeting.admin@example.com", password="GreetingAdmin!2026"
        )

        for user in (employee, admin):
            self.client.force_login(user)
            for hour, expected in ((8, "Good morning"), (13, "Good afternoon"), (19, "Good evening")):
                with patch("inventory.views.timezone.localtime") as localtime:
                    localtime.return_value.hour = hour
                    response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.context["time_greeting"], expected)
                self.assertContains(response, expected)


class PublicSignupAccessTests(TestCase):
    def test_public_signup_redirects_to_login_without_creating_an_account(self):
        existing_user = get_user_model().objects.create_user(
            username="existing.employee", email="existing@example.com", password="KeepThisPass!2026"
        )
        original_password_hash = existing_user.password

        response = self.client.post(
            reverse("signup"),
            {
                "username": "unapproved.user",
                "email": "unapproved@example.com",
                "password1": "NotAllowed!2026",
                "password2": "NotAllowed!2026",
            },
            follow=True,
        )

        self.assertEqual(response.redirect_chain, [(reverse("login"), 302)])
        self.assertContains(response, "Contact your administrator")
        self.assertFalse(get_user_model().objects.filter(username="unapproved.user").exists())
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.password, original_password_hash)


class AccountAccessTests(TestCase):
    def test_login_page_has_no_public_registration_link(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, "Need access? Contact your administrator.")
        self.assertNotContains(response, "Request account")
        self.assertNotContains(response, "Create your account")

    def test_logout_is_post_only_and_protected_pages_require_login_afterward(self):
        user = get_user_model().objects.create_user(
            username="logout.employee", password="SafeLogout!2026"
        )
        self.client.force_login(user)

        get_response = self.client.get(reverse("logout"))
        self.assertEqual(get_response.status_code, 405)

        logout_response = self.client.post(reverse("logout"))
        self.assertRedirects(logout_response, reverse("login"))
        protected_response = self.client.get(reverse("dashboard"))
        self.assertEqual(protected_response.status_code, 302)
        self.assertTrue(protected_response.url.startswith(reverse("login")))


class DemoLoginTests(TestCase):
    def test_demo_login_creates_account_and_logs_user_in(self):
        response = self.client.get(reverse("demo_login"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard"))

        user = get_user_model().objects.get(username=settings.DEMO_LOGIN_USERNAME)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.groups.exists())
        self.assertFalse(user.user_permissions.exists())
        self.assertFalse(user.has_perm("inventory.add_product"))

    def test_demo_login_is_repeatable(self):
        self.client.get(reverse("demo_login"))
        first_user_id = self.client.session.get("_auth_user_id")

        response = self.client.get(reverse("demo_login"))

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.session.get("_auth_user_id"), first_user_id)
        self.assertEqual(
            get_user_model().objects.filter(
                username=settings.DEMO_LOGIN_USERNAME
            ).count(),
            1,
        )

    def test_demo_login_normalizes_an_existing_privileged_account(self):
        demo_user = get_user_model().objects.create_user(
            username=settings.DEMO_LOGIN_USERNAME,
            password="old-password",
            is_staff=True,
            is_superuser=True,
        )
        demo_user.user_permissions.add(
            Permission.objects.get(codename="add_product")
        )

        response = self.client.get(reverse("demo_login"))

        self.assertRedirects(response, reverse("dashboard"))
        demo_user.refresh_from_db()
        self.assertTrue(demo_user.is_active)
        self.assertFalse(demo_user.is_staff)
        self.assertFalse(demo_user.is_superuser)
        self.assertFalse(demo_user.groups.exists())
        self.assertFalse(demo_user.user_permissions.exists())
        self.assertFalse(demo_user.has_perm("inventory.add_product"))

    def test_regular_username_password_login_still_works(self):
        user = get_user_model().objects.create_user(
            username="regular-user", password="regular-password"
        )

        response = self.client.post(
            reverse("login"),
            {"username": "regular-user", "password": "regular-password"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))

    def test_demo_user_is_blocked_from_mutating_views(self):
        self.client.post(reverse("demo_login"))

        response = self.client.get(reverse("add_product"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard"))


class EmployeeManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="adminuser",
            email="admin@example.com",
            password="StrongPass123!",
        )
        self.department = Department.objects.create(name="Engineering")

    def test_employee_cannot_access_administrator_directory(self):
        employee = get_user_model().objects.create_user(
            username="directory.employee", password="DirectoryPass!2026"
        )
        self.client.force_login(employee)

        response = self.client.get(reverse("employee_list"))

        self.assertRedirects(response, reverse("dashboard"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_admin_creates_employee_invites_and_employee_activates_account(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("employee_create"),
            {
                "first_name": "Aisha",
                "last_name": "Patel",
                "username": "aisha.patel",
                "email": "aisha@company.com",
                "phone": "+1 555 111 0000",
                "date_of_birth": "1995-02-15",
                "gender": "Female",
                "address": "42 Market Street",
                "location": "New York",
                "employee_id": "EMP-101",
                "department": str(self.department.pk),
                "position": "Senior Engineer",
                "joining_date": "2024-01-10",
                "employment_status": "Active",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="aisha.patel")
        employee = Employee.objects.get(employee_id="EMP-101")
        self.assertEqual(employee.user, user)
        self.assertEqual(employee.name, "Aisha Patel")
        self.assertEqual(employee.position, "Senior Engineer")
        self.assertEqual(employee.department, self.department)
        self.assertEqual(employee.location, "New York")
        self.assertEqual(employee.date_of_birth.isoformat(), "1995-02-15")
        self.assertEqual(employee.gender, "Female")
        self.assertEqual(Employee.objects.filter(user=user).count(), 1)
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        invitation = EmployeeInvitation.objects.get(employee=employee)
        self.assertIsNone(invitation.accepted_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Activate your ERP Suite account", mail.outbox[0].subject)

        activation_match = re.search(r"/employees/activate/([^/]+)/([^/\s]+)", mail.outbox[0].body)
        self.assertIsNotNone(activation_match)
        uidb64, token = activation_match.groups()
        activation_path = reverse("employee_activate", kwargs={"uidb64": uidb64, "token": token})
        self.assertEqual(self.client.get(activation_path).status_code, 200)

        mismatch_response = self.client.post(
            activation_path,
            {"new_password1": "First!ValidPassword2026", "new_password2": "Second!ValidPassword2026"},
        )
        self.assertContains(mismatch_response, "The two password fields")

        invalid_password_response = self.client.post(
            activation_path,
            {"new_password1": "password", "new_password2": "password"},
        )
        self.assertEqual(invalid_password_response.status_code, 200)
        self.assertContains(invalid_password_response, "This password is too common.")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        activation_response = self.client.post(
            activation_path,
            {
                "new_password1": "VerySecure!Zebra2026",
                "new_password2": "VerySecure!Zebra2026",
            },
        )
        self.assertRedirects(activation_response, reverse("login"))
        user.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("VerySecure!Zebra2026"))
        self.assertNotEqual(user.password, "VerySecure!Zebra2026")
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(self.client.get(activation_path).status_code, 400)

        login_response = self.client.post(
            reverse("login"),
            {"username": "aisha@company.com", "password": "VerySecure!Zebra2026"},
        )
        self.assertRedirects(login_response, reverse("dashboard"))

    def test_duplicate_employee_credentials_are_rejected(self):
        self.client.force_login(self.admin)
        get_user_model().objects.create_user(
            username="existing.user",
            email="existing@example.com",
            password="StrongPass123!",
        )
        duplicate_employee_user = get_user_model().objects.create_user(
            username="employee-dup",
            email="dup@example.com",
            password="StrongPass123!",
        )
        duplicate_employee = Employee.objects.get(user=duplicate_employee_user)
        duplicate_employee.employee_id = "EMP-200"
        duplicate_employee.save(update_fields=["employee_id"])

        response = self.client.post(
            reverse("employee_create"),
            {
                "first_name": "New",
                "last_name": "User",
                "username": "existing.user",
                "email": "existing@example.com",
                "phone": "+1 555 222 0000",
                "date_of_birth": "1992-05-10",
                "gender": "Male",
                "address": "Test Address",
                "location": "Austin",
                "employee_id": "EMP-200",
                "department": str(self.department.pk),
                "position": "Manager",
                "joining_date": "2024-02-01",
                "employment_status": "Active",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_resending_invitation_invalidates_the_old_link(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("employee_create"),
            {
                "first_name": "Sam",
                "last_name": "Rivera",
                "username": "sam.rivera",
                "email": "sam@company.com",
                "employee_id": "EMP-RESEND",
                "department": str(self.department.pk),
                "position": "Analyst",
                "joining_date": "2025-02-01",
                "employment_status": "Active",
            },
        )
        employee = Employee.objects.get(employee_id="EMP-RESEND")
        old_link = re.search(r"/employees/activate/([^/]+)/([^/\s]+)", mail.outbox[0].body)
        old_path = reverse("employee_activate", kwargs={"uidb64": old_link.group(1), "token": old_link.group(2)})
        previous_hash = employee.invitation.token_hash

        resend_response = self.client.post(
            reverse("resend_employee_invitation", kwargs={"employee_id": employee.pk})
        )

        self.assertRedirects(resend_response, reverse("employee_detail", kwargs={"employee_id": employee.pk}))
        employee.invitation.refresh_from_db()
        self.assertNotEqual(employee.invitation.token_hash, previous_hash)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.client.get(old_path).status_code, 400)
        new_link = re.search(r"/employees/activate/([^/]+)/([^/\s]+)", mail.outbox[1].body)
        new_path = reverse("employee_activate", kwargs={"uidb64": new_link.group(1), "token": new_link.group(2)})
        employee.invitation.expires_at = timezone.now() - timedelta(seconds=1)
        employee.invitation.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(new_path).status_code, 400)


class ExistingModuleIntegrationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="module.admin", email="module.admin@example.com", password="ModuleAdmin!2026"
        )
        self.employee = get_user_model().objects.create_user(
            username="module.employee", password="ModuleEmployee!2026"
        )
        self.customer = Customer.objects.create(
            name="Northwind Office", email="office@example.com", phone="555-0100", address="Market Street"
        )
        self.product = Product.objects.create(name="Ergonomic Desk", quantity=8, price="499.00")
        self.order = Order.objects.create(customer=self.customer, total_amount="998.00")
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price="499.00")
        self.payment = Payment.objects.create(
            order=self.order, amount="998.00", payment_method="Bank transfer"
        )

    def test_admin_order_payment_lists_and_global_search_use_existing_records(self):
        self.client.force_login(self.admin)

        order_response = self.client.get(reverse("order_list"), {"q": "Northwind"})
        payment_response = self.client.get(reverse("payment_list"), {"q": "Bank transfer"})
        search_response = self.client.get(reverse("global_search"), {"q": "Northwind"})

        self.assertContains(order_response, "Northwind Office")
        self.assertContains(payment_response, "Bank transfer")
        self.assertContains(search_response, f"Order #{self.order.pk}")
        self.assertContains(search_response, "Payments")

    def test_employee_cannot_view_order_or_payment_lists(self):
        self.client.force_login(self.employee)

        self.assertRedirects(self.client.get(reverse("order_list")), reverse("dashboard"))
        self.assertRedirects(self.client.get(reverse("payment_list")), reverse("dashboard"))

    def test_employee_document_list_and_search_are_scoped_to_owned_documents(self):
        own_document = UploadedFile.objects.create(file="uploads/employee-guide.pdf", uploaded_by=self.employee)
        UploadedFile.objects.create(file="uploads/admin-only.pdf", uploaded_by=self.admin)
        self.client.force_login(self.employee)

        upload_response = self.client.get(reverse("upload_file"))
        search_response = self.client.get(reverse("global_search"), {"q": "employee-guide"})

        visible_documents = list(upload_response.context["uploaded_files"])
        self.assertEqual(visible_documents, [own_document])
        self.assertContains(search_response, "employee-guide.pdf")
        self.assertNotContains(search_response, "admin-only.pdf")

    def test_notification_read_actions_require_post_and_are_user_scoped(self):
        notification = Notification.objects.create(
            user=self.employee,
            notification_type="system_alert",
            title="Account notice",
            description="A real notification.",
            related_link="https://not-allowed.example/path",
        )
        self.client.force_login(self.employee)

        get_response = self.client.get(reverse("mark_notification_read", kwargs={"notification_id": notification.pk}))
        self.assertEqual(get_response.status_code, 405)
        post_response = self.client.post(reverse("mark_notification_read", kwargs={"notification_id": notification.pk}))
        self.assertRedirects(post_response, reverse("notifications_list"))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

        all_read_get = self.client.get(reverse("mark_all_notifications_read"))
        self.assertEqual(all_read_get.status_code, 405)

    def test_employee_shortcut_redirects_to_protected_directory(self):
        self.client.force_login(self.admin)

        response = self.client.get("/employees/")

        self.assertRedirects(response, reverse("employee_list"))


class EmployeeNotificationWorkflowTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="notify.admin", email="notify.admin@example.com", password="NotifyAdmin!2026"
        )
        self.employee = get_user_model().objects.create_user(
            username="notify.employee", email="notify.employee@example.com", password="NotifyEmployee!2026"
        )
        self.employee_record = Employee.objects.get(user=self.employee)

    def test_admin_prompt_is_delivered_to_employee_notifications(self):
        self.client.force_login(self.employee)
        denied_response = self.client.post(
            reverse("send_employee_prompt", kwargs={"employee_id": self.employee_record.pk}),
            {"title": "Unauthorized", "message": "This must not be delivered."},
        )
        self.assertRedirects(denied_response, reverse("dashboard"))
        self.assertFalse(Notification.objects.filter(user=self.employee, title="Unauthorized").exists())

        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("send_employee_prompt", kwargs={"employee_id": self.employee_record.pk}),
            {"title": "Please confirm your schedule", "message": "Reply with your availability for Friday."},
        )

        self.assertRedirects(
            response,
            reverse("employee_detail", kwargs={"employee_id": self.employee_record.pk}),
        )
        notification = Notification.objects.get(user=self.employee, notification_type="admin_prompt")
        self.assertEqual(notification.title, "Please confirm your schedule")
        self.assertEqual(notification.description, "Reply with your availability for Friday.")

        self.client.force_login(self.employee)
        notification_response = self.client.get(reverse("notifications_list"))
        self.assertContains(notification_response, "Please confirm your schedule")
        self.assertContains(notification_response, "Reply with your availability for Friday.")

    def test_employee_leave_attendance_and_profile_actions_notify_admin(self):
        self.client.force_login(self.employee)
        today = timezone.now().date()

        leave_response = self.client.post(
            reverse("apply_leave"),
            {"start_date": today.isoformat(), "end_date": today.isoformat(), "reason": "Medical appointment"},
        )
        self.assertRedirects(leave_response, reverse("view_leaves"))

        attendance_response = self.client.post(reverse("dashboard"))
        self.assertRedirects(attendance_response, reverse("dashboard"))

        profile_response = self.client.post(
            reverse("edit_profile"),
            {
                "first_name": "Notify",
                "last_name": "Employee",
                "email": "notify.employee@example.com",
                "phone": "555-0123",
                "position": "Not Assigned",
                "department": "",
                "employee_id": "",
                "location": "Office",
                "bio": "Updated contact details.",
            },
        )
        self.assertRedirects(profile_response, reverse("employee_profile"))

        admin_notifications = self.admin.notifications.filter(notification_type="employee_activity")
        self.assertGreaterEqual(admin_notifications.count(), 3)
        self.assertTrue(admin_notifications.filter(title="Employee leave request submitted").exists())
        self.assertTrue(admin_notifications.filter(title="Employee attendance submitted").exists())
        self.assertTrue(admin_notifications.filter(title="Employee profile updated").exists())

    def test_employee_document_upload_notifies_admin(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.employee)
            response = self.client.post(
                reverse("upload_file"),
                {"file": SimpleUploadedFile("employee-note.txt", b"Updated employee details.", content_type="text/plain")},
            )

        self.assertRedirects(response, reverse("upload_file"))
        self.assertTrue(
            self.admin.notifications.filter(
                notification_type="employee_activity",
                title="Employee document uploaded",
            ).exists()
        )
