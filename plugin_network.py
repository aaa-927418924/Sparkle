"""Bounded HTTPS requests for permissioned Sparkle feature plugins."""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse
from typing import Any


MAX_REQUEST_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_HEADER_COUNT = 32
MAX_HEADER_BYTES = 16 * 1024
MAX_HEADER_VALUE_BYTES = 8 * 1024
NETWORK_TIMEOUT_SECONDS = 20
ALLOWED_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
BLOCKED_HEADERS = {
    "accept-encoding",
    "connection",
    "content-length",
    "cookie",
    "host",
    "keep-alive",
    "origin",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "referer",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class PluginNetworkError(ValueError):
    """A plugin network request is invalid or exceeded a safety limit."""


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to an already checked IP while retaining hostname TLS checks."""

    def __init__(self, host: str, address: str, port: int):
        super().__init__(host, port=port, timeout=NETWORK_TIMEOUT_SECONDS, context=ssl.create_default_context())
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port),
            timeout=self.timeout,
            source_address=self.source_address,
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _public_address(host: str, port: int) -> str:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise PluginNetworkError("The requested host could not be resolved.") from exc
        addresses = {answer[4][0].split("%", 1)[0] for answer in answers}
    else:
        addresses = {str(literal)}

    if not addresses:
        raise PluginNetworkError("The requested host has no network address.")
    parsed_addresses = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise PluginNetworkError("The requested host has an invalid network address.") from exc
        if not parsed.is_global:
            raise PluginNetworkError("Only publicly routable HTTPS hosts are available to plugins.")
        parsed_addresses.append((parsed.version, str(parsed)))
    parsed_addresses.sort()
    return parsed_addresses[0][1]


def _validate_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, dict) or len(headers) > MAX_HEADER_COUNT:
        raise PluginNetworkError("Request headers are invalid or exceed the limit.")

    normalized: dict[str, str] = {}
    total_bytes = 0
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise PluginNetworkError("Request header names and values must be text.")
        name = raw_name.strip()
        value = raw_value.strip()
        if not name or not HEADER_NAME_PATTERN.fullmatch(name):
            raise PluginNetworkError("A request header name is invalid.")
        lowered = name.lower()
        if lowered in BLOCKED_HEADERS or lowered.startswith("sec-"):
            raise PluginNetworkError(f"The {name} request header cannot be set by a plugin.")
        if any(ord(char) < 32 and char != "\t" for char in value) or "\r" in value or "\n" in value:
            raise PluginNetworkError("A request header value contains invalid characters.")
        value_bytes = len(value.encode("utf-8"))
        if value_bytes > MAX_HEADER_VALUE_BYTES:
            raise PluginNetworkError("A request header value exceeds the limit.")
        total_bytes += len(name.encode("ascii")) + value_bytes
        normalized[name] = value

    if total_bytes > MAX_HEADER_BYTES:
        raise PluginNetworkError("Request headers exceed the total size limit.")
    return normalized


def perform_plugin_network_request(
    *,
    url: str,
    method: str = "GET",
    headers: Any = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Make one bounded HTTPS request without redirects or access to private IPs."""

    if not isinstance(url, str) or len(url) > 2_048:
        raise PluginNetworkError("The request URL is invalid or exceeds the limit.")
    if any(ord(char) < 32 for char in url):
        raise PluginNetworkError("The request URL contains invalid characters.")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port or 443
    except ValueError as exc:
        raise PluginNetworkError("The request URL is invalid.") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port != 443
    ):
        raise PluginNetworkError("Plugin requests must use a public HTTPS URL on port 443.")

    request_method = method.upper() if isinstance(method, str) else ""
    if request_method not in ALLOWED_METHODS:
        raise PluginNetworkError("The request method is not supported.")
    request_headers = _validate_headers(headers)
    if body is not None and not isinstance(body, str):
        raise PluginNetworkError("The request body must be text.")
    request_body = body.encode("utf-8") if body is not None else None
    if request_body is not None and len(request_body) > MAX_REQUEST_BYTES:
        raise PluginNetworkError("The request body exceeds the size limit.")
    if request_method in {"GET", "HEAD"} and request_body:
        raise PluginNetworkError("GET and HEAD requests cannot include a body.")

    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise PluginNetworkError("The request hostname is invalid.") from exc
    pinned_address = _public_address(host, port)
    path = urllib.parse.quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parsed.query:
        path += "?" + urllib.parse.quote(parsed.query, safe="/?%:@!$&'()*+,;=-._~")
    request_headers["Accept-Encoding"] = "identity"

    connection = _PinnedHTTPSConnection(host, pinned_address, port)
    try:
        connection.request(request_method, path, body=request_body, headers=request_headers)
        response = connection.getresponse()
        response_body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(response_body) > MAX_RESPONSE_BYTES:
            raise PluginNetworkError("The response exceeds the size limit.")
        return {
            "status": int(response.status),
            "headers": {
                "content-type": response.getheader("Content-Type", ""),
                "location": response.getheader("Location", ""),
            },
            "body": response_body.decode("utf-8", errors="replace"),
        }
    except PluginNetworkError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise PluginNetworkError("The HTTPS request could not be completed.") from exc
    finally:
        connection.close()
