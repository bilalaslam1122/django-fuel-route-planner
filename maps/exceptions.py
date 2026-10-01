class MapServiceError(Exception):
    """An external map provider failed (timeout, HTTP error, malformed response).

    The message is safe to log; it is never forwarded verbatim to API clients.
    """


class MapServiceTimeout(MapServiceError):
    pass
