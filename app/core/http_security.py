"""Bound request bodies and abuse at the ASGI boundary, before multipart parsing.

Limits are per process: keep one worker, or add a shared limiter at the edge.
Forwarded headers are handled by Uvicorn's trusted-proxy configuration only.
"""
import time
from collections import OrderedDict

from starlette.responses import JSONResponse
from app.core.security import decode_token, TokenDecodeError


class BodyTooLarge(Exception):
    pass


class SecurityMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.buckets = OrderedDict()

    def allowed(self, key, limit, window=60):
        now = time.monotonic()
        count, start = self.buckets.pop(key, (0, now))
        if now - start >= window:
            count, start = 0, now
        self.buckets[key] = (count + 1, start)
        while len(self.buckets) > 10000:
            self.buckets.popitem(last=False)
        return count < limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        path = scope["path"].rstrip("/")
        prefix = self.settings.api_v1_prefix
        method = scope["method"]
        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = message.setdefault("headers", [])
                existing = {name.lower() for name, _ in response_headers}
                for name, value in (
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"cache-control", b"no-store"),
                ):
                    if name not in existing:
                        response_headers.append((name, value))
                if self.settings.app_env.lower() in {"production", "prod"} and b"strict-transport-security" not in existing:
                    response_headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
            await send(message)

        async def reject(code, text, status, retry_after=60):
            response = JSONResponse({"success": False, "error": {"code": code, "message": text}}, status_code=status,
                                    headers={"Retry-After": str(retry_after)} if status == 429 else None)
            await response(scope, receive, secure_send)

        if method not in {"GET", "HEAD", "OPTIONS"}:
            client = (scope.get("client") or ("unknown",))[0]
            if not self.allowed(("writes", client), 120):
                return await reject("RATE_LIMITED", "Too many requests. Please wait a minute.", 429)
            if path.startswith(prefix + "/auth") or path.startswith(prefix + "/account"):
                if not self.allowed(("auth", client), 30):
                    return await reject("RATE_LIMITED", "Too many account requests. Please wait a minute.", 429)
            if path in {prefix + "/auth/register", prefix + "/account/forgot-password"}:
                if not self.allowed(("account_creation", client), 10, window=600):
                    return await reject("RATE_LIMITED", "Too many account requests. Please try again later.", 429, retry_after=600)
            if path == prefix + "/site-content/contact":
                if not self.allowed(("contact", client), 5, window=600):
                    return await reject("RATE_LIMITED", "Too many contact requests. Please try again later.", 429, retry_after=600)
            expensive = path.endswith(("/query", "/retry", "/profile", "/execute")) or path == prefix + "/datasets"
            if expensive:
                identity = client
                token = headers.get(b"authorization", b"").decode("latin1")
                if token.startswith("Bearer "):
                    try:
                        identity = str(decode_token(token[7:], "access")["sub"])
                    except (TokenDecodeError, KeyError):
                        pass
                if not self.allowed(("analysis", identity), 10):
                    return await reject("RATE_LIMITED", "Too many uploads or analyses. Please wait a minute.", 429)

        if method == "POST" and path == prefix + "/datasets":
            maximum = self.settings.max_upload_size_mb * 1024 * 1024 + 1024 * 1024
        elif method == "POST" and path == prefix + "/admin/site-content/images":
            maximum = 6 * 1024 * 1024
        elif method == "POST" and path == prefix + "/admin/site-content/videos":
            maximum = 101 * 1024 * 1024
        elif path.startswith(prefix + "/admin/blogs") and method in {"POST", "PUT"}:
            maximum = 1024 * 1024
        else:
            maximum = 64 * 1024
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0 or length > maximum:
                return await reject("REQUEST_TOO_LARGE", "Request exceeds the allowed size.", 413)
        except ValueError:
            return await reject("INVALID_REQUEST", "Invalid content length.", 400)
        size = 0
        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > maximum:
                raise BodyTooLarge()
            return message
        try:
            await self.app(scope, bounded_receive, secure_send)
        except BodyTooLarge:
            await reject("REQUEST_TOO_LARGE", "Request exceeds the allowed size.", 413)
