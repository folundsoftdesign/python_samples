from datetime import UTC, datetime


def current_utc_timestamp():
    return datetime.now(UTC)
