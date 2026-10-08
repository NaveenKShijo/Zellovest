"""Per-eventType identification for Okta LogEvents."""
from zellovest_shared.schemas.webhooks import OktaEvent, OktaSignal

def _user_target(event: OktaEvent) -> tuple[str|None, str|None]:
    targets = event.target or []
    t = targets[0] if targets else None
    return (t.id if t else None, t.alternateId if t else None)

def extract_okta_signal(event: OktaEvent) -> OktaSignal | None:
    """Return None for UNSUPPORTED so caller can skip + count, not 422."""
    et = event.eventType
    uid, login = _user_target(event)
    base = {"raw_event_type": et, "event_uuid": event.uuid, "occurred_at": event.published,
        "user_id": uid, "user_login": login}
    if et.startswith("user.lifecycle."):
        return OktaSignal(signal="USER_LIFECYCLE", **base)
    if et == "user.session.start":
        return OktaSignal(signal="USER_LOGIN", **base)  # last-login for M6 30/60/90d features
    if et.startswith("app.user_management."):
        # app id is in target where type == "AppInstance"; parse here
        targets = event.target or []
        app = next((t for t in targets if "App" in (t.type or "")), None)
        return OktaSignal(signal="APP_ASSIGNMENT", app_id=app.id if app else None, **base)
    if et.startswith("group.user_membership."):
        return OktaSignal(signal="GROUP_MEMBERSHIP", **base)
    return None
