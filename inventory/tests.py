from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import Department, Employee


class EmployeeProfileTests(TestCase):
    def test_profile_page_creates_missing_employee_profile(self):
        user = get_user_model().objects.create_user(
            username="tester", password="testpass123"
        )

        response = self.client.login(username="tester", password="testpass123")
        self.assertTrue(response)

        response = self.client.get(reverse("employee_profile"))

        self.assertEqual(response.status_code, 200)


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

    def test_admin_can_create_employee_from_enterprise_ui(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("employee_create"),
            {
                "first_name": "Aisha",
                "last_name": "Patel",
                "username": "aisha.patel",
                "email": "aisha@company.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
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
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="aisha.patel").exists())
        self.assertTrue(Employee.objects.filter(employee_id="EMP-101").exists())

    def test_duplicate_employee_credentials_are_rejected(self):
        self.client.force_login(self.admin)
        get_user_model().objects.create_user(
            username="existing.user",
            email="existing@example.com",
            password="StrongPass123!",
        )
        Employee.objects.create(
            user=get_user_model().objects.create_user(
                username="employee-dup",
                email="dup@example.com",
                password="StrongPass123!",
            ),
            name="Existing Employee",
            position="Analyst",
            salary=0,
            joining_date="2024-01-01",
            employee_id="EMP-200",
        )

        response = self.client.post(
            reverse("employee_create"),
            {
                "first_name": "New",
                "last_name": "User",
                "username": "existing.user",
                "email": "existing@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
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
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
