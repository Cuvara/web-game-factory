"""Risk and reward: what the oracle's safe and greedy policies earned, held to the bars of
core/reference/risk-reward.yaml.

The bot's `risk` record (bot.spec.ts) lists every attempt: the unit, the policy, whether the
unit was entered and the policy accepted, how it ended (won, lost, left, timeout), and the
probe's metrics at its start, at its end and at their highest. Per unit:

    reward    the first metric of the probe's own `measures().reward`, else of the rules'
              `reward.metrics`, that every counted attempt of the unit reports at its end
              (a `lower` metric - time - is negated, so more is always better)
    failure   an attempt failed when it ended `lost` or a failure metric (the probe's
              `measures().failure`, else the rules') rose during it
    measured  each policy counted >= `bars.min_attempts` attempts with a reward reading
    pays      greedy's mean reward >= safe's + min_absolute_gain, and >= safe's x
              (1 + min_relative_gain)
    risky     greedy's failure rate >= safe's + min_failure_rate_gain

`judge(record, rules)` returns the report's `risk` block and two checks' raw results; the
step decides their statuses by the tier. Nothing here passes what it did not measure.
"""

__all__ = ["judge"]


def _names(value):
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _counted(attempt):
    return (isinstance(attempt, dict) and attempt.get("entered")
            and attempt.get("policy_set") is True and isinstance(attempt.get("metrics_end"), dict))


def _failed(attempt, failure_metrics):
    if attempt.get("outcome") == "lost":
        return True
    start = attempt.get("metrics_start") or {}
    high = attempt.get("metrics_max") or {}
    for name in failure_metrics:
        if isinstance(high.get(name), (int, float)) and isinstance(start.get(name), (int, float)) \
                and high[name] > start[name]:
            return True
    return False


def _summary(attempts, metric, lower, failure_metrics):
    values = [a["metrics_end"][metric] for a in attempts
              if isinstance(a["metrics_end"].get(metric), (int, float))]
    values = [-v for v in values] if lower else values
    failures = sum(1 for a in attempts if _failed(a, failure_metrics))
    return {"attempts": len(attempts), "rewards": values,
            "mean_reward": round(sum(values) / len(values), 4) if values else None,
            "failures": failures,
            "failure_rate": round(failures / len(attempts), 4) if attempts else None,
            "outcomes": [a.get("outcome") for a in attempts]}


def judge(record, rules):
    """(risk block, {measured: (ok, why), reward: (ok | None, why)})."""
    bars = rules["bars"]
    if not isinstance(record, dict):
        return ({"applies": False, "measured": False,
                 "reason": "the playability records hold no risk test (a build played before "
                           "the bot ran one, or `with: risk` was not asked)", "units": []},
                {"measured": (False, "no risk record"), "reward": (None, "no risk record")})
    if not record.get("applies"):
        why = record.get("reason") or "the risk test did not run"
        return ({"applies": False, "measured": False, "reason": why, "units": []},
                {"measured": (False, why), "reward": (None, why)})
    if not record.get("declared"):
        why = record.get("reason") or "the probe declares no play.policy"
        return ({"applies": True, "measured": False, "reason": why, "units": []},
                {"measured": (False, why), "reward": (None, why)})
    offered = _names(record.get("offered"))
    if offered and not {"safe", "greedy"} <= set(offered):
        why = f"the probe's play.policy offers {', '.join(offered)}, not both safe and greedy"
        return ({"applies": True, "measured": False, "reason": why, "units": []},
                {"measured": (False, why), "reward": (None, why)})
    measures = record.get("measures") if isinstance(record.get("measures"), dict) else {}
    reward_order = _names(measures.get("reward")) or _names(
        (rules.get("reward") or {}).get("metrics"))
    lower = set(_names((rules.get("reward") or {}).get("lower"))) | set(
        _names(measures.get("lower")))
    reward_order += [m for m in sorted(lower) if m not in reward_order]
    failure_metrics = _names(measures.get("failure")) or _names(
        (rules.get("failure") or {}).get("metrics"))
    attempts = [a for a in record.get("attempts") or [] if isinstance(a, dict)]
    units, order = {}, []
    for attempt in attempts:
        uid = attempt.get("unit")
        if uid not in units:
            units[uid] = []
            order.append(uid)
        units[uid].append(attempt)
    results, metric_used = [], None
    for uid in order:
        counted = {p: [a for a in units[uid] if a.get("policy") == p and _counted(a)]
                   for p in ("safe", "greedy")}
        both = counted["safe"] + counted["greedy"]
        metric = next((m for m in reward_order if both and all(
            isinstance(a["metrics_end"].get(m), (int, float)) for a in both)), None)
        entry = {"unit_id": uid or None, "measured": False, "reason": None,
                 "reward_gain": None, "relative_gain": None, "failure_rate_gain": None,
                 "pays": None, "risky": None}
        short = [p for p in ("safe", "greedy") if len(counted[p]) < bars["min_attempts"]]
        if short:
            reasons = sorted({a.get("reason") for a in units[uid] if a.get("reason")})
            entry["reason"] = (f"{' and '.join(short)} counted fewer than "
                               f"{bars['min_attempts']} attempts"
                               + (f" ({'; '.join(reasons[:3])})" if reasons else ""))
        elif metric is None:
            entry["reason"] = ("no reward metric is reported by every attempt (looked for "
                               f"{', '.join(reward_order) or 'none'})")
        else:
            metric_used = metric_used or metric
            safe = _summary(counted["safe"], metric, metric in lower, failure_metrics)
            greedy = _summary(counted["greedy"], metric, metric in lower, failure_metrics)
            entry.update(safe=safe, greedy=greedy, measured=True)
            gain = greedy["mean_reward"] - safe["mean_reward"]
            base = abs(safe["mean_reward"])
            relative = (gain / base) if base > 0 else (float("inf") if gain > 0 else 0.0)
            entry["reward_gain"] = round(gain, 4)
            entry["relative_gain"] = round(relative, 4) if relative != float("inf") else None
            entry["failure_rate_gain"] = round(greedy["failure_rate"] - safe["failure_rate"], 4)
            entry["pays"] = (gain >= bars["min_absolute_gain"]
                             and relative >= bars["min_relative_gain"])
            entry["risky"] = entry["failure_rate_gain"] >= bars["min_failure_rate_gain"]
            entry["safe"]["metric"] = entry["greedy"]["metric"] = metric
        results.append(entry)
    block = {"applies": True, "measured": any(r["measured"] for r in results),
             "reason": None if results else "no attempt was played",
             "reward_metric": metric_used, "failure_metrics": failure_metrics, "units": results}
    unmeasured = [r for r in results if not r["measured"]]
    if not results:
        measured = (False, "no attempt was played")
    elif unmeasured:
        measured = (False, "; ".join(f"{r['unit_id'] or 'the opening'}: {r['reason']}"
                                     for r in unmeasured[:4]))
    else:
        measured = (True, f"{len(results)} unit(s) played under both policies")
    counted = [r for r in results if r["measured"]]
    if not counted:
        reward = (None, measured[1])
    else:
        good = [r for r in counted if r["pays"] and r["risky"]]
        share = len(good) / len(counted)
        why = (f"{len(good)} of {len(counted)} measured unit(s) show greedy earning more "
               f"({metric_used}) at a higher failure rate; the bar is "
               f"{bars['min_unit_share']:.0%}")
        reward = (share >= bars["min_unit_share"], why)
    return block, {"measured": measured, "reward": reward}
