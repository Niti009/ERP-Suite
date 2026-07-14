from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect


def is_demo_user(user):
    """Return True when the authenticated user is the special demo account."""
    return user.is_authenticated and user.username == settings.DEMO_LOGIN_USERNAME


def demo_read_only(view_func):
    """Block write actions for the demo account and redirect to the dashboard."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if is_demo_user(request.user):
            messages.error(
                request,
                "Demo mode is read-only. Please sign in with a full account to make changes.",
            )
            return redirect("dashboard")

        return view_func(request, *args, **kwargs)

    return _wrapped_view
