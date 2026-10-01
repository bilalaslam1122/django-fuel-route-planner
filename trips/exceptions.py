"""Trip-planning errors and the API-wide error format.

Every error response looks like:
    {"error": {"code": "location_outside_usa", "message": "...", "details": {...}}}
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class TripPlanningError(Exception):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "trip_planning_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LocationNotFound(TripPlanningError):
    code = "location_not_found"


class LocationOutsideUSA(TripPlanningError):
    code = "location_outside_usa"


class SameLocation(TripPlanningError):
    code = "same_location"


class RouteNotFound(TripPlanningError):
    code = "route_not_found"


class NoFeasibleFuelPlan(TripPlanningError):
    code = "no_feasible_fuel_plan"


class FuelDataUnavailable(TripPlanningError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "fuel_data_unavailable"


class MapServiceUnavailable(TripPlanningError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "map_service_unavailable"


class MapServiceTimedOut(TripPlanningError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "map_service_timeout"


def error_response(status_code: int, code: str, message: str, details: dict | None = None) -> Response:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return Response({"error": body}, status=status_code)


_DRF_CODES = {
    drf_exceptions.ParseError: ("malformed_json", "Request body is not valid JSON."),
    drf_exceptions.UnsupportedMediaType: ("unsupported_media_type", "Send the body as application/json."),
    drf_exceptions.MethodNotAllowed: ("method_not_allowed", None),
    drf_exceptions.NotFound: ("not_found", None),
}


def api_exception_handler(exc: Exception, context: dict) -> Response:
    if isinstance(exc, TripPlanningError):
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    if isinstance(exc, drf_exceptions.ValidationError):
        return error_response(400, "invalid_request", "The request body is invalid.", exc.detail)

    response = drf_exception_handler(exc, context)
    if response is not None:
        code, message = next(
            (v for k, v in _DRF_CODES.items() if isinstance(exc, k)), ("request_error", None)
        )
        return error_response(response.status_code, code, message or str(exc.detail))

    logger.exception("Unhandled error while processing %s", context.get("request"))
    return error_response(500, "internal_error", "An unexpected error occurred.")
