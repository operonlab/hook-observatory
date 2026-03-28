"""CLI exit code convention — structured error contract.

Inspired by acpx's machine-readable error codes.
Enables Cronicle/headless automation to programmatically handle errors.

Standard exit codes:
    0   Success
    1   General error
    2   Permission denied / authentication failure (HTTP 401/403)
    3   Resource not found (HTTP 404)
    4   Input validation error (HTTP 400/422)
    124 Operation timed out (matches GNU coreutils timeout convention)
    125 Backend service unavailable (connection refused, API down, DB unreachable)
"""

EXIT_SUCCESS = 0
EXIT_ERROR = 1       # General error — fallback for unclassified failures
EXIT_PERMISSION = 2  # HTTP 401 / 403: auth failure or permission denied
EXIT_NOT_FOUND = 3   # HTTP 404: resource not found
EXIT_VALIDATION = 4  # HTTP 400 / 422: bad request or validation error
EXIT_TIMEOUT = 124   # Timeout (matches GNU coreutils `timeout` command)
EXIT_SERVICE = 125   # Backend unavailable: connection refused, API down


def exit_code_for(exc) -> int:
    """Return the appropriate exit code for an APIError or APIConnectionError.

    Args:
        exc: An APIError (with .status_code) or APIConnectionError instance.

    Returns:
        One of the EXIT_* constants defined in this module.
    """
    from sdk_client._base import APIConnectionError, APIError

    if isinstance(exc, APIConnectionError):
        return EXIT_SERVICE
    if isinstance(exc, APIError):
        code = exc.status_code
        if code in (401, 403):
            return EXIT_PERMISSION
        if code == 404:
            return EXIT_NOT_FOUND
        if code in (400, 422):
            return EXIT_VALIDATION
        if code == 408:
            return EXIT_TIMEOUT
    return EXIT_ERROR
