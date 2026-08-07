from django.contrib import admin
from django.urls import path, include
from remote_app.views import logout_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/logout/', logout_view, name='logout'),
    # Django's auth URLs stay ahead of allauth's, so the local username and
    # password form remains the page at accounts/login/. allauth serves only
    # what falls through, which is the GitHub flow under accounts/github/.
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/', include('allauth.urls')),
    path('', include('remote_app.urls')),
]
