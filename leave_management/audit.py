import json

from .db import execute, utcnow


def audit(user_id, action, entity=None, entity_id=None, details=None):
    payload = json.dumps(details, default=str) if isinstance(details, (dict, list)) else (details or "")
    execute(
        "INSERT INTO audit_logs (user_id, action, entity, entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, entity, entity_id, payload, utcnow()),
    )
