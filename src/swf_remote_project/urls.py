from django.contrib import admin
from django.urls import path, include
from remote_app.views import logout_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/logout/', logout_view, name='logout'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('remote_app.urls')),
]
