from django.urls import path
from .views import pronos_view, logout_view, settings_view, competition_ranking_view, classement_prediction

urlpatterns = [
    path("pronos/", pronos_view, name="pronostics"),
    path("logout/", logout_view, name="logout"),
    path('settings/', settings_view, name='settings'),
    path("classement_par_competition/", competition_ranking_view, name="classement_par_competition"),
    path("pronos/classement/<int:competition_id>/", classement_prediction, name="classement_prediction",
    ),
]


