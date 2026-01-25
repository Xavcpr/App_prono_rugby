from django.urls import path 
from .views import pronos_view, logout_view, settings_view, competition_ranking_view, classement_prediction

urlpatterns = [
    # Page principale des pronos
    path("pronos/", pronos_view, name="pronos"),

    # Déconnexion
    path("logout/", logout_view, name="logout"),

    # Réglages
    path('settings/', settings_view, name='settings'),

    # Classement par compétition (vue générale)
    path("classement_par_competition/", competition_ranking_view, name="classement_par_competition"),

    # Classement spécifique pour une compétition (optionnel : tu peux passer la compétition en GET)
    path("pronos/classement/", classement_prediction, name="classement_prediction"),
]



