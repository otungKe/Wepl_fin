from django.http import JsonResponse
from django.urls import include, path

from contexts.operations.api.views import inbox as operations_inbox


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health),
    path("collections/", include("contexts.custody.api.urls")),  # ADR-0019
    path("operators/inbox", operations_inbox),  # ADR-0020, behind operator sign-in (ADR-0021)
    path("operators/", include("contexts.operators.api.urls")),  # ADR-0021
]
