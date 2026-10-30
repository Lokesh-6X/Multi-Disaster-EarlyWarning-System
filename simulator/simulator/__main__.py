"""Command line (design/11 §11.8):

    python -m simulator run                                   # normal weather, real clock, 1× (stand-in kit)
    python -m simulator run --replay openmeteo --from 2024-05-25 --to 2024-05-31 [--lat … --lon …]
    python -m simulator run --replay data.csv
    python -m simulator validate                              # config, contract and one message per kit
    python -m simulator list-scenarios

Scenarios, faults and the demo clock arrive in M2.8; with `clock.mode: real` they are refused for good
(D39, DD125): simulated hazards never reach the real installation.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from simulator import config as sim_config
from simulator import contract
from simulator.kit import SimKit, aligned
from simulator.weather.normal import NormalWeather
from simulator.weather.replay import ReplayWeather, from_csv, from_open_meteo

SCENARIO_DIR = sim_config.SIM_DIR / "scenarios"
REFUSED = 3   # exit code of the D39 guard


def guard(cfg: sim_config.SimConfig, args: argparse.Namespace) -> str | None:
    """Why this run is not allowed, or None (D39, DD125)."""
    wants_hazard = args.scenario or args.fault
    if cfg.clock_mode == "real":
        if wants_hazard:
            return ("refused: scenarios and faults run only with clock.mode: demo (the demo database); "
                    "with the real clock the simulator is only a stand-in kit (D39, DD125)")
        if args.speed not in (None, 1, 1.0):
            return "refused: the real clock runs at 1× only (design/11 §11.3)"
        return None
    return "the demo clock, scenarios and faults arrive in M2.8; use clock.mode: real for now"


def make_kits(cfg: sim_config.SimConfig, args: argparse.Namespace, now: datetime) -> list[SimKit]:
    kits = []
    points = None
    if args.replay == "openmeteo":
        first = cfg.kits[0]
        points = from_open_meteo(args.lat if args.lat is not None else first.lat,
                                 args.lon if args.lon is not None else first.lon, args.date_from, args.date_to)
    elif args.replay:
        points = from_csv(Path(args.replay))
    for n, kit_cfg in enumerate(cfg.kits):
        rng = random.Random(cfg.seed * 1000 + n)
        if points is None:
            source = NormalWeather(rng, cfg.timezone)
        else:
            # real clock: shift the replay so its first point is the next reading slot (11 §11.4.1)
            shift = aligned(now, kit_cfg.sampling_interval_s) - points[0].ts
            source = ReplayWeather(points, rng, rain_mm_per_tip=kit_cfg.rain_mm_per_tip, shift=shift)
        kits.append(SimKit(kit_cfg, cfg.site_id, source, rng, boot=now))
    return kits


def run(cfg: sim_config.SimConfig, args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    kits = make_kits(cfg, args, now)
    every_kit = list(kits)
    for kit in kits:
        kit.connect(cfg.host, cfg.port, sim_config.password(kit.cfg))
    due = {k.cfg.kit_id: aligned(now, k.cfg.sampling_interval_s) for k in kits}
    sent = {k.cfg.kit_id: 0 for k in kits}
    print(f"simulator: {len(kits)} kit(s) on sites/{cfg.site_id}, {'replay' if args.replay else 'normal'} weather, "
          f"real clock 1x; Ctrl+C stops", flush=True)
    try:
        while True:
            kit = min(kits, key=lambda k: due[k.cfg.kit_id])
            ts = due[kit.cfg.kit_id]
            end = kit.source.end
            if end is not None and ts > end:
                print(f"{kit.cfg.kit_id}: end of the replay", flush=True)
                kits.remove(kit)
                if not kits:
                    break
                continue
            wait = (ts - datetime.now(timezone.utc)).total_seconds()
            if wait > 0:
                time.sleep(wait)
            if kit.publish(ts) is not None:
                sent[kit.cfg.kit_id] += 1
                if args.verbose:
                    print(f"{kit.cfg.kit_id}: seq {kit.seq - 1} at {ts:%H:%M:%S}", flush=True)
            due[kit.cfg.kit_id] = ts + timedelta(seconds=kit.cfg.sampling_interval_s)
            if args.count and all(n >= args.count for n in sent.values()):
                break
    except KeyboardInterrupt:
        pass
    except contract.ContractError as e:
        print(f"simulator bug: a message broke the contract: {e}", file=sys.stderr)
        return 1
    finally:
        for kit in every_kit:
            kit.close()
    print(f"simulator: stopped; published {sum(sent.values())} reading(s)", flush=True)
    return 0


def validate(cfg: sim_config.SimConfig) -> int:
    now = datetime.now(timezone.utc)
    args = argparse.Namespace(replay=None)
    for kit in make_kits(cfg, args, now):
        kit.payload(aligned(now, kit.cfg.sampling_interval_s))
        print(f"{kit.cfg.kit_id}: message valid ({kit.readings_topic})")
    print(f"config OK: {len(cfg.kits)} kit(s), clock {cfg.clock_mode}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m simulator")
    ap.add_argument("--config", type=Path, default=sim_config.CONFIG_FILE)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="publish readings")
    r.add_argument("--replay", help="openmeteo or a CSV file (design/11 §11.4.1)")
    r.add_argument("--lat", type=float)
    r.add_argument("--lon", type=float)
    r.add_argument("--from", dest="date_from", type=date.fromisoformat)
    r.add_argument("--to", dest="date_to", type=date.fromisoformat)
    r.add_argument("--scenario")
    r.add_argument("--fault", action="append")
    r.add_argument("--speed", type=float)
    r.add_argument("--count", type=int, help="stop after this many readings per kit")
    r.add_argument("--verbose", action="store_true")
    sub.add_parser("validate", help="check config.yaml and the contract")
    sub.add_parser("list-scenarios")
    args = ap.parse_args(argv)
    try:
        cfg = sim_config.load(args.config)
        if args.command == "validate":
            return validate(cfg)
        if args.command == "list-scenarios":
            for f in sorted(SCENARIO_DIR.glob("*.yaml")):
                print(f.stem)
            return 0
        reason = guard(cfg, args)
        if reason:
            print(reason, file=sys.stderr)
            return REFUSED
        if args.replay == "openmeteo" and not (args.date_from and args.date_to):
            ap.error("--replay openmeteo needs --from and --to")
        return run(cfg, args)
    except (sim_config.ConfigError, contract.ContractError, OSError) as e:
        print(f"simulator: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
