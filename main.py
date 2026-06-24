from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import yfinance as yf
import random
import csv
import time
from datetime import timedelta

app = FastAPI()

# Holdings CSV produced by scripts/build_voo_holdings.py (full ~503 S&P 500 / VOO
# constituents with an estimated % weight). Only the top N get a live price quote
# below, since fetching 500 real-time quotes on every page load isn't practical.
VOO_HOLDINGS_CSV = "data/voo_holdings.csv"
VOO_TOP_N_LIVE = 20

# Danh sách 9 mã cổ phiếu công nghệ hàng đầu trên sàn NASDAQ
TECH_STOCKS = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Alphabet (Google)
    "NVDA",   # NVIDIA
    "TSLA",   # Tesla
    "AMZN",   # Amazon
    "META",   # Meta (Facebook)
    "AVGO",   # Broadcom
    "QCOM"    # Qualcomm
]

# Giá cơ sở mặc định để dùng làm dữ liệu dự phòng (Mock Data) khi API Yahoo lỗi
MOCK_BASE_PRICES = {
    "AAPL": 180.50, "MSFT": 420.20, "GOOGL": 175.10, 
    "NVDA": 900.20, "TSLA": 170.80, "AMZN": 185.30, 
    "META": 475.60, "AVGO": 1300.00, "QCOM": 195.40
}

@app.get("/api/stocks")
def get_stock_data():
    data = {}
    for ticker in TECH_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            # Lấy dữ liệu 1 ngày gần nhất, chia theo khoảng cách mỗi 5 phút
            hist = stock.history(period="1d", interval="5m")
            
            if not hist.empty:
                latest_row = hist.iloc[-1]
                # Lấy giá đóng cửa ngày hôm trước hoặc giá mở cửa để tính % biến động
                prev_close = stock.info.get("previousClose", latest_row["Open"])
                current_price = latest_row["Close"]
                price_change = current_price - prev_close
                pct_change = (price_change / prev_close) * 100
                
                # Lấy 12 điểm giá gần nhất để làm đường biểu đồ mini (sparkline)
                prices_list = hist["Close"].tail(12).tolist()
                
                data[ticker] = {
                    "price": round(current_price, 2),
                    "change": round(price_change, 2),
                    "pct_change": round(pct_change, 2),
                    "high": round(latest_row["High"], 2),
                    "low": round(latest_row["Low"], 2),
                    "sparkline": [round(p, 2) for p in prices_list]
                }
                continue # Thành công thì bỏ qua phần mock data phía dưới
        except Exception as e:
            print(f"⚠️ [Yahoo Finance] Lỗi mã {ticker}: {e}. Đang dùng dữ liệu mô phỏng.")

        # --- TỰ ĐỘNG CỨU CÁNH: MOCK DATA KHI MẠNG HOẶC API CÓ VẤN ĐỀ ---
        base_price = MOCK_BASE_PRICES[ticker]
        pct_change = random.uniform(-2.0, 2.0)
        price_change = base_price * (pct_change / 100)
        current_price = base_price + price_change
        
        sparkline = []
        temp_price = base_price
        for _ in range(12):
            temp_price += random.uniform(-1.0, 1.0)
            sparkline.append(round(temp_price, 2))

        data[ticker] = {
            "price": round(current_price, 2),
            "change": round(price_change, 2),
            "pct_change": round(pct_change, 2),
            "high": round(current_price + random.uniform(0, 1.5), 2),
            "low": round(current_price - random.uniform(0, 1.5), 2),
            "sparkline": sparkline
        }
            
    return data

