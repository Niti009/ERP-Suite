from .models import AuditLog

def log_action(user, action):
    AuditLog.objects.create(user=user, action=action)
