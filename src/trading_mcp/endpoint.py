"""Endpoint and BaseClient abstractions for typed API operations.

Each API endpoint is defined as an Endpoint with its path, caching, rate limiting,
and response model. BaseClient provides get/post/delete methods that handle
encoding requests, making HTTP calls, and decoding responses to markdown.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GetRequest(Protocol):
    """Protocol for GET request models — must produce query params."""

    def to_params(self) -> dict[str, str]: ...


@runtime_checkable
class PostRequest(Protocol):
    """Protocol for POST request models — must produce a JSON body."""

    def to_body(self) -> dict[str, Any]: ...


class ResponseModel(Protocol):
    """Protocol for response models — must parse from JSON and render to markdown."""

    @classmethod
    def from_response(cls, data: Any) -> "ResponseModel": ...

    def to_markdown(self) -> str: ...


@dataclass(frozen=True)
class Endpoint:
    """Definition of a single API endpoint.

    path: HTTP path (e.g. '/openapi/assets/balance').
    cache_ttl: cache duration in seconds (0 = no cache).
    rate_key: rate limiter bucket name (default = 'default').
    response_model: class with from_response(data) and to_markdown() methods.
    extract: optional callable to unwrap nested response dicts before parsing.
    """

    path: str
    cache_ttl: int = 0
    rate_key: str = "default"
    response_model: type[ResponseModel] | None = None
    extract: Callable[[Any], Any] | None = None


class BaseClient(ABC):
    """Base class for API clients. Subclasses implement _request() with provider-specific
    auth, HTTP transport, caching, and rate limiting."""

    def get(self, endpoint: Endpoint, request: GetRequest) -> str:
        """Send a GET request and return the decoded markdown response."""
        data = self._request("GET", endpoint, params=request.to_params())
        return self._decode(endpoint, data)

    def post(self, endpoint: Endpoint, request: PostRequest) -> str:
        """Send a POST request and return the decoded markdown response."""
        params = request.to_params() if isinstance(request, GetRequest) else None
        data = self._request("POST", endpoint, params=params, body=request.to_body())
        return self._decode(endpoint, data)

    def put(self, endpoint: Endpoint, request: PostRequest) -> str:
        """Send a PUT request and return the decoded markdown response."""
        params = request.to_params() if isinstance(request, GetRequest) else None
        data = self._request("PUT", endpoint, params=params, body=request.to_body())
        return self._decode(endpoint, data)

    def delete(self, endpoint: Endpoint, request: GetRequest) -> str:
        """Send a DELETE request and return the decoded markdown response."""
        data = self._request("DELETE", endpoint, params=request.to_params())
        return self._decode(endpoint, data)

    def _decode(self, endpoint: Endpoint, data: Any) -> str:
        """Extract and transform raw API response to markdown."""
        if endpoint.extract:
            data = endpoint.extract(data)
        if endpoint.response_model:
            return endpoint.response_model.from_response(data).to_markdown()
        return json.dumps(data, indent=2, default=str)

    @abstractmethod
    def _request(
        self,
        method: str,
        endpoint: Endpoint,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with provider-specific auth, caching, and rate limiting.
        Returns raw JSON response data."""