def load_voo_holdings():
    """Read the pre-built holdings CSV (rank, symbol, name, sector, weight_percent, ...)."""
    with open(VOO_HOLDINGS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def get_live_price(yahoo_symbol):
    """Fetch a current quote for one ticker. Returns None if Yahoo Finance fails."""
    try:
        fast_info = yf.Ticker(yahoo_symbol).fast_info
        price = fast_info.get("lastPrice")
        prev_close = fast_info.get("previousClose")
        if price is None or prev_close is None:
            return None
        change = price - prev_close
        pct_change = (change / prev_close) * 100
        return {
            "price": round(price, 2),
            "change": round(change, 2),
            "pct_change": round(pct_change, 2),
        }
    except Exception as e:
        print(f"⚠️ [Yahoo Finance] Could not fetch live price for {yahoo_symbol}: {e}")
        return None


# YTD/1Y/3Y returns barely move within a 15s refresh cycle, so they're cached for an
# hour to avoid re-downloading 3 years of daily history per ticker on every page load.
_PERFORMANCE_CACHE = {}
_PERFORMANCE_CACHE_TTL_SECONDS = 3600


def get_performance_metrics(yahoo_symbol):
    """YTD / 1Y / 3Y total return (%) for one ticker, computed from daily adjusted closes."""
    cached = _PERFORMANCE_CACHE.get(yahoo_symbol)
    if cached and (time.time() - cached[0]) < _PERFORMANCE_CACHE_TTL_SECONDS:
        return cached[1]

    metrics = None
    try:
        hist = yf.Ticker(yahoo_symbol).history(period="3y", interval="1d", auto_adjust=True)
        if not hist.empty:
            hist.index = hist.index.tz_localize(None)
            last_close = hist["Close"].iloc[-1]
            last_date = hist.index[-1]

            ytd_rows = hist[hist.index.year == last_date.year]
            ytd_base = ytd_rows["Close"].iloc[0] if not ytd_rows.empty else None

            def closest_close(days_back):
                idx = min(hist.index.searchsorted(last_date - timedelta(days=days_back)), len(hist) - 1)
                return hist["Close"].iloc[idx]

            metrics = {
                "ytd_pct": round((last_close / ytd_base - 1) * 100, 2) if ytd_base else None,
                "one_year_pct": round((last_close / closest_close(365) - 1) * 100, 2),
                "three_year_pct": round((last_close / closest_close(365 * 3 - 5) - 1) * 100, 2),
            }
    except Exception as e:
        print(f"⚠️ [Yahoo Finance] Could not fetch performance history for {yahoo_symbol}: {e}")

    _PERFORMANCE_CACHE[yahoo_symbol] = (time.time(), metrics)
    return metrics


@app.get("/api/voo")
def get_voo_holdings():
    """
    Returns every VOO/S&P 500 holding with its % contribution (weight).
    Only the top VOO_TOP_N_LIVE holdings (by weight) also get a live price quote,
    since fetching real-time data for ~500 tickers on every request isn't practical.
    """
    holdings = load_voo_holdings()

    result = []
    for row in holdings:
        rank = int(row["rank"])
        entry = {
            "rank": rank,
            "symbol": row["symbol"],
            "name": row["name"],
            "sector": row["sector"],
            "weight_percent": float(row["weight_percent"]),
            "price": None,
            "change": None,
            "pct_change": None,
        }

        if rank <= VOO_TOP_N_LIVE:
            quote = get_live_price(row["yahoo_symbol"])
            if quote:
                entry.update(quote)

        result.append(entry)

    return {
        "top_n_live": VOO_TOP_N_LIVE,
        "total_holdings": len(result),
        "holdings": result,
    }


# Actual cash on hand, in each currency. Total portfolio value is derived from these
# plus FX_RATE_USD_CAD below, rather than a fixed CAD figure, since the investor holds
# both currencies directly.
CASH_CAD = 1_000_000
CASH_USD = 2_000_000
FX_RATE_USD_CAD = 1.39  # planning rate as specified, not a live quote

# Illustrative diversified portfolio: 62% equity / 30% fixed income / 6% real assets /
# 2% cash, sized off CASH_CAD + CASH_USD above. US equity sleeve is two cap-weighted
# funds (VTI + VOO) plus a dedicated healthcare tilt — user explicitly chose this over
# pairing VTI with an equal-weight fund (RSP), accepting the resulting tilt toward
# mega-cap/Tech concentration for lower fees and recent performance. fund_currency is
# the currency the ETF itself trades in — chosen, wherever a real equivalent exists, to
# match what's actually funded from CAD vs USD cash so as little as possible needs FX
# conversion (e.g. FLCA/VEA/VWO are USD-listed but hold Canadian/developed/EM stocks,
# same as their CAD-listed cousins;
# genuinely CAD-only instruments like Government of Canada bonds have no USD listing,
# so those stay funded from the CAD pool). sector_weights are approximate GICS
# breakdowns for the underlying index (illustrative, not live data) and are only
# present on equity holdings — they drive the blended equity-sector chart.
PORTFOLIO_HOLDINGS = [
    {
        "ticker": "VTI", "yahoo_symbol": "VTI", "name": "Vanguard Total Stock Market ETF",
        "sleeve": "Equity", "region": "US", "primary_sector": "Diversified (Multi-Sector)", "fund_currency": "USD",
        "weight_pct": 15.5, "expected_return_pct": 8.0,
        "sector_weights": {"Information Technology": 30, "Financials": 13, "Health Care": 11,
                            "Consumer Discretionary": 10, "Communication Services": 9, "Industrials": 9,
                            "Consumer Staples": 6, "Energy": 4, "Utilities": 3, "Real Estate": 3, "Materials": 2},
    },
    {
        "ticker": "VOO", "yahoo_symbol": "VOO", "name": "Vanguard S&P 500 ETF",
        "sleeve": "Equity", "region": "US", "primary_sector": "Diversified (Multi-Sector)", "fund_currency": "USD",
        "weight_pct": 6.2, "expected_return_pct": 8.0,
        "sector_weights": {"Information Technology": 30, "Financials": 13, "Health Care": 11,
                            "Consumer Discretionary": 10, "Communication Services": 9, "Industrials": 9,
                            "Consumer Staples": 6, "Energy": 4, "Utilities": 3, "Real Estate": 3, "Materials": 2},
    },
    {
        "ticker": "FLCA", "yahoo_symbol": "FLCA", "name": "Franklin FTSE Canada ETF",
        "sleeve": "Equity", "region": "Canada", "primary_sector": "Diversified (Multi-Sector)", "fund_currency": "USD",
        "weight_pct": 9.3, "expected_return_pct": 7.0,
        "sector_weights": {"Financials": 30, "Energy": 17, "Industrials": 13, "Materials": 12,
                            "Information Technology": 8, "Consumer Discretionary": 4, "Utilities": 4,
                            "Communication Services": 4, "Consumer Staples": 4, "Real Estate": 2, "Health Care": 2},
    },
    {
        "ticker": "VEA", "yahoo_symbol": "VEA", "name": "Vanguard FTSE Developed Markets ETF",
        "sleeve": "Equity", "region": "International Developed", "primary_sector": "Diversified (Multi-Sector)", "fund_currency": "USD",
        "weight_pct": 15.5, "expected_return_pct": 7.5,
        "sector_weights": {"Financials": 20, "Industrials": 17, "Health Care": 13,
                            "Consumer Discretionary": 11, "Consumer Staples": 9, "Information Technology": 9,
                            "Materials": 7, "Communication Services": 5, "Energy": 4, "Utilities": 3, "Real Estate": 2},
    },
    {
        "ticker": "VWO", "yahoo_symbol": "VWO", "name": "Vanguard FTSE Emerging Markets ETF",
        "sleeve": "Equity", "region": "Emerging Markets", "primary_sector": "Diversified (Multi-Sector)", "fund_currency": "USD",
        "weight_pct": 11.16, "expected_return_pct": 8.5,
        "sector_weights": {"Financials": 24, "Information Technology": 22, "Consumer Discretionary": 13,
                            "Communication Services": 9, "Materials": 7, "Industrials": 6, "Energy": 5,
                            "Consumer Staples": 5, "Health Care": 4, "Utilities": 3, "Real Estate": 2},
    },
    {
        "ticker": "FHLC", "yahoo_symbol": "FHLC", "name": "Fidelity MSCI Health Care Index ETF",
        "sleeve": "Equity", "region": "Global", "primary_sector": "Health Care", "fund_currency": "USD",
        "weight_pct": 4.34, "expected_return_pct": 7.5,
        "sector_weights": {"Health Care": 100},
    },
    {
        "ticker": "ZAG.TO", "yahoo_symbol": "ZAG.TO", "name": "BMO Aggregate Bond Index ETF",
        "sleeve": "Fixed Income", "region": "Canada", "primary_sector": "Fixed Income", "fund_currency": "CAD",
        "weight_pct": 10.5, "expected_return_pct": 4.0, "sector_weights": None,
    },
    {
        "ticker": "XSB.TO", "yahoo_symbol": "XSB.TO", "name": "iShares Core Canadian Short Term Bond Index ETF",
        "sleeve": "Fixed Income", "region": "Canada", "primary_sector": "Fixed Income", "fund_currency": "CAD",
        "weight_pct": 4.5, "expected_return_pct": 3.5, "sector_weights": None,
    },
    {
        "ticker": "XRB.TO", "yahoo_symbol": "XRB.TO", "name": "iShares Canadian Real Return Bond Index ETF",
        "sleeve": "Fixed Income", "region": "Canada", "primary_sector": "Fixed Income", "fund_currency": "CAD",
        "weight_pct": 3.0, "expected_return_pct": 3.5, "sector_weights": None,
    },
    {
        "ticker": "BNDX", "yahoo_symbol": "BNDX", "name": "Vanguard Total International Bond ETF (USD-Hedged)",
        "sleeve": "Fixed Income", "region": "Global", "primary_sector": "Fixed Income", "fund_currency": "USD",
        "weight_pct": 4.5, "expected_return_pct": 3.5, "sector_weights": None,
    },
    {
        "ticker": "VCIT", "yahoo_symbol": "VCIT", "name": "Vanguard Intermediate-Term Corporate Bond ETF",
        "sleeve": "Fixed Income", "region": "US", "primary_sector": "Fixed Income", "fund_currency": "USD",
        "weight_pct": 4.5, "expected_return_pct": 4.5, "sector_weights": None,
    },
    {
        "ticker": "USHY", "yahoo_symbol": "USHY", "name": "iShares Broad USD High Yield Corporate Bond ETF",
        "sleeve": "Fixed Income", "region": "US", "primary_sector": "Fixed Income", "fund_currency": "USD",
        "weight_pct": 3.0, "expected_return_pct": 6.0, "sector_weights": None,
    },
    {
        "ticker": "XRE.TO", "yahoo_symbol": "XRE.TO", "name": "iShares S&P/TSX Capped REIT Index ETF",
        "sleeve": "Real Assets", "region": "Canada", "primary_sector": "Real Estate", "fund_currency": "CAD",
        "weight_pct": 3.0, "expected_return_pct": 6.5, "sector_weights": None,
    },
    {
        "ticker": "REET", "yahoo_symbol": "REET", "name": "iShares Global REIT ETF",
        "sleeve": "Real Assets", "region": "Global", "primary_sector": "Real Estate", "fund_currency": "USD",
        "weight_pct": 3.0, "expected_return_pct": 6.5, "sector_weights": None,
    },
    {
        "ticker": "CASH.TO", "yahoo_symbol": "CASH.TO", "name": "Horizons High Interest Savings ETF",
        "sleeve": "Cash", "region": "Canada", "primary_sector": "Cash & Equivalents", "fund_currency": "CAD",
        "weight_pct": 1.0, "expected_return_pct": 3.0, "sector_weights": None,
    },
    {
        "ticker": "SGOV", "yahoo_symbol": "SGOV", "name": "iShares 0-3 Month Treasury Bond ETF",
        "sleeve": "Cash", "region": "US", "primary_sector": "Cash & Equivalents", "fund_currency": "USD",
        "weight_pct": 1.0, "expected_return_pct": 3.0, "sector_weights": None,
    },
]


def compute_sleeve_breakdown(holdings, total_value_cad):
    weight, amount = {}, {}
    for h in holdings:
        weight[h["sleeve"]] = weight.get(h["sleeve"], 0) + h["weight_pct"]
        amount[h["sleeve"]] = amount.get(h["sleeve"], 0) + h["weight_pct"] / 100 * total_value_cad
    return weight, amount


def compute_region_breakdown(holdings):
    totals = {}
    for h in holdings:
        totals[h["region"]] = totals.get(h["region"], 0) + h["weight_pct"]
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def compute_currency_breakdown(holdings):
    totals = {}
    for h in holdings:
        totals[h["fund_currency"]] = totals.get(h["fund_currency"], 0) + h["weight_pct"]
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def compute_equity_sector_breakdown(holdings):
    """Blended GICS sector exposure as a % of the equity sleeve only (bonds/cash/REITs have no GICS sector)."""
    equity = [h for h in holdings if h["sleeve"] == "Equity"]
    equity_total = sum(h["weight_pct"] for h in equity)
    totals = {}
    for h in equity:
        fraction_of_equity = h["weight_pct"] / equity_total
        for sector, pct in h["sector_weights"].items():
            totals[sector] = totals.get(sector, 0) + fraction_of_equity * pct
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


@app.get("/api/portfolio")
def get_portfolio():
    """
    Returns the proposed diversified portfolio sized off actual CAD/USD cash on hand:
    every holding (with a live quote where Yahoo Finance has one) plus blended
    breakdowns by asset type, geography, currency, and equity sector, and how much of
    each cash pool needs to be FX-converted to fund the CAD-listed vs USD-listed legs.
    """
    total_value_cad = CASH_CAD + CASH_USD * FX_RATE_USD_CAD

    holdings = []
    for h in PORTFOLIO_HOLDINGS:
        entry = {k: v for k, v in h.items() if k != "sector_weights"}
        entry["amount_cad"] = round(h["weight_pct"] / 100 * total_value_cad, 2)

        quote = get_live_price(h["yahoo_symbol"])
        entry["price"] = quote["price"] if quote else None
        entry["change"] = quote["change"] if quote else None
        entry["pct_change"] = quote["pct_change"] if quote else None

        perf = get_performance_metrics(h["yahoo_symbol"])
        entry["ytd_pct"] = perf["ytd_pct"] if perf else None
        entry["one_year_pct"] = perf["one_year_pct"] if perf else None
        entry["three_year_pct"] = perf["three_year_pct"] if perf else None

        holdings.append(entry)

    sleeve_weight, sleeve_amount = compute_sleeve_breakdown(PORTFOLIO_HOLDINGS, total_value_cad)
    blended_return = sum(h["weight_pct"] / 100 * h["expected_return_pct"] for h in PORTFOLIO_HOLDINGS)

    usd_target_cad = sum(h["weight_pct"] for h in PORTFOLIO_HOLDINGS if h["fund_currency"] == "USD") / 100 * total_value_cad
    cad_target_cad = total_value_cad - usd_target_cad
    usd_cash_cad_equiv = CASH_USD * FX_RATE_USD_CAD
    net_conversion_cad = usd_cash_cad_equiv - usd_target_cad  # +: convert USD->CAD, -: convert CAD->USD

    return {
        "total_value_cad": round(total_value_cad, 2),
        "cash_cad": CASH_CAD,
        "cash_usd": CASH_USD,
        "fx_rate_usd_cad": FX_RATE_USD_CAD,
        "target_return_pct": 10.0,
        "blended_expected_return_pct": round(blended_return, 2),
        "sleeve_breakdown": {"weight_pct": sleeve_weight, "amount_cad": sleeve_amount},
        "region_breakdown": compute_region_breakdown(PORTFOLIO_HOLDINGS),
        "currency_breakdown": compute_currency_breakdown(PORTFOLIO_HOLDINGS),
        "sector_breakdown": {k: round(v, 2) for k, v in compute_equity_sector_breakdown(PORTFOLIO_HOLDINGS).items()},
        "funding_plan": {
            "usd_target_usd": round(usd_target_cad / FX_RATE_USD_CAD, 2),
            "cad_target_cad": round(cad_target_cad, 2),
            "net_conversion_cad": round(net_conversion_cad, 2),
        },
        "holdings": holdings,
    }


# Comparison vs 4 real managed accounts (TUS, TCA, RBHN, RD), each supplied by the user
# as Apple Numbers exports and parsed offline (numbers-parser + yfinance sector/country
# lookups + web-sourced MERs for funds yfinance doesn't cover). Every figure below is
# rescaled to the SAME $3.78M CAD capital base as Option A's actual cash, using each
# account's CURRENT % allocation and an all-in fee (advisor fee where disclosed: TUS/TCA
# 0.8%, RBHN already embeds 1.1%+MER per holding, RD 1.45%, all + each holding's own MER).
# Forward 3yr return = blended asset-class capital-market assumption (Equity 7.8%, Fixed
# Income 4.0%, Real Assets/Commodities 6.0%, Cash 3.0%, Alternatives 8.0%) minus the
# account's own weighted fee — illustrative, not a guarantee, same spirit as Option A's
# own forward assumptions.
COMPARISON_DATA = {
    "TUS": {
        "label": "TUS", "actual_total_cad": 597970,
        "asset_class_breakdown": {"Equity": 46.78, "Cash": 34.87, "Fixed Income": 18.35},
        "region_breakdown": {"US": 99.55, "International Developed": 0.45},
        "sector_breakdown": {"Information Technology": 36.99, "Industrials": 12.4, "Financials": 12.33,
                              "Communication Services": 10.26, "Consumer Discretionary": 8.97, "Health Care": 7.72,
                              "Consumer Staples": 3.87, "Energy": 3.86, "Utilities": 2.51, "Materials": 1.09},
        "weighted_fee_pct": 0.872, "gross_return_pct": 5.43, "net_return_pct": 4.56,
        "trajectory_cad": [3780000, 3952247, 4132343, 4320646],
    },
    "TCA": {
        "label": "TCA", "actual_total_cad": 287169,
        "asset_class_breakdown": {"Equity": 100.0},
        "region_breakdown": {"Canada": 47.28, "US": 29.39, "International Developed": 22.19, "Emerging Markets": 1.14},
        "sector_breakdown": {"Financials (Preferred)": 25.37, "Financials": 23.58, "Information Technology": 12.0,
                              "Industrials": 11.01, "Energy": 8.18, "Consumer Discretionary": 4.39, "Health Care": 4.33,
                              "Communication Services": 3.34, "Consumer Staples": 3.08, "Utilities": 2.11,
                              "Materials": 1.9, "Real Estate": 0.71},
        "weighted_fee_pct": 0.955, "gross_return_pct": 7.8, "net_return_pct": 6.85,
        "trajectory_cad": [3780000, 4038750, 4315213, 4610600],
    },
    "RBHN": {
        "label": "RBHN", "actual_total_cad": 1017462,
        "asset_class_breakdown": {"Equity": 52.6, "Fixed Income": 36.55, "Alternatives": 9.86, "Cash": 0.99},
        "region_breakdown": {"Global": 37.04, "Canada": 27.26, "US": 22.43, "International Developed": 8.73,
                              "Emerging Markets": 4.55},
        "sector_breakdown": {"Diversified (Multi-Sector)": 100.0},
        "weighted_fee_pct": 1.227, "gross_return_pct": 6.38, "net_return_pct": 5.16,
        "trajectory_cad": [3780000, 3974924, 4179899, 4395444],
    },
    "RD": {
        "label": "RD", "actual_total_cad": 719029,
        "asset_class_breakdown": {"Equity": 51.46, "Fixed Income": 31.69, "Alternatives": 11.35,
                                   "Commodities": 5.15, "Cash": 0.34},
        "region_breakdown": {"US": 72.3, "Global": 23.02, "International Developed": 3.19, "Emerging Markets": 1.49},
        "sector_breakdown": {"Information Technology": 31.26, "Financials": 16.65, "Industrials": 13.18,
                              "Consumer Discretionary": 9.6, "Health Care": 9.05, "Communication Services": 7.04,
                              "Consumer Staples": 4.29, "Materials": 3.13, "Utilities": 3.06, "Energy": 2.74},
        "weighted_fee_pct": 1.789, "gross_return_pct": 6.51, "net_return_pct": 4.72,
        "trajectory_cad": [3780000, 3958409, 4145238, 4340885],
    },
    "B_COMBINED": {
        "label": "Option B (TUS+TCA+RBHN+RD combined)", "actual_total_cad": 2621631,
        "asset_class_breakdown": {"Equity": 56.15, "Fixed Income": 27.06, "Cash": 8.43, "Alternatives": 6.94,
                                   "Commodities": 1.41},
        "region_breakdown": {"US": 54.46, "Global": 20.69, "Canada": 15.76, "International Developed": 6.79,
                              "Emerging Markets": 2.3},
        "sector_breakdown": {"Diversified (Multi-Sector)": 36.35, "Information Technology": 17.23,
                              "Financials": 11.13, "Industrials": 7.82, "Consumer Discretionary": 4.97,
                              "Financials (Preferred)": 4.95, "Health Care": 4.59, "Communication Services": 4.37,
                              "Energy": 3.02, "Consumer Staples": 2.41, "Utilities": 1.66, "Materials": 1.37,
                              "Real Estate": 0.14},
        "weighted_fee_pct": 1.27, "gross_return_pct": 6.35, "net_return_pct": 5.08,
        "trajectory_cad": [3780000, 3972199, 4174170, 4386410],
    },
}


@app.get("/api/compare")
def get_compare():
    """Option A (this dashboard's portfolio) vs each of the 4 real accounts individually, and vs their combined total (Option B) — all rescaled to the same $3.78M CAD capital."""
    option_a = get_portfolio()
    total_value_cad = option_a["total_value_cad"]
    option_a_entry = {
        "label": "Option A (this portfolio)", "actual_total_cad": round(total_value_cad),
        "asset_class_breakdown": option_a["sleeve_breakdown"]["weight_pct"],
        "region_breakdown": option_a["region_breakdown"],
        "sector_breakdown": option_a["sector_breakdown"],
        "weighted_fee_pct": 0.086, "gross_return_pct": round(option_a["blended_expected_return_pct"] + 0.086, 2),
        "net_return_pct": option_a["blended_expected_return_pct"],
        "trajectory_cad": [round(total_value_cad * (1 + option_a["blended_expected_return_pct"] / 100) ** y) for y in range(4)],
    }
    return {"A": option_a_entry, **COMPARISON_DATA}


@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/voo", response_class=HTMLResponse)
def read_voo_page():
    with open("voo.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/portfolio", response_class=HTMLResponse)
def read_portfolio_page():
    with open("portfolio.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/compare", response_class=HTMLResponse)
def read_compare_page():
    with open("compare.html", "r", encoding="utf-8") as f:
        return f.read()