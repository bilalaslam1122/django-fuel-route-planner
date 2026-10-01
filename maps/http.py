from typing import Any

import requests

from .exceptions import MapServiceError, MapServiceTimeout


def get_json(
    session: requests.Session, url: str, *, params: dict[str, Any] | None, timeout: float
) -> Any:
    """GET a JSON document, translating every transport failure into MapServiceError."""
    try:
        response = session.get(url, params=params, timeout=timeout)
    except requests.Timeout as exc:
        raise MapServiceTimeout(f"Timed out after {timeout}s calling {url}") from exc
    except requests.RequestException as exc:
        raise MapServiceError(f"Could not reach {url}: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise MapServiceError(f"{url} returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise MapServiceError(f"{url} returned a non-JSON response") from exc
