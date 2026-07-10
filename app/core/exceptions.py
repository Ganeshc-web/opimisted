class APIError(Exception):
    def __init__(self, code: str, message: str, field: str = None, http_status: int = 400):
        self.code = code
        self.message = message
        self.field = field
        self.http_status = http_status
        super().__init__(message)


ERRORS = {
    "INVALID_INPUT":     400,
    "INVALID_API_KEY":   401,
    "FORBIDDEN":         403,
    "NOT_FOUND":         404,
    "CALCULATION_ERROR": 422,
    "CONFIG_ERROR":      500,
    "INTERNAL_ERROR":    500,
}
