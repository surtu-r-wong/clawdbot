class BacktestSystemError(Exception):
    """Base exception for this package."""


class ConfigurationError(BacktestSystemError):
    """Raised when required configuration is missing or invalid."""


class NetworkError(BacktestSystemError):
    """Raised for network/API request failures (retryable)."""


class DataValidationError(BacktestSystemError):
    """Raised when input data is invalid or missing required fields."""


class ModuleError(BacktestSystemError):
    """Raised for internal logic errors or unexpected states."""

