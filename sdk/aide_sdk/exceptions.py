class AideApiError(Exception):
    def __init__(self, status_code: int, error_code: str, detail: str):
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        super().__init__(f"{error_code}: {detail}")


class NotFoundError(AideApiError):
    pass


class ConflictError(AideApiError):
    pass


class ValidationError(AideApiError):
    pass


class AuthError(AideApiError):
    pass


def raise_for_status(status_code: int, error_code: str, detail: str) -> None:
    if 200 <= status_code < 300:
        return
    cls = {
        401: AuthError,
        403: AuthError,
        404: NotFoundError,
        409: ConflictError,
        422: ValidationError,
    }.get(status_code, AideApiError)
    raise cls(status_code=status_code, error_code=error_code, detail=detail)
