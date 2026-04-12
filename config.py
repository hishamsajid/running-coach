import json
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
TOKENS_FILE = PROJECT_ROOT / ".tokens.json"

load_dotenv(PROJECT_ROOT / ".env")


class Config:
    def __init__(self):
        self.client_id = os.environ["STRAVA_CLIENT_ID"]
        self.client_secret = os.environ["STRAVA_CLIENT_SECRET"]
        self.anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
        self._load_tokens()

    def _load_tokens(self):
        if TOKENS_FILE.exists():
            data = json.loads(TOKENS_FILE.read_text())
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            self.token_expires_at = data["expires_at"]
        else:
            # Fall back to env vars (e.g. Railway — no local tokens file)
            self.access_token = os.environ.get("STRAVA_ACCESS_TOKEN")
            self.refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN")
            self.token_expires_at = int(os.environ.get("STRAVA_TOKEN_EXPIRES_AT", 0))

    def update_tokens(self, access_token: str, refresh_token: str, expires_at: int):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = expires_at
        TOKENS_FILE.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                },
                indent=2,
            )
        )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
