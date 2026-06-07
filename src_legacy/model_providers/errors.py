from __future__ import annotations


class ModelProviderError(RuntimeError):
    """Base error for model-provider failures."""


class ModelProviderConfigError(ModelProviderError):
    """Raised when a provider is missing required local configuration."""


class ModelProviderAPIError(ModelProviderError):
    """Raised when a provider API call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: object | None = None,
        provider_data: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.provider_data = provider_data or {}
