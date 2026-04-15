"""Endpoint and BaseClient abstractions for typed API operations.

Each API endpoint is defined as an Endpoint with its path, caching, rate limiting,
and response model. BaseClient provides get/post/put/delete methods that handle
encoding requests, making HTTP calls, and decoding typed responses.

Request mixins define the three ways data is sent in HTTP:
  - PathRequest: URL path template params (e.g. /accounts/{account_id})
  - ParamsRequest: URL query params (e.g. ?symbol=AAPL)
  - BodyRequest: JSON or form-encoded request body
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

_DEFAULT_CONCURRENCY = 1

# ── Request mixins ──────────────────────────────────────────


class PathRequest:
    """Mixin for requests with URL path template parameters."""

    def to_path_params(self) -> dict[str, str]:
        raise NotImplementedError


class ParamsRequest:
    """Mixin for requests with URL query parameters."""

    def to_params(self) -> dict[str, str]:
        raise NotImplementedError


class BodyRequest:
    """Mixin for requests with a JSON or form-encoded body."""

    def to_body(self) -> dict[str, Any]:
        raise NotImplementedError


# ── Response protocol ───────────────────────────────────────


class ResponseModel(Protocol):
    """Protocol for response models — must parse from JSON and render to markdown."""

    @classmethod
    def from_response(cls, data: Any) -> "ResponseModel": ...

    def to_output(self) -> str: ...


# ── Endpoint ────────────────────────────────────────────────


@dataclass(frozen=True)
class Endpoint:
    """Definition of a single API endpoint.

    path: HTTP path, may contain {templates} for PathRequest substitution.
    cache_ttl: cache duration in seconds (0 = no cache).
    rate_key: rate limiter bucket name (default = 'default').
    response_model: class with from_response(data) and to_output() methods.
    extract: optional callable to unwrap nested response dicts before parsing.
    base_url: override the client's default base URL for this endpoint.
    """

    path: str
    cache_ttl: int = 0
    rate_key: str = "default"
    response_model: type[ResponseModel] | None = None
    extract: Callable[[Any], Any] | None = None
    base_url: str | None = None


# ── BaseClient ──────────────────────────────────────────────


class BaseClient(ABC):
    """Base class for async API clients. Subclasses implement _request() with
    provider-specific auth, HTTP transport, caching, and rate limiting.

    Each client holds an asyncio.Semaphore that serializes concurrent calls.
    The semaphore is acquired in get/post/put/delete (not _request), so internal
    HTTP calls (e.g. token refresh) don't double-acquire.
    """

    _http: Any  # httpx.AsyncClient
    _semaphore: asyncio.Semaphore

    async def aclose(self) -> None:
        """Close the underlying async HTTP client."""
        await self._http.aclose()

    async def get(self, endpoint: Endpoint, request: ParamsRequest) -> Any:
        """Send a GET request and return the typed response model."""
        async with self._semaphore:
            path = self._resolve_path(endpoint, request)
            data = await self._request("GET", endpoint, path=path, params=request.to_params())
            return self._decode(endpoint, data)

    async def post(self, endpoint: Endpoint, request: BodyRequest) -> Any:
        """Send a POST request and return the typed response model."""
        async with self._semaphore:
            path = self._resolve_path(endpoint, request)
            data = await self._request("POST", endpoint, path=path, body=request.to_body())
            return self._decode(endpoint, data)

    async def put(self, endpoint: Endpoint, request: BodyRequest) -> Any:
        """Send a PUT request and return the typed response model."""
        async with self._semaphore:
            path = self._resolve_path(endpoint, request)
            data = await self._request("PUT", endpoint, path=path, body=request.to_body())
            return self._decode(endpoint, data)

    async def delete(self, endpoint: Endpoint, request: ParamsRequest) -> Any:
        """Send a DELETE request and return the typed response model."""
        async with self._semaphore:
            path = self._resolve_path(endpoint, request)
            data = await self._request(
                "DELETE", endpoint, path=path, params=request.to_params()
            )
            return self._decode(endpoint, data)

    @staticmethod
    def _resolve_path(endpoint: Endpoint, request: object) -> str:
        """Resolve path templates using PathRequest.to_path_params() if available."""
        path = endpoint.path
        if isinstance(request, PathRequest) and "{" in path:
            path = path.format_map(request.to_path_params())
        return path

    def _decode(self, endpoint: Endpoint, data: Any) -> Any:
        """Extract raw response and convert to typed response model."""
        if endpoint.extract:
            data = endpoint.extract(data)
        if endpoint.response_model:
            return endpoint.response_model.from_response(data)
        return data

    @abstractmethod
    async def _request(
        self,
        method: str,
        endpoint: Endpoint,
        path: str | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute HTTP request with provider-specific auth, caching, and rate limiting.
        path is the resolved URL path (with templates substituted).
        Returns raw JSON response data."""
