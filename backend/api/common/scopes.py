from sqlalchemy import select

from api.auth import AuthContext
from db.models import ConnectorSignalEvent


def connector_scope_statement(auth_context: AuthContext):
    if auth_context.organization_id is None:
        return None
    return (
        select(ConnectorSignalEvent)
        .where(
            ConnectorSignalEvent.organization_id == auth_context.organization_id,
            ConnectorSignalEvent.workspace_id == auth_context.workspace_id,
        )
        .order_by(ConnectorSignalEvent.observed_at.desc())
        .limit(8)
    )
