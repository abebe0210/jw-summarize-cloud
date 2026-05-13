from __future__ import annotations

import secrets

from flask import Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from .config import Settings
from .exceptions import AuthError


def authorize_request(request: Request, settings: Settings) -> None:
    if settings.webhook_shared_secret:
        presented = request.headers.get("X-Webhook-Secret") or _bearer_token(request)
        if not presented or not secrets.compare_digest(
            presented, settings.webhook_shared_secret
        ):
            raise AuthError("Invalid shared secret.")
        return

    if settings.google_oidc_audience:
        token = _bearer_token(request)
        if not token:
            raise AuthError("Missing bearer token.")
        try:
            payload = id_token.verify_oauth2_token(
                token, GoogleAuthRequest(), settings.google_oidc_audience
            )
        except Exception as exc:  # pragma: no cover - google-auth raises varied errors
            raise AuthError(f"Invalid OIDC token: {exc}") from exc
        if payload.get("aud") != settings.google_oidc_audience:
            raise AuthError("OIDC audience mismatch.")


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if header.startswith(prefix):
        return header[len(prefix) :].strip() or None
    return None
