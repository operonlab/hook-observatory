"""Workshop error hierarchy (minimal subset for paper-svc)."""


class WorkshopError(Exception):
    status_code: int = 500
    code: str = "system.internal_error"

    def __init__(self, detail: str, *, code: str | None = None):
        self.detail = detail
        if code:
            self.code = code
        super().__init__(detail)


class NotFoundError(WorkshopError):
    status_code = 404
    code = "system.not_found"

    def __init__(self, detail: str = "Not found", code: str | None = None):
        super().__init__(detail, code=code or self.code)


class ForbiddenError(WorkshopError):
    status_code = 403
    code = "system.forbidden"

    def __init__(self, detail: str = "Forbidden", code: str | None = None):
        super().__init__(detail, code=code or self.code)


class BadRequestError(WorkshopError):
    status_code = 400
    code = "system.bad_request"

    def __init__(self, detail: str = "Bad request", code: str | None = None):
        super().__init__(detail, code=code or self.code)


class ConflictError(WorkshopError):
    status_code = 409
    code = "system.conflict"

    def __init__(self, detail: str = "Conflict", code: str | None = None):
        super().__init__(detail, code=code or self.code)
