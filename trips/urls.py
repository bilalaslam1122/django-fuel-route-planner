from django.urls import re_path

from .views import RoutePlanView

urlpatterns = [
    # Trailing slash optional: POSTs can't be redirected to add it.
    re_path(r"^route/?$", RoutePlanView.as_view(), name="route-plan"),
]
