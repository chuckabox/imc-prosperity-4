"""
Real-World Market Data Fetcher for IMC Prosperity 4
====================================================
Fetches real commodity/stock data from Alpha Vantage + yfinance,
normalizes it into IMC-compatible tick format for robust backtesting.

Usage:
    IMC_PROSPERITY_ALLOW_REAL_FETCH=1 python real_data_fetcher.py
    python real_data_fetcher.py --list
    python real_data_fetcher.py --source av
    python real_data_fetcher.py --source yf
"""

import os
import sys
import json
import time
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data_capsule"
REAL_DATA_DIR = DATA_DIR / "real_world"
RAW_DIR = REAL_DATA_DIR / "raw"
NORMALIZED_DIR = REAL_DATA_DIR / "normalized"
METADATA_FILE = REAL_DATA_DIR / "metadata.json"

REAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

IMC_TICKS_PER_DAY = 10000
IMC_TICK_INTERVAL = 100


def _real_fetch_allowed() -> bool:
    v = os.environ.get("IMC_PROSPERITY_ALLOW_REAL_FETCH", "").strip().lower()
    return v in ("1", "true", "yes")


PEPPER_ANALOGS = {
    "yf": {
        "ZC=F":  "Corn Futures (CBOT)",
        "ZW=F":  "Wheat Futures (CBOT)",
        "ZS=F":  "Soybean Futures (CBOT)",
        "MKC":   "McCormick & Co (Spices)",
        "BGS":   "B&G Foods (Pepper/Spice)",
        "ADM":   "Archer-Daniels-Midland (Ag)",
    },
    "av": {
        "CORN":   "Corn (Global Price Index)",
        "WHEAT":  "Wheat (Global Price Index)",
        "COFFEE": "Coffee (Global Price Index)",
        "SUGAR":  "Sugar (Global Price Index)",
        "COTTON": "Cotton (Global Price Index)",
    }
}

OSMIUM_ANALOGS = {
    "yf": {
        "GC=F":  "Gold Futures (mean-reverting intraday)",
        "GLD":   "SPDR Gold Shares ETF",
    },
    "av": {
        "COPPER":   "Copper (Global Price Index)",
        "ALUMINUM": "Aluminum (Global Price Index)",
    }
}


def load_api_key() -> Optional[str]:
    """Load Alpha Vantage API key from .env file."""
    env_path = PROJECT_ROOT.parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        for p in [PROJECT_ROOT / ".env", Path.cwd() / ".env"]:
            if p.exists():
                env_path = p
                break

    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ALPHAVANTAGE_API_KEY=") and not line.endswith("YOUR_KEY_HERE"):
                    return line.split("=", 1)[1].strip()

    return os.environ.get("ALPHAVANTAGE_API_KEY")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_yfinance(symbols: Dict[str, str], period: str = "2y") -> Dict[str, pd.DataFrame]:
    """Fetch daily OHLCV from yfinance."""
    import yfinance as yf

    results = {}
    for symbol, desc in symbols.items():
        print(f"  [yfinance] Fetching {symbol} ({desc})...")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, auto_adjust=True)
            if df.empty:
                print(f"    WARNING: No data returned for {symbol}")
                continue

            df = df.reset_index()
            df = df.rename(columns={"Date": "date", "Open": "open", "High": "high",
                                     "Low": "low", "Close": "close", "Volume": "volume"})
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df = df[["date", "open", "high", "low", "close", "volume"]].dropna()

            raw_path = RAW_DIR / f"yf_{symbol.replace('=', '_')}.csv"
            df.to_csv(raw_path, index=False)
            results[symbol] = df
            print(f"    OK: {len(df)} days, range [{df['close'].min():.2f}, {df['close'].max():.2f}]")
        except Exception as e:
            print(f"    ERROR: {e}")

    return results


def fetch_alpha_vantage(symbols: Dict[str, str], api_key: str) -> Dict[str, pd.DataFrame]:
    """Fetch commodity data from Alpha Vantage."""
    results = {}
    base_url = "https://www.alphavantage.co/query"

    import requests

    for symbol, desc in symbols.items():
        print(f"  [AlphaVantage] Fetching {symbol} ({desc})...")
        try:
            params = {
                "function": symbol,
                "interval": "monthly",
                "apikey": api_key,
            }
            resp = requests.get(base_url, params=params, timeout=30)
            data = resp.json()

            if "data" not in data:
                if "Note" in data or "Information" in data:
                    msg = data.get("Note", data.get("Information", ""))
                    print(f"    RATE LIMITED: {msg}")
                    print(f"    Waiting 60s before retry...")
                    time.sleep(62)
                    resp = requests.get(base_url, params=params, timeout=30)
                    data = resp.json()

                if "data" not in data:
                    print(f"    WARNING: Unexpected response for {symbol}: {list(data.keys())}")
                    continue

            rows = data["data"]
            df = pd.DataFrame(rows)
            df = df.rename(columns={"date": "date", "value": "close"})
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["date"] = pd.to_datetime(df["date"])
            df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)

            df["open"] = df["close"].shift(1).fillna(df["close"])
            df["high"] = df["close"] * 1.02
            df["low"] = df["close"] * 0.98
            df["volume"] = 1000

            raw_path = RAW_DIR / f"av_{symbol.lower()}.csv"
            df.to_csv(raw_path, index=False)
            results[symbol] = df
            print(f"    OK: {len(df)} months, range [{df['close'].min():.2f}, {df['close'].max():.2f}]")

            time.sleep(13)

        except Exception as e:
            print(f"    ERROR: {e}")

    return results


