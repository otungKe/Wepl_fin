from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health),
    path("collections/", include("contexts.custody.api.urls")),  # ADR-0018
]
