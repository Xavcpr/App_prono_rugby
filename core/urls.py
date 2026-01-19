from django.urls import path
from . import views

urlpatterns = [
    path('pronos/', views.pronos_view, name='pronos'),
]