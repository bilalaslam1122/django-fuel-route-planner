from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .planner import TripPlanner
from .serializers import RouteRequestSerializer


class RoutePlanView(APIView):
    """POST {"start": "...", "finish": "..."} -> route + cheapest fuel stops."""

    def post(self, request: Request) -> Response:
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(TripPlanner().plan(data["start"], data["finish"], data["include_geometry"]))
