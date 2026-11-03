"""Conservative Chinese event intake; ambiguous language remains unconfirmed."""
import re

from .contracts import ValidationError, digest, parse_time


def parse_customer_message(text, portfolio_id, customer_id, known_at, source, event_id):
    """Accept only the documented absolute-date template, returning a pending event.

    This is a bounded parser, not a general language model. It deliberately refuses
    relative dates, negation, revocations and partial matches.
    """
    for name, value in (("text", text), ("portfolio_id", portfolio_id), ("customer_id", customer_id),
                        ("source", source), ("event_id", event_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("MISSING_FIELD", name + " is required")
    parse_time(known_at)
    expression = r"\s*(\d{4}-\d{2}-\d{2} \d{2}:00)\s*(?:至|到)\s*(\d{4}-\d{2}-\d{2} \d{2}:00)\s*(?:停产|停工)\s*[。.]?\s*"
    match = re.fullmatch(expression, text)
    if match is None:
        return {"status": "needs_clarification", "message": "请使用明确起止时间，例如：2026-01-21 10:00 至 2026-01-21 15:00 停产",
                "reason": "relative dates, negations, cancellations and unsupported wording require clarification",
                "source_text_hash": digest(text), "event": None}
    start, end = [v.replace(" ", "T") + ":00+08:00" for v in match.groups()]
    if parse_time(end) <= parse_time(start):
        raise ValidationError("INVALID_INTERVAL", "end must follow start")
    event = {"portfolio_id": portfolio_id, "customer_id": customer_id, "event_id": event_id,
             "revision": 1, "kind": "customer_event", "status": "pending", "source": source,
             "available_time": known_at, "start": start, "end": end, "load_multiplier": 0,
             "source_text": text}
    return {"status": "pending_confirmation", "event": event,
            "message": "核对客户与时段后，以新修订记录确认；pending 不改变预测。"}
