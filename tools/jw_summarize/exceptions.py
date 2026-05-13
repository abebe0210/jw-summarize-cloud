class JWSummarizeError(RuntimeError):
    """Base application error."""


class ConfigError(JWSummarizeError):
    """Raised when required configuration is missing or invalid."""


class ValidationError(JWSummarizeError):
    """Raised when request payload validation fails."""


class ProcessingError(JWSummarizeError):
    """Raised when summarization or rendering fails."""


class PublishError(JWSummarizeError):
    """Raised when publishing output fails."""


class AuthError(JWSummarizeError):
    """Raised when request authentication fails."""
