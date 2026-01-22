from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib import admin
from .views import pronos_view, logout_view

# from core.admin import rugby_admin_site

urlpatterns = [
    # path("admin/", rugby_admin_site.urls),
    # path('admin/', admin.site.urls),
    path('pronos/', views.pronos_view, name='pronostics'),
    path('logout/', views.logout_view, name='logout'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
]