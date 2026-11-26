"""Response headers the app itself must produce. TLS, HSTS, compression and rate limiting belong to
the reverse proxy in front of it; the Content-Security-Policy cannot, because it carries hashes of
this app's own inline script (and any inline style), which only the app knows."""

from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser


def _same_origin(href: str) -> bool:
    return not href.strip().lower().startswith(("http:", "https:", "//"))


class _InlineBlocks(HTMLParser):
    """The exact text of every inline <script> and <style> block, and whether the page links a
    same-origin stylesheet."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: dict[str, list[str]] = {"script": [], "style": []}
        self.stylesheet = False
        self._open: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.blocks and not a.get("src"):
            self._open, self._text = tag, []
        elif (
            tag == "link"
            and "stylesheet" in (a.get("rel") or "").lower().split()
            and _same_origin(a.get("href") or "")
        ):
            self.stylesheet = True

    def handle_data(self, data):
        if self._open:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == self._open:
            self.blocks[tag].append("".join(self._text))
            self._open = None


def _sources(blocks: list[str], *, own_files: bool = False) -> str:
    hashes = [
        "'sha256-"
        + base64.b64encode(hashlib.sha256(b.encode("utf-8")).digest()).decode()
        + "'"
        for b in blocks
    ]
    return " ".join([*(["'self'"] if own_files else []), *hashes]) or "'none'"


def content_security_policy(index_html: str) -> str:
    """Allow exactly the inline script this page contains, its own stylesheet (and any inline style
    it has), same-origin requests and images, and nothing else: no 'unsafe-inline', no
    'unsafe-eval', no framing, no base or form tricks. A stylesheet is allowed only when the page
    links one from its own origin."""
    parser = _InlineBlocks()
    parser.feed(index_html)
    return "; ".join(
        [
            "default-src 'none'",
            f"script-src {_sources(parser.blocks['script'])}",
            f"style-src {_sources(parser.blocks['style'], own_files=parser.stylesheet)}",
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
