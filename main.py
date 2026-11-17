"""Hour-by-hour Twitch viewer forecast for a game launch day.

The program reads every case file in the input directory. Each case carries
the launch's first-hour viewer count plus the full hourly curves of past
launches (the comparables). The forecast for each later hour is built from
those past curves, rescaled to this launch's own first hour:

  - Every comparable contributes the log ratio of its viewers in that hour
    to its own first-hour count.
  - Comparables are weighted by how close their first-hour count is to this
    launch's, on the log scale, with a Gaussian kernel of bandwidth 1.
  - The five quantiles of an hour are the interpolated weighted quantiles
    of that hour's log-ratio distribution, shifted back by this launch's
    first-hour count.

The shape a launch day takes depends strongly on how big its first hour
already is: launches that open huge stay near their first hour, launches
that open small build through the day. Conditioning on the first hour's
size captures that without any assumption about which launch is which.
When too few comparables cover an hour, the forecast falls back to a
persistence fan that widens like a random walk in log space.

Standard library only, offline, deterministic: the same input bytes always
produce the same output bytes.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard normal quantiles at the scored levels, for the fallback fan.
NORMAL_Q = [-1.645, -0.674, 0.0, 0.674, 1.645]
FALLBACK_SIGMA = 0.15
# Gaussian kernel bandwidth on log first-hour viewers.
BANDWIDTH = 1.0
# An hour needs at least this many comparable curves, else the fallback fan.
MIN_CURVES = 5
# Output bounds required by the contest.
Q_FLOOR = 0.01
Q_CAP = 1_000_000_000.0


def parse_time(text):
    """Parse an ISO 8601 UTC timestamp into a datetime."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def comparable_curves(case):
    """Extract each comparable's release-day curve as {hour: viewers}.

    Only curves with a positive first-hour count are usable; the rest are
    skipped (a pre-release history has no release-day first hour).
    """
    curves = []
    for comp in case.get("comparables") or []:
        try:
            start = parse_time(comp["day_start"])
        except (KeyError, TypeError, ValueError):
            continue
        hours = {}
        for point in comp.get("hourly") or []:
            try:
                when = parse_time(point["from"])
                viewers = point["viewers"]
            except (KeyError, TypeError, ValueError):
                continue
            hour = int((when - start).total_seconds() // 3600) + 1
            if 1 <= hour <= 24 and isinstance(viewers, (int, float)):
                hours[hour] = viewers
        first = hours.get(1)
        if first is None or first <= 0:
            continue
        curves.append((first, hours))
    return curves


def weighted_quantile(pairs, tau):
    """Interpolated weighted quantile of values sorted ascending.

    Each pair is (value, weight). The cumulative weight axis is marked at
    interval midpoints, and the value at the tau point is linearly
    interpolated between neighbouring marks.
    """
    total = sum(w for _, w in pairs)
    marks = []
    acc = 0.0
    for _, w in pairs:
        acc += w
        marks.append(acc - 0.5 * w)
    target = tau * total
    if target <= marks[0]:
        return pairs[0][0]
    if target >= marks[-1]:
        return pairs[-1][0]
    for i in range(1, len(pairs)):
        if marks[i] >= target:
            span = marks[i] - marks[i - 1]
            frac = (target - marks[i - 1]) / span if span > 0 else 0.0
            return pairs[i - 1][0] * (1.0 - frac) + pairs[i][0] * frac
    return pairs[-1][0]


def fallback_row(anchor, hour):
    """Persistence fan: every quantile around the first-hour count."""
    spread = FALLBACK_SIGMA * math.sqrt(hour - 1)
    return [anchor * math.exp(z * spread) for z in NORMAL_Q]


def forecast_hour(anchor, log_anchor, curves, hour):
    """The five quantiles for one hour from the comparable curves."""
    pairs = []
    for first, hours in curves:
        value = hours.get(hour)
        if value is None or value <= 0:
            continue
        dist = (math.log(first) - log_anchor) / BANDWIDTH
        weight = math.exp(-0.5 * dist * dist)
        pairs.append((math.log(value / first), weight))
    if len(pairs) < MIN_CURVES:
        return fallback_row(anchor, hour)
    pairs.sort()
    return [anchor * math.exp(weighted_quantile(pairs, tau)) for tau in LEVELS]


def clean_row(values):
    """Clamp to the allowed range, round, and enforce non-decreasing order."""
    out = []
    prev = None
    for value in values:
        q = round(max(Q_FLOOR, min(Q_CAP, value)), 2)
        if q <= 0:
            q = Q_FLOOR
        if prev is not None and q < prev:
            q = prev
        out.append(q)
        prev = q
    return out


def first_hour_anchor(case):
    """Hour 1's print, with defensive fallbacks if the known row is absent."""
    for row in case.get("known") or []:
        if row.get("hour") == 1 and row.get("viewers"):
            return max(1.0, float(row["viewers"]))
    for row in case.get("known") or []:
        if row.get("viewers"):
            return max(1.0, float(row["viewers"]))
    hourly = case.get("history_hourly") or []
    if hourly:
        last = hourly[-1].get("viewers")
        if last:
            return max(1.0, float(last))
    history = case.get("history") or []
    if history:
        last = history[-1].get("viewers")
        if last:
            return max(1.0, float(last))
    return 1.0


def forecast_rows(case):
    """The hours to forecast, from the case, with a safe default."""
    rows = case.get("forecast")
    if not isinstance(rows, list) or not rows:
        return [{"hour": h} for h in range(2, 25)]
    return rows


def row_hour(row, default):
    """An hour number from a forecast row, defaulting when malformed."""
    if isinstance(row, dict):
        try:
            return int(row["hour"])
        except (KeyError, TypeError, ValueError):
            return default
    return default


def forecast_case(case):
    anchor = first_hour_anchor(case)
    log_anchor = math.log(anchor)
    curves = comparable_curves(case)
    hours = []
    for i, row in enumerate(forecast_rows(case)):
        hour = row_hour(row, i + 2)
        hours.append({"hour": hour, "q": clean_row(forecast_hour(anchor, log_anchor, curves, hour))})
    return {"hours": hours}


def baseline_case(case):
    """Last-resort forecast: the persistence fan around the anchor."""
    anchor = first_hour_anchor(case)
    hours = []
    for i, row in enumerate(forecast_rows(case)):
        hour = row_hour(row, i + 2)
        hours.append({"hour": hour, "q": clean_row(fallback_row(anchor, hour))})
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            case = {}
        try:
            forecast = forecast_case(case)
        except Exception:
            forecast = baseline_case(case)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