# ---------------------------------------------------------------------------
# Normalization: Real prices -> IMC tick format
# ---------------------------------------------------------------------------

def normalize_to_imc_day(
    df: pd.DataFrame,
    target_product: str,
    target_start: float,
    target_range: float,
    day_label: str,
    ticks: int = IMC_TICKS_PER_DAY,
) -> pd.DataFrame:
    """
    Convert a real-world daily OHLCV series into an IMC-format price CSV.

    Each real-world day becomes one IMC "day" of 10,000 ticks.
    Prices are scaled to the target range (e.g. Pepper 10000-13000).
    """
    closes = df["close"].values.astype(float)
    n = len(closes)
    if n < 2:
        return pd.DataFrame()

    src_indices = np.linspace(0, n - 1, ticks)
    interpolated = np.interp(src_indices, np.arange(n), closes)

    raw_min, raw_max = interpolated.min(), interpolated.max()
    raw_span = raw_max - raw_min
    if raw_span < 1e-9:
        raw_span = 1.0

    scaled = target_start + (interpolated - raw_min) / raw_span * target_range

    rows = []
    for i in range(ticks):
        ts = i * IMC_TICK_INTERVAL
        mid = scaled[i]
        noise = np.random.normal(0, 0.3)

        spread = max(6, int(np.random.exponential(8)))
        half = spread / 2.0

        bid1 = int(mid - half + noise)
        ask1 = int(mid + half + noise)
        if bid1 >= ask1:
            ask1 = bid1 + 1

        bid_vol1 = int(np.clip(np.random.normal(15, 5), 5, 30))
        ask_vol1 = int(np.clip(np.random.normal(15, 5), 5, 30))

        bid2 = bid1 - int(np.random.uniform(2, 5))
        ask2 = ask1 + int(np.random.uniform(2, 5))
        bid_vol2 = int(np.clip(np.random.normal(20, 5), 8, 35))
        ask_vol2 = int(np.clip(np.random.normal(20, 5), 8, 35))

        rows.append({
            "day": day_label,
            "timestamp": ts,
            "product": target_product,
            "bid_price_1": bid1, "bid_volume_1": bid_vol1,
            "bid_price_2": bid2, "bid_volume_2": bid_vol2,
            "bid_price_3": "", "bid_volume_3": "",
            "ask_price_1": ask1, "ask_volume_1": ask_vol1,
            "ask_price_2": ask2, "ask_volume_2": ask_vol2,
            "ask_price_3": "", "ask_volume_3": "",
            "mid_price": round((bid1 + ask1) / 2, 1),
            "profit_and_loss": 0.0,
        })

    return pd.DataFrame(rows)


def generate_imc_days_from_real(
    df_raw: pd.DataFrame,
    source_name: str,
    target_product: str,
    target_start: float,
    target_range: float,
    window_days: int = 60,
    stride_days: int = 30,
) -> List[Tuple[str, pd.DataFrame]]:
    """
    Slice a real-world series into overlapping windows, each becoming one IMC day.
    This gives us many diverse "days" from a single source.
    """
    results = []
    n = len(df_raw)

    if n < window_days:
        label = f"{source_name}_full"
        imc_df = normalize_to_imc_day(df_raw, target_product, target_start, target_range, label)
        if not imc_df.empty:
            results.append((label, imc_df))
        return results

    idx = 0
    day_num = 0
    while idx + window_days <= n:
        chunk = df_raw.iloc[idx:idx + window_days].reset_index(drop=True)
        label = f"{source_name}_d{day_num}"
        imc_df = normalize_to_imc_day(chunk, target_product, target_start, target_range, label)
        if not imc_df.empty:
            results.append((label, imc_df))
        idx += stride_days
        day_num += 1

    return results


