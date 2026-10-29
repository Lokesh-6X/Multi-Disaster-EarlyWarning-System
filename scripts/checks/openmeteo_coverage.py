"""Week-1 check 2 (M0.5, DD113, DD118, design/06 §6.3): first date with data per variable in the
Open-Meteo Previous Runs API (lead-correct archived forecasts), and gaps after that date.

Usage: python scripts/checks/openmeteo_coverage.py [--lat 28.61 --lon 77.21] [--from 2020-01-01 --to 2025-12-31]
One request per lead day (six variables, whole period), 10 s apart; waits for Retry-After on 429 (DD118).
Standard library only.
"""
import argparse
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_gusts_10m", "precipitation", "pressure_msl"]
LEADS = [1, 2, 3]


def fetch(params, tries=3):
    url = URL + "?" + urllib.parse.urlencode(params)
    failures = 0
    while True:
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "60"))
                print(f"  429, waiting {wait} s")
                time.sleep(wait)
                continue
            raise SystemExit(f"HTTP {e.code}: {e.read().decode()[:300]}")
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError) as e:
            failures += 1
            if failures >= tries:
                raise
            print(f"  download broken ({type(e).__name__}), retrying in 10 s")
            time.sleep(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=28.61)
    ap.add_argument("--lon", type=float, default=77.21)
    ap.add_argument("--from", dest="start", default="2020-01-01")
    ap.add_argument("--to", dest="end", default="2025-12-31")
    args = ap.parse_args()

    rows = []
    for i, lead in enumerate(LEADS):
        if i:
            time.sleep(10)
        names = [f"{v}_previous_day{lead}" for v in VARIABLES]
        data = fetch({
            "latitude": args.lat, "longitude": args.lon, "start_date": args.start, "end_date": args.end,
            "hourly": ",".join(names), "wind_speed_unit": "kmh", "timezone": "GMT",
        })
        times = data["hourly"]["time"]
        for name in names:
            values = data["hourly"][name]
            per_day = defaultdict(int)
            for t, v in zip(times, values):
                if v is not None:
                    per_day[t[:10]] += 1
            if not per_day:
                rows.append((name, None, 0, 0))
                continue
            first = min(per_day)
            days_after = sorted({t[:10] for t in times if t[:10] >= first})
            incomplete = sum(1 for d in days_after if per_day.get(d, 0) < 24)
            rows.append((name, first, len(days_after), incomplete))

    weight = len(VARIABLES) / 10 * (len(times) / 24) / 14
    # ASCII only: the Windows console code page cannot print every character
    print(f"Location {args.lat}, {args.lon}; period {args.start} to {args.end}; "
          f"{len(LEADS)} requests of about {weight:.0f} weighted calls each")
    print(f"{'variable':42} {'first date':12} {'days':>5} {'days < 24 h':>12}")
    for name, first, days, incomplete in rows:
        print(f"{name:42} {first or '-':12} {days:>5} {incomplete:>12}")


if __name__ == "__main__":
    main()
