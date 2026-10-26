"""Formatting GitHub's UTC timestamps for display in IST."""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")  # GitHub gives UTC; show times to the user in IST


def to_ist(iso_text):
    """Convert a GitHub UTC timestamp (e.g. 2026-06-09T07:15:57Z) to IST."""
    return datetime.fromisoformat(iso_text.replace("Z", "+00:00")).astimezone(IST)


def format_ist(iso_text):
    """Show a GitHub UTC timestamp as a readable IST date and time."""
    if not iso_text:
        return "unknown"
    return to_ist(iso_text).strftime("%Y-%m-%d %H:%M IST")