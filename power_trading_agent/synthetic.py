"""Deterministic invented data, with forecasts derived from earlier observations."""
import math
import random
from datetime import date, timedelta

from .contracts import hours


def demo_bundle():
    rng = random.Random(1100)
    start = date(2026, 1, 1)
    series = []
    for day in range(42):
        target = start + timedelta(days=day)
        l, da, rt = [], [], []
        for h in range(24):
            demand = 20 + 5 * math.sin((h - 7) * math.pi / 12) + 2 * math.cos(day / 3)
            demand += rng.uniform(-1.3, 1.3)
            if target.weekday() >= 5:
                demand *= 0.82
            if day == 20 and 10 <= h < 15:
                demand *= 0.4  # customer-a (60%) stops; actual synthetic event
            price = 310 + 55 * math.sin((h - 8) * math.pi / 12) + 18 * math.cos(day / 4)
            spread = 28 * math.sin((h + day) * math.pi / 8) + rng.uniform(-8, 8)
            if day in (25, 33) and 17 <= h < 21:
                spread += 150
            l.append(round(demand, 6))
            da.append(round(price, 6))
            rt.append(round(price + spread, 6))
        series.append({"target_date": target.isoformat(), "l": l, "da": da, "rt": rt,
                       "price_basis": "user_side", "energy_unit": "MWh", "price_unit": "CNY/MWh",
                       "available_time": (target + timedelta(days=1)).isoformat() + "T06:00:00+08:00"})
    records, days, provenance = [], [], []
    for i in range(14, 42):
        target = start + timedelta(days=i)
        prior = target - timedelta(days=1)
        origin = prior.isoformat() + "T12:00:00+08:00"
        published = prior.isoformat() + "T10:00:00+08:00"
        history = series[i - 8:i - 1]  # D-8 ... D-2; all released before origin
        group = "synthetic_spike" if i in (25, 33) else ("weekend" if target.weekday() >= 5 else "weekday")
        days.append({"target_date": target.isoformat(), "origin": origin, "group": group})
        provenance.append({"target_date": target.isoformat(), "model_version": "trailing-seven-available-days-v1",
                           "training_days": [a["target_date"] for a in history],
                           "latest_label_available_time": history[-1]["available_time"]})
        for h, target_time in enumerate(hours(target.isoformat())):
            mean_l = sum(a["l"][h] for a in history) / len(history)
            means = {"da_forecast": sum(a["da"][h] for a in history) / len(history),
                     "rt_forecast": sum(a["rt"][h] for a in history) / len(history)}
            cells = [("load_forecast", mean_l * 0.6, "customer-a"),
                     ("load_forecast", mean_l * 0.4, "customer-b")]
            cells += [(m, v, None) for m, v in means.items()]
            for metric, value, customer in cells:
                record = {"record_id": target_time + "/" + metric + "/" + str(customer),
                          "revision": 1, "source": "synthetic_trailing_mean", "metric": metric,
                          "target_time": target_time, "available_time": published,
                          "issue_time": published, "received_at": published, "value": round(value, 6),
                          "unit": "MWh" if metric == "load_forecast" else "CNY/MWh"}
                if customer:
                    record["customer_id"] = customer
                else:
                    record["price_basis"] = "user_side"
                records.append(record)
                if metric == "da_forecast" and h == 0:
                    late = dict(record, revision=2, value=value + 999,
                                available_time=target.isoformat() + "T10:00:00+08:00",
                                issue_time=target.isoformat() + "T10:00:00+08:00",
                                received_at=target.isoformat() + "T10:00:00+08:00")
                    records.append(late)
    event_base = {"portfolio_id": "synthetic-retailer", "revision": 1,
                  "available_time": "2026-01-14T09:00:00+08:00",
                  "start": "2026-01-15T00:00:00+08:00", "end": "2026-02-12T00:00:00+08:00",
                  "source": "invented-example"}
    events = [dict(event_base, event_id="contract-001", kind="trade", status="confirmed",
                   hourly_mwh=8, price_cny_per_mwh=300),
              dict(event_base, event_id="purchase-intent-001", kind="intent", status="pending", hourly_mwh=3),
              dict(event_base, event_id="customer-stop-001", kind="customer_event", status="confirmed",
                   customer_id="customer-a", load_multiplier=0,
                   available_time="2026-01-20T10:00:00+08:00",
                   start="2026-01-21T10:00:00+08:00", end="2026-01-21T15:00:00+08:00")]
    return {"schema_version": "1.1", "scope": "synthetic", "portfolio_id": "synthetic-retailer",
            "customers": ["customer-a", "customer-b"], "days": days, "records": records,
            "actuals": series[14:], "forecast_provenance": provenance, "events": events,
            "rule": {"rule_id": "synthetic-physical-forward-v1", "scope": "synthetic",
                     "price_basis": "user_side", "currency": "CNY", "deviation_fee_cny_per_mwh": 3,
                     "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                     "source": "Invented arithmetic example; not Guangdong market rules"},
            "strategy": {"k_min": 0.9, "k_max": 1.1, "adjustment": 0.1, "spread_threshold": 5},
            "risk_budget_cny": 2000,
            "notice": "All data, positions, rules and budget are invented for offline research."}
