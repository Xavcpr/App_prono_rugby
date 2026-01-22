from django.urls import path
from .views import pronos_view, logout_view

urlpatterns = [
    path("pronos/", pronos_view, name="pronostics"),
    path("logout/", logout_view, name="logout"),
]

# from django.http import HttpResponse

# def test_url(request):
#     return HttpResponse("OK PRONOS")

# urlpatterns = [
#     path("pronos/", pronos_view, name="pronostics"),
#     path("test-pronos/", test_url),
# ]
