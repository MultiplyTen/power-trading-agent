"""Host-neutral, allowlisted JSON tools; no shell or remote LLM execution."""
import os
import tempfile
from pathlib import Path

from .contracts import ValidationError
from .data import build_snapshot
from .events import parse_customer_message
from .portfolio import Ledger
from .runner import evaluate_day, validate_bundle


TOOL_CATALOG = [
    {"name": "validate_input", "description": "Validate an as-of 24-hour forecast snapshot / 校验事前快照",
     "required": ["bundle", "target_date", "origin"]},
    {"name": "portfolio_state", "description": "Compute confirmed holdings separately from intents / 查询组合状态",
     "required": ["portfolio_id", "target_date", "origin", "events"]},
    {"name": "evaluate_day", "description": "Evaluate a synthetic day without actual labels / 生成研究候选",
     "required": ["bundle", "target_date", "origin"]},
    {"name": "parse_customer_event", "description": "Parse an absolute-date stop event as pending / 提取待确认事件",
     "required": ["text", "portfolio_id", "customer_id", "known_at", "source", "event_id"]},
]


def dispatch(request):
    if not isinstance(request, dict) or not isinstance(request.get("arguments"), dict):
        raise ValidationError("INVALID_TOOL_REQUEST", "name and arguments object required")
    descriptors = {t["name"]: t for t in TOOL_CATALOG}
    name, args = request.get("name"), request["arguments"]
    if name not in descriptors:
        raise ValidationError("UNKNOWN_TOOL", "tool is not allowlisted")
    required = descriptors[name]["required"]
    if set(args) != set(required):
        raise ValidationError("TOOL_ARGUMENTS", "argument fields must match " + str(required))
    if name == "parse_customer_event":
        return parse_customer_message(**args)
    if name == "validate_input":
        return build_snapshot(args["bundle"], args["target_date"], args["origin"])
    with tempfile.TemporaryDirectory(prefix="pta-tools-", dir=os.environ.get("TMPDIR")) as temporary:
        with Ledger(Path(temporary) / "ledger.sqlite3") as ledger:
            events = args["events"] if name == "portfolio_state" else args["bundle"].get("events", [])
            portfolio = args["portfolio_id"] if name == "portfolio_state" else args["bundle"]["portfolio_id"]
            for event in events:
                if event.get("portfolio_id") != portfolio:
                    raise ValidationError("SCOPE_MISMATCH", "tool input mixes portfolios")
                ledger.record_event(event)
            if name == "portfolio_state":
                return ledger.state(portfolio, args["target_date"], args["origin"])
            bundle = args["bundle"]
            day = {"target_date": args["target_date"], "origin": args["origin"]}
            # Validate rule applicability to the requested day, not unrelated bundle days.
            validate_bundle(dict(bundle, days=[day]))
            return evaluate_day(bundle, day, ledger)
