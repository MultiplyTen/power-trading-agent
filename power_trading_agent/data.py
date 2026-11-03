"""As-of snapshot selection. Scoring labels are a separate access path."""
from .contracts import ValidationError, SHANGHAI, curve, digest, hours, number, parse_time

UNITS = {"load_forecast": "MWh", "da_forecast": "CNY/MWh", "rt_forecast": "CNY/MWh"}


def build_snapshot(bundle, target_date, origin):
    cutoff = parse_time(origin)
    delivery = hours(target_date)
    if cutoff >= parse_time(delivery[0]):
        raise ValidationError("INVALID_ORIGIN", "day-ahead origin must precede target day")
    portfolio = bundle.get("portfolio_id")
    if not isinstance(portfolio, str) or not portfolio:
        raise ValidationError("MISSING_PORTFOLIO", "portfolio_id is required")
    customers = bundle.get("customers", [portfolio])
    if (not isinstance(customers, list) or not customers or
            any(not isinstance(c, str) or not c for c in customers) or
            len(set(customers)) != len(customers)):
        raise ValidationError("INVALID_CUSTOMERS", "customers must be unique identifiers")
    records = bundle.get("records")
    if not isinstance(records, list):
        raise ValidationError("MISSING_RECORDS", "records must be a list")
    seen = {}
    identities = {}
    version_times = {}
    selected = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValidationError("INVALID_RECORD", "record must be an object")
        metric = record.get("metric")
        if metric not in UNITS:
            # Actuals and unknown features cannot silently enter a decision snapshot.
            raise ValidationError("UNKNOWN_METRIC", "forecast records contain an unsupported metric")
        try:
            available = parse_time(record["available_time"])
            issued = parse_time(record["issue_time"])
            received = parse_time(record["received_at"])
            target = parse_time(record["target_time"]).astimezone(SHANGHAI).isoformat()
            record_id = record["record_id"]
            revision = record["revision"]
            source = record["source"]
        except KeyError as exc:
            raise ValidationError("MISSING_FIELD", str(exc)) from exc
        if available < max(issued, received):
            raise ValidationError("INVALID_AVAILABILITY", "available_time precedes issuance or receipt")
        if (not isinstance(record_id, str) or not record_id or
                not isinstance(source, str) or not source or
                isinstance(revision, bool) or not isinstance(revision, int) or revision < 1):
            raise ValidationError("INVALID_VERSION", "record identity/source/revision is invalid")
        if record.get("portfolio_id", portfolio) != portfolio:
            raise ValidationError("SCOPE_MISMATCH", "record belongs to another portfolio")
        customer = record.get("customer_id", portfolio) if metric == "load_forecast" else portfolio
        if metric == "load_forecast" and customer not in customers:
            raise ValidationError("SCOPE_MISMATCH", "unknown customer in load forecast")
        identity = (source, record_id)
        scope = (metric, target, customer)
        if identity in identities and identities[identity] != scope:
            raise ValidationError("REVISION_SCOPE", "revision changes metric, hour or customer")
        identities[identity] = scope
        key = (source, record_id, revision)
        record_hash = digest(record)
        if key in seen and seen[key] != record_hash:
            raise ValidationError("CONFLICTING_REVISION", "same revision has conflicting content")
        seen[key] = record_hash
        version_times.setdefault(identity, {})[revision] = available
        # Never substitute a post-cutoff revision for a historical observation.
        if available > cutoff or target not in delivery:
            continue
        if record.get("unit") != UNITS[metric]:
            raise ValidationError("UNIT_MISMATCH", "unexpected unit for " + metric)
        if metric != "load_forecast" and record.get("price_basis") != "user_side":
            raise ValidationError("PRICE_BASIS", "user-side prices are required")
        number(record.get("value"), "value", 0 if metric == "load_forecast" else None)
        previous = selected.get(scope)
        if previous:
            if (previous["source"], previous["record_id"]) != identity:
                raise ValidationError("SOURCE_CONFLICT", "two source identities supply one cell")
            prev_available = parse_time(previous["available_time"])
            if (revision > previous["revision"] and available < prev_available or
                    revision < previous["revision"] and available > prev_available):
                raise ValidationError("VERSION_ORDER", "revision and availability ordering conflict")
            if revision <= previous["revision"]:
                continue
        selected[scope] = record
    for history in version_times.values():
        times = [history[r] for r in sorted(history)]
        if any(b < a for a, b in zip(times, times[1:])):
            raise ValidationError("VERSION_ORDER", "revision and availability ordering conflict")
    required = [(m, t, c) for t in delivery for m in UNITS
                for c in (customers if m == "load_forecast" else [portfolio])]
    missing = [list(k) for k in required if k not in selected]
    if missing:
        raise ValidationError("MISSING_DATA", "missing forecast cells: " + str(missing[:3]))
    per_customer = {c: [float(selected[("load_forecast", t, c)]["value"]) for t in delivery]
                    for c in customers}
    refs = [dict(selected[k], source_hash=digest(selected[k])) for k in required]
    result = {
        "portfolio_id": portfolio, "target_date": target_date, "origin": origin,
        "price_basis": "user_side", "unit_energy": "MWh", "unit_price": "CNY/MWh",
        "hours": delivery, "customer_forecasts": per_customer,
        "f": [number(sum(per_customer[c][h] for c in customers), "portfolio_load", 0) for h in range(24)],
        "da": [float(selected[("da_forecast", t, portfolio)]["value"]) for t in delivery],
        "rt": [float(selected[("rt_forecast", t, portfolio)]["value"]) for t in delivery],
        "record_refs": refs,
    }
    result["input_snapshot_id"] = digest(result)
    return result


def actual_curves(bundle, target_date):
    """Read labels after decisions are frozen; never called by build_snapshot."""
    matches = [a for a in bundle.get("actuals", []) if a.get("target_date") == target_date]
    if len(matches) != 1:
        raise ValidationError("MISSING_ACTUALS", "exactly one actual record per replay day required")
    actual = matches[0]
    if actual.get("price_basis") != "user_side":
        raise ValidationError("PRICE_BASIS", "actual price basis must match forecasts")
    if actual.get("energy_unit", "MWh") != "MWh" or actual.get("price_unit", "CNY/MWh") != "CNY/MWh":
        raise ValidationError("UNIT_MISMATCH", "actual units do not match")
    result = {"l": curve(actual.get("l"), "actual_load", True),
              "da": curve(actual.get("da"), "actual_da"),
              "rt": curve(actual.get("rt"), "actual_rt")}
    result["actual_snapshot_id"] = digest(actual)
    return result


def apply_customer_events(snapshot, state):
    """Only confirmed, as-of events; two overlapping events need explicit resolution."""
    values = {c: list(f) for c, f in snapshot["customer_forecasts"].items()}
    touched = set()
    for event in state["customer_events"]:
        customer = event["customer_id"]
        if customer not in values:
            raise ValidationError("SCOPE_MISMATCH", "event customer not in forecast roster")
        for h, t in enumerate(snapshot["hours"]):
            if parse_time(event["start"]) <= parse_time(t) < parse_time(event["end"]):
                if (customer, h) in touched:
                    raise ValidationError("EVENT_CONFLICT", "overlapping customer events require resolution")
                touched.add((customer, h))
                values[customer][h] = number(values[customer][h] * number(event["load_multiplier"], "load_multiplier", 0), "event_adjusted_load", 0)
    return [number(sum(v[h] for v in values.values()), "portfolio_load", 0) for h in range(24)]
