"""Versioned local portfolio and execution ledger; no exchange side effects."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta, timezone
from pathlib import Path

from .contracts import ValidationError, digest, hours, number, parse_time


LOCAL_TZ = timezone(timedelta(hours=8))


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("invalid_identifier", "%s must be a nonempty string" % field)
    return value


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9223372036854775807:
        raise ValidationError("invalid_revision", "%s must be a positive signed-64-bit integer" % field)
    return value


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError("invalid_json", str(exc)) from exc


class Ledger:
    """Single-machine SQLite ledger with atomic generation and event writes.

    Event IDs identify one portfolio/kind/customer for their entire history.
    Intent quantities are never counted as executed trades. For every cutoff,
    the highest eligible revision replaces its older revisions, even if it is
    cancelled or pending. Caller owns the database and its containing directory.
    """

    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                portfolio_id TEXT NOT NULL, event_id TEXT NOT NULL,
                revision INTEGER NOT NULL, available_time TEXT NOT NULL,
                available_epoch REAL NOT NULL, payload TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                PRIMARY KEY (portfolio_id, event_id, revision)
            );
            CREATE INDEX IF NOT EXISTS events_identity ON events(event_id, revision);
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, current_generation INTEGER NOT NULL,
                cancelled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS runs (
                task_id TEXT NOT NULL, generation INTEGER NOT NULL,
                input_hash TEXT NOT NULL, status TEXT NOT NULL,
                result_json TEXT, result_hash TEXT, selection_json TEXT,
                PRIMARY KEY (task_id, generation)
            );
        """)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._db.close()

    @contextmanager
    def _write(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        else:
            self._db.execute("COMMIT")

    def _event(self, event):
        if not isinstance(event, dict):
            raise ValidationError("invalid_event", "event must be a JSON object")
        # Copy through canonical JSON so later caller mutation cannot affect storage.
        item = json.loads(_json(event))
        for key in ("portfolio_id", "event_id", "source"):
            _text(item.get(key), key)
        _positive_int(item.get("revision"), "revision")
        if item.get("kind") not in {"trade", "intent", "declaration", "customer_event"}:
            raise ValidationError("invalid_event_kind", "unsupported event kind")
        if item.get("status") not in {"confirmed", "pending", "cancelled"}:
            raise ValidationError("invalid_event_status", "unsupported event status")
        available = parse_time(item.get("available_time"))
        start, end = parse_time(item.get("start")), parse_time(item.get("end"))
        if end <= start:
            raise ValidationError("invalid_interval", "event end must be after start")
        for boundary in (start, end):
            local = boundary.astimezone(LOCAL_TZ)
            if local.minute or local.second or local.microsecond:
                raise ValidationError("interval_alignment", "event intervals must align to Shanghai hours")
        if item["kind"] == "customer_event":
            _text(item.get("customer_id"), "customer_id")
            number(item.get("load_multiplier"), "load_multiplier", minimum=0)
        else:
            number(item.get("hourly_mwh"), "hourly_mwh", minimum=0)
        if item["kind"] == "trade":
            price = number(item.get("price_cny_per_mwh"), "price_cny_per_mwh")
            amount = number(item.get("hourly_mwh"), "hourly_mwh", minimum=0)
            number(price * amount, "hourly_trade_cost")
        return item, available

    def record_event(self, event):
        item, available = self._event(event)
        encoded, item_hash = _json(item), digest(item)
        with self._write():
            history = self._db.execute(
                "SELECT * FROM events WHERE event_id=?", (item["event_id"],)
            ).fetchall()
            for old in history:
                previous = json.loads(old["payload"])
                for key in ("portfolio_id", "kind", "customer_id"):
                    if previous.get(key) != item.get(key):
                        raise ValidationError("event_scope_changed", "revision changes %s" % key)
                if old["revision"] == item["revision"]:
                    if old["payload_hash"] == item_hash and old["payload"] == encoded:
                        return False
                    raise ValidationError("conflicting_revision", "same revision has different content")
                # Out-of-order arrival is supported; time-travelling versions are not.
                if ((old["revision"] < item["revision"] and old["available_epoch"] > available.timestamp())
                        or (old["revision"] > item["revision"] and old["available_epoch"] < available.timestamp())):
                    raise ValidationError("revision_time_order", "revision order conflicts with availability")
            self._db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                (item["portfolio_id"], item["event_id"], item["revision"],
                 item["available_time"], available.timestamp(), encoded, item_hash),
            )
        return True

    def state(self, portfolio_id, target_date, as_of):
        _text(portfolio_id, "portfolio_id")
        cutoff = parse_time(as_of)
        starts = [parse_time(value) for value in hours(target_date)]
        day_start, day_end = starts[0], starts[-1] + timedelta(hours=1)
        # Fetch in one read statement so a concurrent commit cannot mix revisions.
        rows = self._db.execute(
            "SELECT * FROM events WHERE portfolio_id=? AND available_epoch<=? "
            "ORDER BY event_id, revision",
            (portfolio_id, cutoff.timestamp()),
        ).fetchall()
        latest = {}
        for row in rows:
            latest[row["event_id"]] = row
        result = {
            "portfolio_id": portfolio_id, "target_date": target_date,
            "as_of": as_of, "holdings_mwh": [0.0] * 24,
            "holding_cost_cny": [0.0] * 24, "intents_mwh": [0.0] * 24,
            "declarations_mwh": [0.0] * 24, "customer_events": [], "event_refs": [],
        }
        for event_id in sorted(latest):
            row = latest[event_id]
            item = json.loads(row["payload"])
            start, end = parse_time(item["start"]), parse_time(item["end"])
            if start >= day_end or end <= day_start:
                continue
            result["event_refs"].append({
                "event_id": item["event_id"], "revision": item["revision"],
                "source": item["source"], "available_time": item["available_time"],
                "status": item["status"], "kind": item["kind"],
                "content_hash": row["payload_hash"],
            })
            if item["status"] == "cancelled":
                continue
            if item["kind"] == "customer_event":
                if item["status"] == "confirmed":
                    result["customer_events"].append(item)
                continue
            if item["kind"] != "intent" and item["status"] != "confirmed":
                continue
            field = {"trade": "holdings_mwh", "intent": "intents_mwh",
                     "declaration": "declarations_mwh"}[item["kind"]]
            for index, hour in enumerate(starts):
                if start <= hour < end:
                    amount = float(item["hourly_mwh"])
                    result[field][index] = number(result[field][index] + amount, field)
                    if item["kind"] == "trade":
                        result["holding_cost_cny"][index] = number(
                            result["holding_cost_cny"][index] + amount * float(item["price_cny_per_mwh"]),
                            "holding_cost_cny")
        result["state_id"] = digest(result)
        return result

    def start_run(self, task_id, input_hash):
        _text(task_id, "task_id")
        _text(input_hash, "input_hash")
        with self._write():
            task = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is not None and task["cancelled"]:
                raise ValidationError("task_cancelled", "cancelled task cannot restart")
            generation = 1 if task is None else task["current_generation"] + 1
            if task is not None:
                self._db.execute("UPDATE runs SET status='superseded' WHERE task_id=? "
                                 "AND generation=? AND status='running'",
                                 (task_id, task["current_generation"]))
                self._db.execute("UPDATE tasks SET current_generation=? WHERE task_id=?",
                                 (generation, task_id))
            else:
                self._db.execute("INSERT INTO tasks VALUES (?,?,0)", (task_id, generation))
            self._db.execute("INSERT INTO runs(task_id,generation,input_hash,status) VALUES (?,?,?,'running')",
                             (task_id, generation, input_hash))
        return generation

    def _active_run(self, task_id, generation):
        _text(task_id, "task_id")
        _positive_int(generation, "generation")
        task = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            raise ValidationError("unknown_task", "task has not been started")
        if task["cancelled"]:
            raise ValidationError("task_cancelled", "task is cancelled")
        if task["current_generation"] != generation:
            raise ValidationError("stale_generation", "worker or selection refers to an old generation")
        return self._db.execute("SELECT * FROM runs WHERE task_id=? AND generation=?",
                                (task_id, generation)).fetchone()

    def finish_run(self, task_id, generation, input_hash, result):
        _text(input_hash, "input_hash")
        if not isinstance(result, dict):
            raise ValidationError("invalid_result", "result must be a JSON object")
        encoded, result_hash = _json(result), digest(result)
        with self._write():
            run = self._active_run(task_id, generation)
            if run["input_hash"] != input_hash:
                raise ValidationError("input_hash_mismatch", "result does not match frozen inputs")
            if run["status"] == "completed":
                if run["result_json"] == encoded:
                    return False
                raise ValidationError("conflicting_result", "completed result cannot be overwritten")
            if run["status"] != "running":
                raise ValidationError("invalid_run_state", "only running tasks may complete")
            self._db.execute("UPDATE runs SET status='completed',result_json=?,result_hash=? "
                             "WHERE task_id=? AND generation=?",
                             (encoded, result_hash, task_id, generation))
        return True

    def select_plan(self, task_id, generation, plan_id, plan_hash):
        _text(plan_id, "plan_id")
        _text(plan_hash, "plan_hash")
        with self._write():
            run = self._active_run(task_id, generation)
            if run["status"] != "completed":
                raise ValidationError("incomplete_run", "selection requires a completed run")
            result = json.loads(run["result_json"])
            plans = result.get("plans", [])
            if not isinstance(plans, list):
                raise ValidationError("plan_mismatch", "completed result does not contain a plan list")
            matches = [plan for plan in plans if isinstance(plan, dict) and plan.get("plan_id") == plan_id]
            if len(matches) != 1 or matches[0].get("plan_hash") != plan_hash:
                raise ValidationError("plan_mismatch", "plan ID/hash not present in current completed result")
            selection = {"task_id": task_id, "generation": generation,
                         "input_hash": run["input_hash"], "result_hash": run["result_hash"],
                         "plan_id": plan_id, "plan_hash": plan_hash}
            previous = run["selection_json"]
            encoded = _json(selection)
            if previous is not None and previous != encoded:
                raise ValidationError("selection_conflict", "selection already recorded for this run")
            self._db.execute("UPDATE runs SET selection_json=? WHERE task_id=? AND generation=?",
                             (encoded, task_id, generation))
        return selection

    def get_run(self, task_id):
        _text(task_id, "task_id")
        row = self._db.execute(
            "SELECT r.*,t.cancelled FROM tasks t JOIN runs r ON r.task_id=t.task_id "
            "AND r.generation=t.current_generation WHERE t.task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise ValidationError("unknown_task", "task has not been started")
        return {"task_id": row["task_id"], "generation": row["generation"],
                "input_hash": row["input_hash"], "status": "cancelled" if row["cancelled"] else row["status"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "result_hash": row["result_hash"],
                "selection": json.loads(row["selection_json"]) if row["selection_json"] else None}

    def cancel_run(self, task_id):
        _text(task_id, "task_id")
        with self._write():
            task = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise ValidationError("unknown_task", "task has not been started")
            self._db.execute("UPDATE tasks SET cancelled=1 WHERE task_id=?", (task_id,))
            self._db.execute("UPDATE runs SET status='cancelled' WHERE task_id=? AND generation=?",
                             (task_id, task["current_generation"]))
