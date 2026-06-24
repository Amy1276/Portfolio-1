"""
Builds data/voo_holdings.csv: the full list of VOO (S&P 500) holdings
with an estimated % contribution (weight) for each stock.

How the weight is calculated:
    VOO tracks the S&P 500, which is weighted by market capitalization
    (price * shares outstanding). We don't have a live feed of the
    fund's official weights, so we approximate them the same way the
    index does: fetch each company's current market cap from Yahoo
    Finance, then divide by the total market cap of all companies.

This script is meant to be run occasionally (e.g. once a day), NOT on
every page load -- fetching ~500 quotes takes a few minutes. The web
app just reads the CSV this script produces.

Usage:
    python scripts/build_voo_holdings.py
"""

import csv
import time
from pathlib import Path

import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV = PROJECT_ROOT / "data" / "sp500_constituents.csv"
OUTPUT_CSV = PROJECT_ROOT / "data" / "voo_holdings.csv"


def to_yahoo_symbol(symbol: str) -> str:
    """Yahoo Finance uses a dash instead of a dot for share classes.

    Example: "BRK.B" (S&P 500 listing) -> "BRK-B" (Yahoo ticker).
    """
    return symbol.replace(".", "-")


def load_constituents() -> list[dict]:
    """Read the static ticker/name/sector list (Symbol, Security, GICS Sector, ...)."""
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def fetch_market_cap(symbol: str) -> float | None:
    """Get current market cap for one ticker. Returns None if unavailable."""
    try:
        info = yf.Ticker(symbol).fast_info
        market_cap = info.get("marketCap") if hasattr(info, "get") else info.market_cap
        if market_cap and market_cap > 0:
            return float(market_cap)
    except Exception as exc:
        print(f"  ! could not fetch market cap for {symbol}: {exc}")
    return None


def build_holdings() -> None:
    constituents = load_constituents()
    print(f"Loaded {len(constituents)} S&P 500 constituents from {INPUT_CSV.name}")

    rows = []
    for i, row in enumerate(constituents, start=1):
        symbol = row["Symbol"].strip()
        yahoo_symbol = to_yahoo_symbol(symbol)
        name = row["Security"].strip()
        sector = row.get("GICS Sector", "").strip()

        print(f"[{i}/{len(constituents)}] {symbol} ...", end=" ")
        market_cap = fetch_market_cap(yahoo_symbol)

        if market_cap is None:
            print("skipped (no data)")
            continue

        print(f"market cap = ${market_cap:,.0f}")
        rows.append(
            {
                "symbol": symbol,
                "yahoo_symbol": yahoo_symbol,
                "name": name,
                "sector": sector,
                "market_cap": market_cap,
            }
        )

        # Be polite to Yahoo Finance's free endpoint and avoid rate-limit errors.
        time.sleep(0.1)

    total_market_cap = sum(r["market_cap"] for r in rows)
    for r in rows:
        r["weight_percent"] = round(r["market_cap"] / total_market_cap * 100, 4)

    # Largest weight first, like a real fund holdings sheet.
    rows.sort(key=lambda r: r["weight_percent"], reverse=True)
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["rank", "symbol", "yahoo_symbol", "name", "sector", "market_cap", "weight_percent"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} holdings to {OUTPUT_CSV}")
    print(f"Total estimated market cap: ${total_market_cap:,.0f}")


if __name__ == "__main__":
    build_holdings()
