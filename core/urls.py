from django.urls import path
from .views import pronos_view, logout_view

urlpatterns = [
    path("pronos/", pronos_view, name="pronostics"),
    path("logout/", logout_view, name="logout"),
]