def build_paired_days(
    pepper_days: List[Tuple[str, pd.DataFrame]],
    osmium_days: List[Tuple[str, pd.DataFrame]],
) -> List[Tuple[str, pd.DataFrame]]:
    """
    Pair each pepper day with an osmium day to create full IMC-format CSVs.
    If we have more pepper days than osmium, osmium days are recycled.
    """
    paired = []
    n_osm = len(osmium_days) if osmium_days else 0

    for i, (pep_label, pep_df) in enumerate(pepper_days):
        if n_osm > 0:
            osm_label, osm_df = osmium_days[i % n_osm]
            osm_copy = osm_df.copy()
            osm_copy["day"] = pep_label
            combined = pd.concat([pep_df, osm_copy], ignore_index=True)
            combined = combined.sort_values(["timestamp", "product"]).reset_index(drop=True)
        else:
            combined = pep_df

        paired.append((pep_label, combined))

    return paired


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def fetch_all(sources: str = "both") -> Dict:
    """Fetch from all configured sources."""
    if not _real_fetch_allowed():
        print(
            "Real-world network fetch is disabled by default (no yfinance / Alpha Vantage calls).\n"
            "Set IMC_PROSPERITY_ALLOW_REAL_FETCH=1 in the environment to enable fetching.\n"
            "Use: python real_data_fetcher.py --list   (reads local cache only)"
        )
        return {}

    api_key = load_api_key()
    metadata = {"fetched_at": datetime.now().isoformat(), "datasets": {}}

    all_pepper_raw = {}
    all_osmium_raw = {}

    print("\n=== FETCHING PEPPER ROOT ANALOGS ===")
    if sources in ("both", "yf"):
        yf_pepper = fetch_yfinance(PEPPER_ANALOGS["yf"])
        all_pepper_raw.update({f"yf_{k}": v for k, v in yf_pepper.items()})

    if sources in ("both", "av") and api_key:
        av_pepper = fetch_alpha_vantage(PEPPER_ANALOGS["av"], api_key)
        all_pepper_raw.update({f"av_{k}": v for k, v in av_pepper.items()})
    elif sources in ("both", "av") and not api_key:
        print("  SKIP: No Alpha Vantage API key found. Set AV_API_KEY in .env")

    print("\n=== FETCHING OSMIUM ANALOGS ===")
    if sources in ("both", "yf"):
        yf_osmium = fetch_yfinance(OSMIUM_ANALOGS["yf"])
        all_osmium_raw.update({f"yf_{k}": v for k, v in yf_osmium.items()})

    if sources in ("both", "av") and api_key:
        av_osmium = fetch_alpha_vantage(OSMIUM_ANALOGS["av"], api_key)
        all_osmium_raw.update({f"av_{k}": v for k, v in av_osmium.items()})

    print(f"\n=== NORMALIZING TO IMC FORMAT ===")
    print(f"Pepper sources: {len(all_pepper_raw)}, Osmium sources: {len(all_osmium_raw)}")

    all_pepper_days = []
    for name, df in all_pepper_raw.items():
        days = generate_imc_days_from_real(
            df, name,
            target_product="INTARIAN_PEPPER_ROOT",
            target_start=10000, target_range=3000,
            window_days=60, stride_days=30,
        )
        all_pepper_days.extend(days)
        print(f"  {name}: generated {len(days)} IMC days")

    all_osmium_days = []
    for name, df in all_osmium_raw.items():
        days = generate_imc_days_from_real(
            df, name,
            target_product="ASH_COATED_OSMIUM",
            target_start=9900, target_range=200,
            window_days=60, stride_days=30,
        )
        all_osmium_days.extend(days)
        print(f"  {name}: generated {len(days)} IMC days")

    print(f"\n=== PAIRING & SAVING ===")
    paired = build_paired_days(all_pepper_days, all_osmium_days)
    print(f"Total paired IMC days: {len(paired)}")

    for label, df in paired:
        safe_label = label.replace("=", "_").replace("/", "_")
        out_path = NORMALIZED_DIR / f"prices_{safe_label}.csv"
        df.to_csv(out_path, sep=";", index=False)
        metadata["datasets"][safe_label] = {
            "file": str(out_path.relative_to(REAL_DATA_DIR)),
            "ticks": len(df),
            "products": df["product"].unique().tolist(),
        }

    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nSaved {len(paired)} normalized day files to: {NORMALIZED_DIR}")
    print(f"Metadata: {METADATA_FILE}")

    return metadata


def list_cached():
    """List all cached datasets."""
    if not METADATA_FILE.exists():
        print("No cached data. Run: python real_data_fetcher.py")
        return

    with open(METADATA_FILE) as f:
        meta = json.load(f)

    print(f"Fetched: {meta.get('fetched_at', 'unknown')}")
    print(f"Datasets: {len(meta.get('datasets', {}))}")
    print()

    for name, info in meta.get("datasets", {}).items():
        print(f"  {name}: {info['ticks']} ticks, products={info['products']}")

    raw_files = list(RAW_DIR.glob("*.csv"))
    print(f"\nRaw files: {len(raw_files)}")
    for f in sorted(raw_files):
        df = pd.read_csv(f)
        print(f"  {f.name}: {len(df)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch real-world market data for IMC training")
    parser.add_argument("--list", action="store_true", help="List cached datasets")
    parser.add_argument("--source", choices=["both", "yf", "av"], default="both",
                        help="Data source: yf=yfinance, av=AlphaVantage, both=all")
    args = parser.parse_args()

    if args.list:
        list_cached()
    else:
        fetch_all(sources=args.source)
