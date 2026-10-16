from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from inventory import views as inventory_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('inventory.urls')),
]

if settings.DEBUG:
    private_uploads_route = f"{settings.MEDIA_URL.lstrip('/')}uploads/<path:path>"
    urlpatterns.append(path(private_uploads_route, inventory_views.block_private_upload_media))
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)