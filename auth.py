"""Run this once to authenticate with your Strava account.

Usage:
    python auth.py
"""
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from config import TOKENS_FILE, get_config

REDIRECT_PORT = 8282
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPE = "read,activity:read_all,profile:read_all"


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            params = parse_qs(parsed.query)
            _CallbackHandler.code = params.get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication complete! You can close this window.</h1></body></html>"
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args, **kwargs):
        pass  # Suppress request logs


def authenticate():
    config = get_config()

    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={config.client_id}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&approval_prompt=force"
        f"&scope={SCOPE}"
    )

    print("Opening browser for Strava authorization...")
    webbrowser.open(auth_url)
    print(f"If the browser didn't open, visit:\n{auth_url}\n")

    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    print("Waiting for authorization callback...")

    while _CallbackHandler.code is None:
        server.handle_request()

    code = _CallbackHandler.code

    resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    resp.raise_for_status()
    data = resp.json()

    config.update_tokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=data["expires_at"],
    )

    athlete = data["athlete"]
    print(f"\nAuthenticated as {athlete['firstname']} {athlete['lastname']}")
    print(f"Tokens saved to {TOKENS_FILE}")
    print("\nYou can now run: python cli.py")


if __name__ == "__main__":
    authenticate()
