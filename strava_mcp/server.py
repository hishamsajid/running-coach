"""Strava MCP server — exposes Strava API endpoints as tools for the coach agent.

Run as a subprocess via stdio transport; do not add any print() calls here
as stdout is reserved for the MCP protocol.
"""
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from strava_mcp.strava_client import StravaClient

# Send logs to stderr only — stdout is the MCP protocol channel
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

mcp = FastMCP("strava-coach")
_client: StravaClient | None = None


def get_client() -> StravaClient:
    global _client
    if _client is None:
        _client = StravaClient()
    return _client


@mcp.tool()
def get_current_timestamp() -> str:
    """Return the current Unix timestamp (seconds since epoch) and the current UTC date.
    Use this before computing date ranges for list_activities."""
    now = int(time.time())
    return json.dumps({"unix_timestamp": now})


@mcp.tool()
def get_athlete() -> str:
    """Get the authenticated athlete's profile: name, location, weight, FTP, sex,
    measurement preference (metric/imperial), and follower counts."""
    return json.dumps(get_client().get_athlete())


@mcp.tool()
def get_athlete_stats() -> str:
    """Get the athlete's overall training statistics including:
    - recent_run_totals: distance, moving_time, elevation_gain for the last 4 weeks
    - ytd_run_totals: year-to-date totals
    - all_run_totals: lifetime totals
    All distances are in metres, times in seconds."""
    athlete = get_client().get_athlete()
    return json.dumps(get_client().get_athlete_stats(athlete["id"]))


@mcp.tool()
def get_athlete_zones() -> str:
    """Get the athlete's configured heart rate and power zones.
    Heart rate zones are defined by min/max bpm boundaries.
    Useful for zone-based training analysis."""
    return json.dumps(get_client().get_athlete_zones())


@mcp.tool()
def list_activities(
    per_page: int = 30,
    page: int = 1,
    after_timestamp: Optional[int] = None,
    before_timestamp: Optional[int] = None,
) -> str:
    """List the athlete's activities (summary level).

    Each activity includes: id, name, type, sport_type, start_date, distance (metres),
    moving_time (seconds), elapsed_time (seconds), total_elevation_gain (metres),
    average_speed (m/s), max_speed (m/s), average_heartrate, max_heartrate,
    average_cadence, suffer_score, kudos_count, pr_count.

    Use after_timestamp / before_timestamp (Unix epoch integers) to filter by date range.
    Use page to paginate results. per_page max is 200.

    To get runs from the last 30 days, compute after_timestamp as (current Unix time - 2592000).
    Call the get_current_timestamp tool to get the current Unix time.
    """
    return json.dumps(
        get_client().list_activities(
            before=before_timestamp,
            after=after_timestamp,
            per_page=per_page,
            page=page,
        )
    )


@mcp.tool()
def get_activity(activity_id: int) -> str:
    """Get full details of a specific activity by its Strava ID.

    Returns everything in list_activities PLUS: description, calories, perceived_exertion,
    splits_metric (per-km splits with pace and HR), splits_imperial (per-mile splits),
    best_efforts (PRs at standard distances), gear info, segment efforts, laps count.

    Use this after list_activities to drill into a specific run for detailed analysis."""
    return json.dumps(get_client().get_activity(activity_id))


@mcp.tool()
def get_activity_laps(activity_id: int) -> str:
    """Get lap-by-lap data for an activity.

    Each lap includes: lap_index, distance, moving_time, elapsed_time, average_speed,
    max_speed, average_heartrate, max_heartrate, average_cadence, total_elevation_gain.

    Essential for analysing interval workouts, tempo runs, and paced efforts.
    Distances in metres, times in seconds, speed in m/s."""
    return json.dumps(get_client().get_activity_laps(activity_id))


@mcp.tool()
def get_activity_zones(activity_id: int) -> str:
    """Get heart rate and pace zone distribution for a specific activity.

    Shows what percentage of the run was spent in each HR/pace zone.
    Useful for determining aerobic vs anaerobic training load.

    Note: requires Strava Premium and a heart rate monitor. Returns an error dict
    if zone data is unavailable."""
    try:
        return json.dumps(get_client().get_activity_zones(activity_id))
    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "note": "Zone data requires Strava Premium and heart rate data for this activity.",
            }
        )


if __name__ == "__main__":
    mcp.run()
