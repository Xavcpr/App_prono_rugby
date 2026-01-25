from django.urls import path
from .views import pronos_view, logout_view, settings_view, competition_ranking_view
from backend.core import views

urlpatterns = [
    path("pronos/", pronos_view, name="pronostics"),
    path("logout/", logout_view, name="logout"),
    path('settings/', settings_view, name='settings'),
    path("classement_par_competition/", competition_ranking_view, name="classement_par_competition"),
    path("pronos/classement/", views.classement_prediction, name="classement_prediction"),
]


