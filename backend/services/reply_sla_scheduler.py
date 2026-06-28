import asyncio
import logging

from sqlalchemy import or_, select

from db.models import TenantConfig
from db.session import AsyncSessionLocal
from services.reply_sla_escalation_service import create_reply_sla_escalation_tasks

logger = logging.getLogger(__name__)
DEFAULT_REPLY_SLA_INTERVAL_SECONDS = 15 * 60
DEFAULT_REPLY_SLA_OVERDUE_HOURS = 48
DEFAULT_REPLY_SLA_LIMIT = 10


class ReplySlaScheduler:
    def __init__(
        self,
        *,
        interval_seconds: int = DEFAULT_REPLY_SLA_INTERVAL_SECONDS,
        overdue_hours: int = DEFAULT_REPLY_SLA_OVERDUE_HOURS,
        limit: int = DEFAULT_REPLY_SLA_LIMIT,
    ):
        self.interval_seconds = interval_seconds
        self.overdue_hours = overdue_hours
        self.limit = limit
        self._task = None
        self._is_running = False

    async def start(self):
        if self._is_running:
            logger.warning("ReplySlaScheduler is already running.")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ReplySlaScheduler started.")

    async def stop(self):
        if not self._is_running:
            return

        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug(
                    "ReplySlaScheduler cancellation acknowledged during shutdown."
                )
        logger.info("ReplySlaScheduler stopped.")

    async def _run_loop(self):
        while self._is_running:
            try:
                await self._sync()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Error in ReplySlaScheduler loop.", exc_info=True)

            if self._is_running:
                try:
                    await asyncio.sleep(self.interval_seconds)
                except asyncio.CancelledError:
                    break

    async def _sync(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TenantConfig).where(
                    or_(
                        TenantConfig.smtp_username.isnot(None),
                        TenantConfig.imap_username.isnot(None),
                    )
                )
            )
            configs = result.scalars().all()

            tasks = []
            for config in configs:
                tasks.append(
                    create_reply_sla_escalation_tasks(
                        session,
                        user_id=config.user_id,
                        organization_id=config.organization_id,
                        overdue_hours=self.overdue_hours,
                        limit=self.limit,
                    )
                )

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for config, result in zip(configs, results):
                    if isinstance(result, Exception):
                        logger.error(
                            "Overdue reply follow-up failed for configured owner %s.",
                            config.user_id,
                            exc_info=result,
                        )
