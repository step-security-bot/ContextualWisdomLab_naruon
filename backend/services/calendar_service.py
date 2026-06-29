import asyncio
import datetime
import unicodedata

from .exceptions import CalendarServiceError, UnsafeCalendarTodoError

MAX_CALENDAR_TODO_LENGTH = 500
UNSAFE_CALENDAR_TODO_SEQUENCES = ("<", ">", "`", "$(", "${")
GOOGLE_OAUTH_ENDPOINT_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_ALLOWED_KEYS = {
    "account",
    "client_id",
    "client_secret",
    "expiry",
    "quota_project_id",
    "rapt_token",
    "refresh_token",
    "scopes",
    "token",
    "token_uri",
    "universe_domain",
}
GOOGLE_OAUTH_REQUIRED_KEYS = {
    "client_id",
    "client_secret",
    "refresh_token",
    "token_uri",
}


def build(*args, **kwargs):
    from googleapiclient.discovery import build as google_calendar_build

    return google_calendar_build(*args, **kwargs)


def _google_credentials(validated_user_token: dict):
    from google.oauth2.credentials import Credentials

    return Credentials(**validated_user_token)


def validate_calendar_todo_text(todo_text: str) -> str:
    """Validate user-authored calendar text before external writeback."""
    normalized = todo_text.strip()
    if not normalized or len(normalized) > MAX_CALENDAR_TODO_LENGTH:
        raise UnsafeCalendarTodoError("Unsafe calendar todo text")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise UnsafeCalendarTodoError("Unsafe calendar todo text")
    if any(sequence in normalized for sequence in UNSAFE_CALENDAR_TODO_SEQUENCES):
        raise UnsafeCalendarTodoError("Unsafe calendar todo text")
    return normalized


def validate_google_user_token(user_token: dict) -> dict:
    """Allow only server-issued Google OAuth credential fields."""
    if not isinstance(user_token, dict):
        raise CalendarServiceError("Invalid calendar credentials")

    unexpected_keys = set(user_token) - GOOGLE_OAUTH_ALLOWED_KEYS
    if unexpected_keys:
        raise CalendarServiceError("Invalid calendar credentials")

    missing_required_keys = {
        key
        for key in GOOGLE_OAUTH_REQUIRED_KEYS
        if not isinstance(user_token.get(key), str) or not user_token[key].strip()
    }
    if missing_required_keys:
        raise CalendarServiceError("Invalid calendar credentials")

    token_uri = user_token.get("token_uri")
    if token_uri != GOOGLE_OAUTH_ENDPOINT_URL:
        raise CalendarServiceError("Invalid calendar credentials")

    access_token = user_token.get("token")
    if access_token is not None and (
        not isinstance(access_token, str) or not access_token.strip()
    ):
        raise CalendarServiceError("Invalid calendar credentials")

    return dict(user_token)


async def create_calendar_event(todo_text: str, user_token: dict) -> dict:
    """Creates a calendar event for a given TODO text."""
    try:
        safe_todo_text = validate_calendar_todo_text(todo_text)
        validated_user_token = validate_google_user_token(user_token)
        creds = _google_credentials(validated_user_token)
        service = build("calendar", "v3", credentials=creds)

        now = datetime.datetime.now(datetime.timezone.utc)
        event = {
            "summary": safe_todo_text,
            "start": {"dateTime": now.isoformat()},
            "end": {"dateTime": (now + datetime.timedelta(hours=1)).isoformat()},
        }
        request = service.events().insert(calendarId="primary", body=event)
        created_event = await asyncio.to_thread(request.execute)
        return created_event
    except UnsafeCalendarTodoError:
        raise
    except CalendarServiceError:
        raise
    except Exception as e:
        raise CalendarServiceError("Failed to create event") from e
