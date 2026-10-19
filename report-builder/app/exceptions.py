"""Our own errors. Each one maps to a clean HTTP status and a safe message."""


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class FileRejected(AppError):
    """The file itself is not acceptable (wrong type, too big, corrupt)."""
    status_code = 400
    code = "file_rejected"


class DuplicateFile(AppError):
    status_code = 409
    code = "duplicate_file"


class ValidationFailed(AppError):
    """The file opened fine but the data inside is not usable."""
    status_code = 422
    code = "validation_failed"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
