"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""


from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

from core import views
from core import pwa_views

urlpatterns = [
    path('admin/saisie-resultats/', views.admin_saisie_resultats, name='admin_saisie_resultats'),
    path('admin/calcul-points/<int:season_id>/', views.declencher_calcul_points, name='calcul_points_classement'),
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    # PWA (application installable sur téléphone)
    path("manifest.webmanifest", pwa_views.pwa_manifest, name="pwa_manifest"),
    path("sw.js", pwa_views.service_worker, name="service_worker"),
    # Fichiers uploadés (photos de profil)
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    # Fichiers statiques (icônes PWA, etc.)
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
]