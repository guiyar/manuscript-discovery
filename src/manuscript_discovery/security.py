"""Response headers the app itself must produce. TLS, HSTS, compression and rate limiting belong to
the reverse proxy in front of it; the Content-Security-Policy cannot, because it carries hashes of
this app's own inline script and style, which only the app knows."""

from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser


class _InlineBlocks(HTMLParser):
    """The exact text of every inline <script> and <style> block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: dict[str, list[str]] = {"script": [], "style": []}
        self._open: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.blocks and not dict(attrs).get("src"):
            self._open, self._text = tag, []

    def handle_data(self, data):
        if self._open:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == self._open:
            self.blocks[tag].append("".join(self._text))
            self._open = None


def _sources(blocks: list[str]) -> str:
    return (
        " ".join(
            "'sha256-"
            + base64.b64encode(hashlib.sha256(b.encode("utf-8")).digest()).decode()
            + "'"
            for b in blocks
        )
        or "'none'"
    )


def content_security_policy(index_html: str) -> str:
    """Allow exactly the inline script and style this page contains, same-origin requests and images,
    and nothing else: no 'unsafe-inline', no 'unsafe-eval', no framing, no base or form tricks."""
    parser = _InlineBlocks()
    parser.feed(index_html)
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src {_sources(parser.blocks['script'])}",
            f"style-src {_sources(parser.blocks['style'])}",
            "img-src 'self'",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )


class SecurityHeaders:
    """Plain ASGI (not BaseHTTPMiddleware, which hides client disconnects from the endpoints)."""

    def __init__(self, app, csp: str) -> None:
        self.app = app
        self.headers = [
            (b"content-security-policy", csp.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"x-frame-options", b"DENY"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"cross-origin-resource-policy", b"same-origin"),
        ]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *self.headers]
            await send(message)

        await self.app(scope, receive, send_with_headers)
