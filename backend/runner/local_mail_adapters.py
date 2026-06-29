from dataclasses import dataclass
from typing import Any, Iterable

from db.models import TenantConfig
from services.email_client import EmailMessageParams, SmtpConfig, send_email
from services.imap_worker import ImapSyncWorker


@dataclass(frozen=True)
class LocalMailAccountConfig:
    account: str
    user_id: str
    organization_id: str | None = None
    smtp_server: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    imap_server: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None
    imap_password: str | None = None


class LocalMailAdapters:
    def __init__(
        self,
        accounts: Iterable[LocalMailAccountConfig],
        *,
        imap_worker_factory=None,
    ):
        self._accounts = {
            account.account.strip(): account
            for account in accounts
            if account.account.strip()
        }
        self._imap_worker_factory = imap_worker_factory or ImapSyncWorker

    async def send_smtp(self, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._account_for_payload(payload)
        if account is None:
            return self._error("account_not_configured")
        if (
            not account.smtp_server
            or not account.smtp_port
            or not account.smtp_username
            or not account.smtp_password
        ):
            return self._error("account_configuration_incomplete")

        try:
            message_params = EmailMessageParams(
                to_address=self._required_payload_text(payload, "to"),
                subject=self._required_payload_text(payload, "subject"),
                body=self._required_payload_text(payload, "body"),
                in_reply_to=self._optional_payload_text(payload, "in_reply_to"),
                references=self._optional_payload_text(payload, "references"),
            )
        except ValueError:
            return self._error("invalid_payload")

        try:
            send_result = await send_email(
                message_params=message_params,
                smtp_config=SmtpConfig(
                    smtp_server=account.smtp_server,
                    smtp_port=account.smtp_port,
                    smtp_username=account.smtp_username,
                    smtp_password=account.smtp_password,
                ),
            )
        except ValueError:
            return self._error("provider_destination_not_allowed")

        if send_result.get("status") == "sent" and not send_result.get("simulated"):
            return {
                "status": "success",
                "provider_write_executed": True,
                "provider_status": send_result["status"],
            }
        return self._error("provider_write_not_executed")

    async def fetch_imap(self, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._account_for_payload(payload)
        if account is None:
            return self._error("account_not_configured")
        if (
            not account.imap_server
            or not account.imap_port
            or not account.imap_username
            or not account.imap_password
        ):
            return self._error("account_configuration_incomplete")

        worker = self._imap_worker_factory()
        imported_count = await worker._sync_tenant(self._tenant_config(account))
        return {
            "status": "success",
            "messages_imported": int(imported_count or 0),
            "provider_write_executed": False,
        }

    def _account_for_payload(
        self, payload: dict[str, Any]
    ) -> LocalMailAccountConfig | None:
        account_name = payload.get("account")
        if not isinstance(account_name, str):
            return None
        return self._accounts.get(account_name.strip())

    def _tenant_config(self, account: LocalMailAccountConfig) -> TenantConfig:
        return TenantConfig(
            user_id=account.user_id,
            organization_id=account.organization_id,
            smtp_server=account.smtp_server,
            smtp_port=account.smtp_port,
            smtp_username=account.smtp_username,
            smtp_password=account.smtp_password,
            imap_server=account.imap_server,
            imap_port=account.imap_port,
            imap_username=account.imap_username,
            imap_password=account.imap_password,
        )

    def _required_payload_text(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("invalid payload")
        return value

    def _optional_payload_text(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("invalid payload")
        return value

    def _error(self, error_code: str) -> dict[str, Any]:
        return {
            "status": "error",
            "error": error_code,
            "error_code": error_code,
            "provider_write_executed": False,
        }
