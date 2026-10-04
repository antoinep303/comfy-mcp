"""Present local ComfyUI output URLs on the public HTTPS base.

comfy-cli returns the URL it used to reach ComfyUI. With
``COMFY_LOCAL_URL=http://127.0.0.1:8189`` that address is right for the
server and useless to a remote MCP client. ``COMFY_MCP_PUBLIC_BASE_URL`` is
the externally reachable base those clients should open.

This module rewrites strings only. It does not change comfy-cli stdout, job
state, or the URL ``comfy download`` uses. Callers apply
:func:`publicize_client_result` to the object they are about to return.

``COMFY_LOCAL_URL`` is read here only to recognize that local origin. comfy-cli
still owns the connection. This server does not turn the variable into
``--host`` / ``--port``.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# comfy-cli's own default when COMFY_LOCAL_URL is unset. README precedence:
# the variable, then a background server, then this address.
_DEFAULT_LOCAL_URL = "http://127.0.0.1:8188"


def _origin(url: str) -> tuple[str, str, int] | None:
    """``(scheme, hostname, port)`` or ``None`` when ``url`` is not an HTTP(S) origin."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname or port is None:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return parts.scheme, parts.hostname.casefold(), port


def _local_origin() -> tuple[str, str, int] | None:
    """The ComfyUI origin whose ``/view?type=output`` links may be published.

    An unset variable uses comfy-cli's default. A set but unusable value
    publishes nothing: guessing ``127.0.0.1:8188`` would rewrite the wrong host.
    """
    raw = os.environ.get("COMFY_LOCAL_URL", "").strip()
    if not raw:
        raw = _DEFAULT_LOCAL_URL
    parts = urlsplit(raw)
    # A path on the local URL is not part of the origin. A query or userinfo is
    # not a ComfyUI address this helper understands.
    if parts.query or parts.fragment or parts.username or parts.password:
        return None
    return _origin(raw)


def normalized_public_base() -> str | None:
    """``COMFY_MCP_PUBLIC_BASE_URL`` without a trailing slash, or ``None``.

    ``None`` means unset or not a usable http(s) base (no userinfo, query, or
    fragment). Output rewriting then leaves every URL unchanged. A path prefix
    is kept: ``https://example.com/comfy/`` becomes ``https://example.com/comfy``.
    """
    raw = os.environ.get("COMFY_MCP_PUBLIC_BASE_URL", "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if parts.query or parts.fragment:
        return None
    if parts.path not in {"", "/"} and (
        ".." in parts.path.split("/") or "//" in parts.path
    ):
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    # urlsplit keeps an explicit default port in netloc (`:80`). Rebuild from
    # hostname and port so `https://example.com:443` and `https://example.com`
    # share one spelling, and so a path prefix joins cleanly.
    default_port = 443 if parts.scheme == "https" else 80
    if port == default_port:
        netloc = host
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, netloc, path, "", ""))


def _type_is_output(query: str) -> bool:
    values = [
        value
        for key, value in parse_qsl(query, keep_blank_values=True, separator="&")
        if key == "type"
    ]
    return values == ["output"]


def _publicize_comfy_output_url(url: str) -> str:
    """Replace the local ComfyUI origin on a generated ``/view`` URL.

    Unchanged unless the public base is set, ``url`` is HTTP(S), its origin is
    the local ComfyUI origin, the path is exactly ``/view``, and ``type`` is
    exactly ``output``. Scheme, host, and port become the public base. The
    path prefix of that base is joined in front of ``/view``. The query string
    and fragment are copied as they arrived.
    """
    public = normalized_public_base()
    local = _local_origin()
    if public is None or local is None or not isinstance(url, str):
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme not in {"http", "https"} or parts.path != "/view":
        return url
    if _origin(url) != local or not _type_is_output(parts.query):
        return url
    base = urlsplit(public)
    prefix = base.path.rstrip("/")
    view_path = f"{prefix}/view"
    return urlunsplit(
        (base.scheme, base.netloc, view_path, parts.query, parts.fragment)
    )


def publicize_client_result(value: Any) -> Any:
    """Copy ``value``, rewriting only local generated-output URLs.

    The input is not mutated. When nothing matches, the same object is
    returned, so a deployment with no public base is unchanged.
    """
    rewritten, changed = _walk(value)
    return rewritten if changed else value


def _walk(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        rewritten = _publicize_comfy_output_url(value)
        return rewritten, rewritten is not value and rewritten != value
    if isinstance(value, list):
        changed = False
        items: list[Any] = []
        for item in value:
            new, item_changed = _walk(item)
            items.append(new)
            changed = changed or item_changed
        return (items, True) if changed else (value, False)
    if isinstance(value, tuple):
        changed = False
        items = []
        for item in value:
            new, item_changed = _walk(item)
            items.append(new)
            changed = changed or item_changed
        return (tuple(items), True) if changed else (value, False)
    if isinstance(value, dict):
        changed = False
        mapping: dict[Any, Any] = {}
        for key, item in value.items():
            new, item_changed = _walk(item)
            mapping[key] = new
            changed = changed or item_changed
        return (mapping, True) if changed else (value, False)
    return value, False
