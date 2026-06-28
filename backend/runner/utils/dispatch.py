from typing import Literal, TypedDict

from typing_extensions import NotRequired


class ErrorDispatchPayload(TypedDict):
    status: Literal["error"]
    error: str
    error_code: str
    provider_write_executed: Literal[False]
    provider_status: NotRequired[int | str]
    retry_item_uid: NotRequired[str]


def dispatch_error(error_code: str) -> ErrorDispatchPayload:
    return {
        "status": "error",
        "error": error_code,
        "error_code": error_code,
        "provider_write_executed": False,
    }


__all__ = ["ErrorDispatchPayload", "dispatch_error"]
