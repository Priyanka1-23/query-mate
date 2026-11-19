"""Application-specific exceptions. Messages are safe to show to users."""


class QueryMateError(Exception):
    """Base class. `str(e)` is always safe to display in the UI."""


class ConnectionFailedError(QueryMateError):
    pass


class SchemaExtractionError(QueryMateError):
    pass


class AIServiceError(QueryMateError):
    pass


class AIConfigurationError(AIServiceError):
    pass


class SQLValidationError(QueryMateError):
    pass


class QueryExecutionError(QueryMateError):
    pass


class QueryTimeoutError(QueryExecutionError):
    pass


class ContextMismatchError(QueryMateError):
    """Raised when something would run against a different database than intended."""
