from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Employee, Department
from datetime import date

@receiver(post_save, sender=User)
def create_employee_profile(sender, instance, created, **kwargs):
    if created:
        department, _ = Department.objects.get_or_create(name='General')
        Employee.objects.get_or_create(
            user=instance,
            defaults={
                'name': instance.get_full_name().strip() or instance.username,
                'position': 'Not Assigned',
                'salary': 0.00,
                'joining_date': date.today(),
                'department': department,
            },
        )
