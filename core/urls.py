from django.urls import path 
from .views import charte_view, admin_saisie_resultats, declencher_calcul_points, recap_pronos_classement, debug_scores_view, statistics_view, statistiques_view, all_pronos_view, compute_round_view, pronos_view, logout_view, round_results_board, settings_view, competition_ranking_view, classement_prediction

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
    
    path('tous-les-pronos/', all_pronos_view, name='all_pronos'),
    
    # Page du tableau des scores (Remplace <int:round_id> par ton identifiant de journée)
    path('resultats/<int:round_id>/', round_results_board, name='round_board'),
    
    # Optionnel : Route pour lancer le calcul des points
    path('calculer-points/<int:round_id>/', compute_round_view, name='compute_points'),
    
     # Statistiques générales sur les paris   
    path("statistiques/", statistiques_view, name="statistiques"),
    
    path('debug-scores/', debug_scores_view, name='debug_scores'),
    
    path('classement/recap/', recap_pronos_classement, name='recap_classement'),
    
    path('admin/saisie-resultats/', admin_saisie_resultats, name='admin_saisie_resultats'),
    path('admin/calcul-points/<int:season_id>/', declencher_calcul_points, name='calcul_points_classement'),
    path('charte/', charte_view, name='charte'),
    path('stats-scores/', statistics_view, name='scores_statistics'),
]



