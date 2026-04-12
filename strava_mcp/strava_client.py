import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from config import get_config


class StravaClient:
    BASE_URL = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"

    def __init__(self):
        self._config = get_config()

    def _refresh_if_needed(self):
        # Refresh if token expires within 5 minutes
        if time.time() > self._config.token_expires_at - 300:
            self._refresh()

    def _refresh(self):
        resp = httpx.post(
            self.TOKEN_URL,
            data={
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._config.refresh_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._config.update_tokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
        )

    def _get(self, path: str, **params) -> dict | list:
        self._refresh_if_needed()
        resp = httpx.get(
            f"{self.BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._config.access_token}"},
            params={k: v for k, v in params.items() if v is not None},
        )
        resp.raise_for_status()
        return resp.json()

    def get_athlete(self) -> dict:
        return self._get("/athlete")

    def get_athlete_stats(self, athlete_id: int) -> dict:
        return self._get(f"/athletes/{athlete_id}/stats")

    def get_athlete_zones(self) -> dict:
        return self._get("/athlete/zones")

    def list_activities(
        self,
        before: int | None = None,
        after: int | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> list:
        return self._get(
            "/athlete/activities",
            before=before,
            after=after,
            per_page=per_page,
            page=page,
        )

    def get_activity(self, activity_id: int) -> dict:
        return self._get(f"/activities/{activity_id}")

    def get_activity_laps(self, activity_id: int) -> list:
        return self._get(f"/activities/{activity_id}/laps")

    def get_activity_zones(self, activity_id: int) -> dict:
        return self._get(f"/activities/{activity_id}/zones")
