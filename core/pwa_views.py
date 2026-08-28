import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse

APP_NAME = "Pronos Rugby"
APP_SHORT_NAME = "Pronos"
APP_THEME_COLOR = "#212529"
APP_BG_COLOR = "#0f172a"


def pwa_manifest(request):
    base = request.build_absolute_uri("/")
    icons = [
        {
            "src": base + "static/pwa/icon-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": base + "static/pwa/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": base + "static/pwa/maskable-icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ]
    return JsonResponse(
        {
            "name": APP_NAME,
            "short_name": APP_SHORT_NAME,
            "description": "Pronostics rugby : devine les scores, marque des points, grimpe au classement.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": APP_THEME_COLOR,
            "theme_color": APP_THEME_COLOR,
            "lang": "fr",
            "icons": icons,
        },
        json_dumps_params={"ensure_ascii": False},
        content_type="application/manifest+json",
    )


def service_worker(request):
    path = settings.BASE_DIR / "core" / "static" / "pwa" / "sw.js"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return HttpResponse(status=404)
    return HttpResponse(
        content,
        content_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )