from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class EmployeeProfileTests(TestCase):
    def test_profile_page_creates_missing_employee_profile(self):
        user = User.objects.create_user(username="tester", password="testpass123")

        response = self.client.login(username="tester", password="testpass123")
        self.assertTrue(response)

        response = self.client.get(reverse("employee_profile"))

        self.assertEqual(response.status_code, 200)
