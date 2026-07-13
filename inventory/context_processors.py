from .models import LeaveApplication


def pending_leave_notifications(request):
    pending_leaves = LeaveApplication.objects.filter(status="Pending").order_by("-start_date")[:5]
    return {
        "pending_leave_requests": pending_leaves,
        "pending_leave_count": pending_leaves.count(),
    }
