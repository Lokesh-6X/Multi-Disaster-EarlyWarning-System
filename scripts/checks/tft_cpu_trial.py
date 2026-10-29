"""Week-1 check 3 (M0.6, DD113, design/06 §6.5, §6.8.2): Darts TFT end to end on a laptop CPU.

TFT with 5 targets, static + past + future covariates and 9 quantiles; 2 locations of ERA5
(Open-Meteo Archive), 1 epoch; save, reload, predict. Pass when the reloaded model gives identical
predictions and inference for one series takes < 10 s.

Usage: python scripts/checks/tft_cpu_trial.py --work <scratch dir>
"""
import argparse
import json
import platform
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

LOCATIONS = {  # design/06 §6.2
    "delhi": {"lat": 28.61, "lon": 77.21, "region": "plains"},
    "chennai": {"lat": 13.08, "lon": 80.27, "region": "coastal"},
}
REGIONS = ["plains", "coastal", "hilly"]
HOURLY = "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_gusts_10m,precipitation,pressure_msl"
TARGETS = ["temp_c", "rh_pct", "wind_gust_kmh", "rain_mm", "pressure_msl_hpa"]
QUANTILES = [0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.98]  # DD51
START, END = "2023-01-01", "2024-12-31"
INPUT_LEN, OUTPUT_LEN = 168, 72


def download(work: Path, name: str, loc: dict) -> pd.DataFrame:
    """ERA5 hourly from the Open-Meteo Archive (design/05 §5.8.2), cached; one request per location."""
    cache = work / f"era5_{name}.json"
    if not cache.exists():
        q = urllib.parse.urlencode({
            "latitude": loc["lat"], "longitude": loc["lon"], "start_date": START, "end_date": END,
            "hourly": HOURLY, "models": "era5", "wind_speed_unit": "kmh", "timezone": "GMT",
        })
        with urllib.request.urlopen("https://archive-api.open-meteo.com/v1/archive?" + q, timeout=180) as r:
            cache.write_bytes(r.read())
        time.sleep(10)  # DD118 pacing
    data = json.loads(cache.read_text())
    h = data["hourly"]
    df = pd.DataFrame({
        "temp_c": h["temperature_2m"], "rh_pct": h["relative_humidity_2m"], "wind_avg_kmh": h["wind_speed_10m"],
        "wind_gust_kmh": h["wind_gusts_10m"], "rain_mm": h["precipitation"], "pressure_msl_hpa": h["pressure_msl"],
    }, index=pd.to_datetime(h["time"]))
    df.attrs["elevation_m"] = data.get("elevation", 0.0)
    return df.astype("float32").interpolate(limit_direction="both")


def build(name: str, loc: dict, df: pd.DataFrame):
    from darts import TimeSeries

    static = pd.DataFrame([{
        "lat": loc["lat"], "lon": loc["lon"], "elevation_m": df.attrs["elevation_m"],
        **{f"region_{r}": float(loc["region"] == r) for r in REGIONS},
    }])
    target = TimeSeries.from_dataframe(df[TARGETS], freq="h", static_covariates=static).astype(np.float32)

    past = pd.DataFrame({
        "wind_avg_kmh": df["wind_avg_kmh"],
        "pressure_tendency_3h": df["pressure_msl_hpa"].diff(3),
        "rain_24h": df["rain_mm"].rolling(24, min_periods=1).sum(),
    }).bfill()
    past_ts = TimeSeries.from_dataframe(past, freq="h").astype(np.float32)

    # Future covariates must reach OUTPUT_LEN hours past the target's end for prediction
    idx = pd.date_range(df.index[0], df.index[-1] + pd.Timedelta(hours=OUTPUT_LEN), freq="h")
    daily_max = df["temp_c"].resample("D").max()
    normal = daily_max.groupby(daily_max.index.dayofyear).mean()  # stand-in for the 1991-2020 normal
    future = pd.DataFrame({
        "hour_sin": np.sin(2 * np.pi * idx.hour / 24), "hour_cos": np.cos(2 * np.pi * idx.hour / 24),
        "doy_sin": np.sin(2 * np.pi * idx.dayofyear / 366), "doy_cos": np.cos(2 * np.pi * idx.dayofyear / 366),
        "month": idx.month.astype(float),
        "normal_tmax_c": normal.reindex(idx.dayofyear).to_numpy(),
    }, index=idx)
    future_ts = TimeSeries.from_dataframe(future, freq="h").astype(np.float32)
    return target, past_ts, future_ts


def make_model(work: Path):
    from darts.models import TFTModel
    from darts.utils.likelihood_models import QuantileRegression

    return TFTModel(  # design/06 §6.8.2
        input_chunk_length=INPUT_LEN, output_chunk_length=OUTPUT_LEN,
        hidden_size=64, lstm_layers=1, num_attention_heads=4, dropout=0.1,
        batch_size=256, n_epochs=1, likelihood=QuantileRegression(quantiles=QUANTILES),
        use_static_covariates=True, random_state=42, model_name="tft_cpu_trial",
        work_dir=str(work), save_checkpoints=True, force_reset=True,
        pl_trainer_kwargs={"accelerator": "cpu", "enable_progress_bar": False},
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--max-samples", type=int, default=3000, help="training samples per location")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    import darts
    import lightgbm
    import torch
    from darts.dataprocessing.transformers import Scaler
    from darts.models import TFTModel

    torch.set_num_threads(max(1, torch.get_num_threads()))
    series = [build(n, loc, download(args.work, n, loc)) for n, loc in LOCATIONS.items()]
    cut = pd.Timestamp("2024-10-01")
    train_t = [t.split_before(cut)[0] for t, _, _ in series]
    past = [p for _, p, _ in series]
    future = [f for _, _, f in series]
    scaler = Scaler()
    train_scaled = scaler.fit_transform(train_t)

    model = make_model(args.work)
    t0 = time.perf_counter()
    model.fit(train_scaled, past_covariates=past, future_covariates=future, max_samples_per_ts=args.max_samples)
    fit_s = time.perf_counter() - t0

    path = args.work / "tft_trial.pt"
    model.save(str(path))
    size_mb = sum(p.stat().st_size for p in args.work.glob("tft_trial.pt*")) / 1e6

    def predict(m, i=0):
        return m.predict(n=OUTPUT_LEN, series=train_scaled[i], past_covariates=past[i], future_covariates=future[i],
                         predict_likelihood_parameters=True, verbose=False)

    before = predict(model)
    loaded = TFTModel.load(str(path), pl_trainer_kwargs={"accelerator": "cpu", "enable_progress_bar": False})
    predict(loaded)  # warm-up (first call builds the trainer)
    t1 = time.perf_counter()
    after = predict(loaded)
    infer_s = time.perf_counter() - t1
    identical = np.array_equal(before.values(), after.values())

    print(f"python {platform.python_version()}, torch {torch.__version__}, darts {darts.__version__}, lightgbm {lightgbm.__version__}")
    print(f"training: 2 locations, 1 epoch, {args.max_samples} samples/location: {fit_s:.0f} s")
    print(f"prediction: {after.n_timesteps} h x {after.n_components} columns (5 targets x 9 quantiles)")
    print(f"model on disk: {size_mb:.1f} MB")
    print(f"{'OK  ' if identical else 'FAIL'} reloaded model gives identical predictions")
    print(f"{'OK  ' if infer_s < 10 else 'FAIL'} inference for one series: {infer_s:.2f} s (< 10 s)")
    ok = identical and infer_s < 10 and after.n_components == 45
    print("TFT CPU TRIAL OK" if ok else "TFT CPU TRIAL FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
