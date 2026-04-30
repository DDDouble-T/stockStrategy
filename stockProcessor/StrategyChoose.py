import pandas as pd
import tushare as ts
import os
from copy import deepcopy
from datetime import datetime, timedelta
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from module.basic import basic_api
from module.config import tushare_config
from constants import data_path, score_result_path
import strategy_choose_config

# ======================
# 参数区
# ======================
def load_strategy_runtime_config():
    preset_name = strategy_choose_config.ACTIVE_STRATEGY
    preset = strategy_choose_config.STRATEGY_PRESETS.get(preset_name)
    if preset is None:
        raise ValueError(f"未找到策略配置: {preset_name}")

    config = deepcopy(strategy_choose_config.DEFAULT_CONFIG)
    preset_conditions = preset.get("conditions", {})
    config["conditions"].update(preset_conditions)
    for key, value in preset.items():
        if key == "conditions":
            continue
        config[key] = value

    config["strategy_name"] = preset_name
    return config


RUNTIME_CONFIG = load_strategy_runtime_config()
END_DATE = None  # None 表示自动取最近一个已结束的交易日
MARKET_CLOSE_HOUR = 15
DATA_LOOKBACK_TRADE_DAYS = RUNTIME_CONFIG["data_lookback_trade_days"]
SIGNAL_DAYS = RUNTIME_CONFIG["signal_days"]
MAX_FORWARD_DAYS = RUNTIME_CONFIG["max_forward_days"]
VOL_MA_DAYS = RUNTIME_CONFIG["vol_ma_days"]
RSI_PERIOD = RUNTIME_CONFIG["rsi_period"]
DAILY_CACHE_CSV = data_path("strategy_daily_cache.csv")
DIVIDEND_CACHE_CSV = data_path("strategy_dividend_cache.csv")
BASIC_CACHE_CSV = data_path("strategy_basic_cache.csv")
SHAREHOLDER_CACHE_CSV = data_path("strategy_shareholder_cache.csv")
MONEYFLOW_CACHE_CSV = data_path("strategy_moneyflow_cache.csv")
PREV_YEAR_MIN_CASH_DIV_TAX = RUNTIME_CONFIG["prev_year_min_cash_div_tax"]
RESULT_XLSX = score_result_path("strategy_choose_result.xlsx")
CONDITION_FLAGS = RUNTIME_CONFIG["conditions"]
RSI_MAX = RUNTIME_CONFIG["rsi_max"]
NEAR_MA_THRESHOLD = RUNTIME_CONFIG["near_ma_threshold"]
RECENT_HIGH_LOOKBACK_DAYS = RUNTIME_CONFIG["recent_high_lookback_days"]
MIN_EPS = RUNTIME_CONFIG["min_eps"]
MIN_VOLUME_RATIO = RUNTIME_CONFIG["min_volume_ratio"]
MIN_EXTERNAL_INTERNAL_RATIO = RUNTIME_CONFIG["min_external_internal_ratio"]
MIN_TURNOVER_RATE = RUNTIME_CONFIG["min_turnover_rate"]
MAX_TURNOVER_RATE = RUNTIME_CONFIG["max_turnover_rate"]
MAX_PE = RUNTIME_CONFIG["max_pe"]

CONDITION_NAMES = {
    "trend_above_ma20": "股价在20日线之上",
    "bullish_ma_alignment": "5日线 > 10日线 > 20日线",
    "volume_rule": "上涨放量或回调缩量",
    "position_rule": "回踩10/20日线缩量，或突破前高放量",
    "macd_golden_cross": "MACD金叉",
    "rsi_not_overheated": "RSI不过热",
    "volume_ratio_high": "量比达标",
    "external_internal_ratio_high": "外盘/内盘达标",
    "turnover_rate_range": "换手率在设定区间",
    "pe_reasonable": "市盈率合理",
    "social_security_holder": "股东成分包含全国社保基金",
    "prev_year_high_dividend": "上一年度现金分红较高",
    "main_money_inflow_2days": "主力资金连续流入2天",
}

# ======================
# 工具函数
# ======================
def pro_api():
    return ts.pro_api(tushare_config.TuShareConst.TOKEN)


def fetch_with_retry(fetch_func, label):
    try:
        return fetch_func()
    except Exception as e:
        raise RuntimeError(f"{label} 下载失败，已停止本次任务，避免使用不完整数据：{e}") from e


def get_trade_dates(end_date, count=80):
    pro = pro_api()
    calendar_lookback_days = max(180, count * 2 + 30)
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=(datetime.strptime(end_date, "%Y%m%d") - timedelta(days=calendar_lookback_days)).strftime("%Y%m%d"),
        end_date=end_date,
        is_open="1"
    )
    cal = cal.sort_values("cal_date")
    return cal["cal_date"].tolist()[-count:]


def get_latest_completed_trade_date(now=None):
    if now is None:
        now = datetime.now()

    today = now.strftime("%Y%m%d")
    pro = pro_api()
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=(now - timedelta(days=30)).strftime("%Y%m%d"),
        end_date=today,
        is_open="1"
    )
    cal = cal.sort_values("cal_date")
    trade_dates = cal["cal_date"].tolist()
    if not trade_dates:
        raise ValueError("未获取到可用交易日，请检查交易日历接口")

    if trade_dates[-1] != today:
        return trade_dates[-1]

    if now.hour >= MARKET_CLOSE_HOUR:
        return today

    if len(trade_dates) < 2:
        raise ValueError("当前交易日未结束，且没有可用的上一交易日")
    return trade_dates[-2]


def calc_rsi(close, period=6):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd


def get_moneyflow(ts_code, start_date, end_date):
    try:
        pro = pro_api()
        mf = pro.moneyflow(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )
        if mf.empty:
            return None

        mf = mf.sort_values("trade_date")
        return mf
    except Exception:
        return None


def is_main_money_inflow_2days(ts_code, trade_date, trade_dates):
    """
    判断主力资金连续流入2天。
    这里用 buy_lg_amount + buy_elg_amount - sell_lg_amount - sell_elg_amount 作为主力净流入。
    """
    idx = trade_dates.index(trade_date)
    if idx < 1:
        return False

    start_date = trade_dates[idx - 1]
    end_date = trade_date

    mf = get_moneyflow(ts_code, start_date, end_date)
    if mf is None or len(mf) < 2:
        return False

    mf["main_net"] = (
        mf["buy_lg_amount"].fillna(0)
        + mf["buy_elg_amount"].fillna(0)
        - mf["sell_lg_amount"].fillna(0)
        - mf["sell_elg_amount"].fillna(0)
    )

    last2 = mf.tail(2)
    return (last2["main_net"] > 0).all()


def add_daily_indicators(df):
    if df.empty:
        return df

    df = df.sort_values("trade_date").reset_index(drop=True)

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["vol_ma5"] = df["vol"].rolling(VOL_MA_DAYS).mean()

    df["rsi"] = calc_rsi(df["close"], RSI_PERIOD)
    df["dif"], df["dea"], df["macd"] = calc_macd(df["close"])

    df["macd_gold"] = (df["dif"] > df["dea"]) & (df["dif"].shift(1) <= df["dea"].shift(1))

    return df


def load_daily_cache():
    if not os.path.exists(DAILY_CACHE_CSV):
        return pd.DataFrame()

    df = pd.read_csv(DAILY_CACHE_CSV, dtype={"ts_code": str, "trade_date": str})
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].astype(str)
    return df


def save_daily_cache(df):
    os.makedirs(os.path.dirname(DAILY_CACHE_CSV), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    df = df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    df.to_csv(DAILY_CACHE_CSV, index=False, encoding="utf-8-sig")


def fetch_daily_by_trade_date(trade_date):
    pro = pro_api()
    return pro.daily(trade_date=trade_date)


def load_moneyflow_cache():
    if not os.path.exists(MONEYFLOW_CACHE_CSV):
        return pd.DataFrame()
    df = pd.read_csv(MONEYFLOW_CACHE_CSV, dtype={"ts_code": str, "trade_date": str})
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].astype(str)
    return df


def save_moneyflow_cache(df):
    os.makedirs(os.path.dirname(MONEYFLOW_CACHE_CSV), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    df = df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    df.to_csv(MONEYFLOW_CACHE_CSV, index=False, encoding="utf-8-sig")


def fetch_moneyflow_by_trade_date(trade_date):
    pro = pro_api()
    return pro.moneyflow(trade_date=trade_date)


def load_all_moneyflow(trade_dates):
    cache_df = load_moneyflow_cache()
    cached_dates = set(cache_df["trade_date"].astype(str)) if not cache_df.empty and "trade_date" in cache_df.columns else set()

    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
    if missing_dates:
        print(f"资金流缓存缺失 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}")
    else:
        print(f"资金流缓存已命中最近 {len(trade_dates)} 个交易日，无需重新拉取")

    fetched = []
    for trade_date in missing_dates:
        df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_moneyflow_by_trade_date(trade_date),
            f"moneyflow {trade_date}"
        )
        if df.empty:
            raise RuntimeError(f"moneyflow {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
        df["trade_date"] = df["trade_date"].astype(str)
        fetched.append(df)
        print(f"已补齐资金流数据：{trade_date}")

    if fetched:
        cache_df = pd.concat([cache_df] + fetched, ignore_index=True)
        save_moneyflow_cache(cache_df)

    columns = ["ts_code", "trade_date", "external_internal_ratio", "main_net", "main_inflow_2days"]
    if cache_df.empty:
        return pd.DataFrame(columns=columns)

    buy_vol_columns = ["buy_sm_vol", "buy_md_vol", "buy_lg_vol", "buy_elg_vol"]
    sell_vol_columns = ["sell_sm_vol", "sell_md_vol", "sell_lg_vol", "sell_elg_vol"]
    money_amount_columns = ["buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"]

    for col in buy_vol_columns + sell_vol_columns + money_amount_columns:
        if col not in cache_df.columns:
            cache_df[col] = 0
        cache_df[col] = pd.to_numeric(cache_df[col], errors="coerce").fillna(0)

    cache_df["external_vol"] = cache_df[buy_vol_columns].sum(axis=1)
    cache_df["internal_vol"] = cache_df[sell_vol_columns].sum(axis=1)
    cache_df["external_internal_ratio"] = (
        cache_df["external_vol"] / cache_df["internal_vol"].where(cache_df["internal_vol"] > 0)
    )
    cache_df["main_net"] = (
        cache_df["buy_lg_amount"]
        + cache_df["buy_elg_amount"]
        - cache_df["sell_lg_amount"]
        - cache_df["sell_elg_amount"]
    )

    cache_df = cache_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    cache_df["main_inflow"] = cache_df["main_net"] > 0
    cache_df["prev_main_inflow"] = cache_df.groupby("ts_code")["main_inflow"].shift(1).eq(True)
    cache_df["main_inflow_2days"] = cache_df["main_inflow"] & cache_df["prev_main_inflow"]

    trade_date_set = set(trade_dates)
    return cache_df[cache_df["trade_date"].isin(trade_date_set)][columns].copy()


def load_basic_cache():
    if not os.path.exists(BASIC_CACHE_CSV):
        return pd.DataFrame()

    df = pd.read_csv(BASIC_CACHE_CSV, dtype={"ts_code": str, "trade_date": str})
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].astype(str)
    for col in ["eps", "volume_ratio", "turnover_rate", "pe"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def save_basic_cache(df):
    os.makedirs(os.path.dirname(BASIC_CACHE_CSV), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    df = df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    df.to_csv(BASIC_CACHE_CSV, index=False, encoding="utf-8-sig")


def fetch_daily_basic_by_trade_date(trade_date):
    pro = pro_api()
    return pro.daily_basic(
        trade_date=trade_date,
        fields="ts_code,trade_date,pe,pe_ttm,volume_ratio,turnover_rate"
    )


def fetch_bak_basic_by_trade_date(trade_date):
    pro = pro_api()
    return pro.bak_basic(trade_date=trade_date)


def merge_basic_frames(daily_basic_df, bak_basic_df, trade_date):
    if daily_basic_df is None or daily_basic_df.empty:
        daily_basic_df = pd.DataFrame(columns=["ts_code", "trade_date", "pe", "pe_ttm", "volume_ratio", "turnover_rate"])
    if bak_basic_df is None or bak_basic_df.empty:
        bak_basic_df = pd.DataFrame(columns=["ts_code", "trade_date", "eps"])

    daily_basic_df = daily_basic_df.copy()
    bak_basic_df = bak_basic_df.copy()

    if "trade_date" not in daily_basic_df.columns:
        daily_basic_df["trade_date"] = trade_date
    if "trade_date" not in bak_basic_df.columns:
        bak_basic_df["trade_date"] = trade_date

    merged = pd.merge(
        daily_basic_df,
        bak_basic_df,
        on=["ts_code", "trade_date"],
        how="outer",
        suffixes=("", "_bak")
    )

    if "pe_ttm" in merged.columns:
        merged["pe"] = merged["pe_ttm"].where(merged["pe_ttm"].notna(), merged.get("pe"))

    if "eps" not in merged.columns:
        merged["eps"] = pd.NA

    if "close" in merged.columns:
        pass

    columns = ["ts_code", "trade_date", "eps", "volume_ratio", "turnover_rate", "pe"]
    for col in columns:
        if col not in merged.columns:
            merged[col] = pd.NA

    return merged[columns].copy()


def load_all_basic(ts_codes, trade_dates, daily_df=None):
    cache_df = load_basic_cache()
    required_columns = {"ts_code", "trade_date", "eps", "volume_ratio", "turnover_rate", "pe"}
    cache_has_required_columns = required_columns.issubset(set(cache_df.columns))
    cached_dates = (
        set(cache_df["trade_date"].astype(str))
        if cache_has_required_columns and not cache_df.empty and "trade_date" in cache_df.columns
        else set()
    )
    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
    if missing_dates:
        print(f"基础面缓存缺失 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}")
    else:
        print(f"基础面缓存已命中最近 {len(trade_dates)} 个交易日，无需重新拉取")

    fetched = []
    for trade_date in missing_dates:
        daily_basic_df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_daily_basic_by_trade_date(trade_date),
            f"daily_basic {trade_date}"
        )
        if daily_basic_df.empty:
            raise RuntimeError(f"daily_basic {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
        bak_basic_df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_bak_basic_by_trade_date(trade_date),
            f"bak_basic {trade_date}"
        )
        if bak_basic_df.empty:
            raise RuntimeError(f"bak_basic {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")

        merged = merge_basic_frames(daily_basic_df, bak_basic_df, trade_date)
        if not merged.empty:
            fetched.append(merged)
            print(f"已补齐基础面数据：{trade_date}")

    if fetched:
        cache_df = pd.concat([cache_df] + fetched, ignore_index=True)
        save_basic_cache(cache_df)

    if cache_df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "eps", "volume_ratio", "turnover_rate", "pe"])

    ts_code_set = set(ts_codes)
    trade_date_set = set(trade_dates)
    result = cache_df[
        cache_df["ts_code"].isin(ts_code_set)
        & cache_df["trade_date"].isin(trade_date_set)
    ].copy()
    print(
        f"本次使用基础面缓存：{len(result)} 行，"
        f"{result['trade_date'].nunique() if not result.empty else 0} 个交易日，"
        f"{result['ts_code'].nunique() if not result.empty else 0} 只股票"
    )
    return result


def load_shareholder_cache():
    if not os.path.exists(SHAREHOLDER_CACHE_CSV):
        return pd.DataFrame(columns=["ts_code", "holder_flag", "holder_end_date"])

    return pd.read_csv(
        SHAREHOLDER_CACHE_CSV,
        dtype={"ts_code": str, "holder_flag": bool, "holder_end_date": str}
    )


def save_shareholder_cache(df):
    os.makedirs(os.path.dirname(SHAREHOLDER_CACHE_CSV), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code"], keep="last")
    df = df.sort_values(by=["ts_code"]).reset_index(drop=True)
    df.to_csv(SHAREHOLDER_CACHE_CSV, index=False, encoding="utf-8-sig")


def is_social_security_holder_name(holder_names):
    # 股东名称不是精确匹配，形如“xxx全国社保基金xxx”也应视为社保基金持仓。
    return holder_names.astype(str).str.contains("全国社保基金", regex=False, na=False).any()


def fetch_social_security_holder_flag(ts_code):
    pro = pro_api()
    sources = []
    for api_name in ["top10_floatholders", "top10_holders"]:
        try:
            df = getattr(pro, api_name)(ts_code=ts_code)
            if df is not None and not df.empty:
                df = df.copy()
                if "holder_name" not in df.columns:
                    continue
                if "end_date" in df.columns:
                    df["end_date"] = df["end_date"].astype(str)
                    latest_end_date = df["end_date"].max()
                    latest_df = df[df["end_date"] == latest_end_date]
                else:
                    latest_end_date = ""
                    latest_df = df
                holder_flag = is_social_security_holder_name(latest_df["holder_name"])
                sources.append((bool(holder_flag), latest_end_date))
        except Exception:
            continue

    if not sources:
        return False, ""

    for holder_flag, holder_end_date in sources:
        if holder_flag:
            return True, holder_end_date
    return False, sources[0][1]


def get_social_security_holder_flag(ts_code, shareholder_cache_ref):
    cache_df = shareholder_cache_ref["df"]
    cached = cache_df[cache_df["ts_code"] == ts_code]
    if not cached.empty:
        return bool(cached.iloc[-1]["holder_flag"])

    holder_flag, holder_end_date = fetch_social_security_holder_flag(ts_code)
    new_row = pd.DataFrame([{
        "ts_code": ts_code,
        "holder_flag": holder_flag,
        "holder_end_date": holder_end_date
    }])
    if cache_df.empty:
        shareholder_cache_ref["df"] = new_row
    else:
        shareholder_cache_ref["df"] = pd.concat([cache_df, new_row], ignore_index=True)
    shareholder_cache_ref["dirty"] = True
    return holder_flag


def load_dividend_cache():
    if not os.path.exists(DIVIDEND_CACHE_CSV):
        return pd.DataFrame(columns=["ts_code", "dividend_year", "cash_div_tax"])

    df = pd.read_csv(
        DIVIDEND_CACHE_CSV,
        dtype={"ts_code": str, "dividend_year": str}
    )
    if "cash_div_tax" in df.columns:
        df["cash_div_tax"] = pd.to_numeric(df["cash_div_tax"], errors="coerce").fillna(0)
    return df


def save_dividend_cache(df):
    os.makedirs(os.path.dirname(DIVIDEND_CACHE_CSV), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code", "dividend_year"], keep="last")
    df = df.sort_values(by=["dividend_year", "ts_code"]).reset_index(drop=True)
    df.to_csv(DIVIDEND_CACHE_CSV, index=False, encoding="utf-8-sig")


def fetch_prev_year_cash_div_tax(ts_code, dividend_year):
    pro = pro_api()
    df = pro.dividend(
        ts_code=ts_code,
        fields="ts_code,end_date,div_proc,cash_div,cash_div_tax,record_date,ex_date,pay_date"
    )
    if df.empty or "end_date" not in df.columns:
        return 0

    df["end_date"] = df["end_date"].astype(str)
    year_df = df[df["end_date"].str.startswith(str(dividend_year))]
    if year_df.empty:
        return 0

    cash_col = "cash_div_tax" if "cash_div_tax" in year_df.columns else "cash_div"
    return pd.to_numeric(year_df[cash_col], errors="coerce").fillna(0).sum()


def get_prev_year_cash_div_tax(ts_code, dividend_year, dividend_cache_ref):
    cache_df = dividend_cache_ref["df"]
    year = str(dividend_year)
    cached = cache_df[
        (cache_df["ts_code"] == ts_code)
        & (cache_df["dividend_year"].astype(str) == year)
    ]
    if not cached.empty:
        return cached.iloc[-1]["cash_div_tax"]

    cash_div_tax = fetch_prev_year_cash_div_tax(ts_code, dividend_year)
    new_row = pd.DataFrame([{
        "ts_code": ts_code,
        "dividend_year": year,
        "cash_div_tax": cash_div_tax
    }])
    if cache_df.empty:
        dividend_cache_ref["df"] = new_row
    else:
        dividend_cache_ref["df"] = pd.concat([cache_df, new_row], ignore_index=True)
    dividend_cache_ref["dirty"] = True
    return cash_div_tax


def is_prev_year_high_dividend(ts_code, dividend_year, dividend_cache_ref):
    cash_div_tax = get_prev_year_cash_div_tax(ts_code, dividend_year, dividend_cache_ref)
    return cash_div_tax >= PREV_YEAR_MIN_CASH_DIV_TAX


def load_all_daily(ts_codes, trade_dates):
    cache_df = load_daily_cache()
    cached_dates = set()
    if not cache_df.empty and "trade_date" in cache_df.columns:
        cached_dates = set(cache_df["trade_date"].astype(str))

    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
    if missing_dates:
        print(f"日线缓存缺失 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}")
    else:
        print(f"日线缓存已命中最近 {len(trade_dates)} 个交易日，无需重新拉取 daily")

    fetched_list = []
    for trade_date in missing_dates:
        df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_daily_by_trade_date(trade_date),
            f"daily {trade_date}"
        )
        if df.empty:
            raise RuntimeError(f"daily {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
        df["trade_date"] = df["trade_date"].astype(str)
        fetched_list.append(df)
        print(f"已补齐日线数据：{trade_date}")

    if fetched_list:
        cache_df = pd.concat([cache_df] + fetched_list, ignore_index=True)
        save_daily_cache(cache_df)

    if cache_df.empty:
        return pd.DataFrame()

    ts_code_set = set(ts_codes)
    trade_date_set = set(trade_dates)
    result = cache_df[
        cache_df["ts_code"].isin(ts_code_set)
        & cache_df["trade_date"].isin(trade_date_set)
    ].copy()
    print(
        f"本次使用日线缓存：{len(result)} 行，"
        f"{result['trade_date'].nunique() if not result.empty else 0} 个交易日，"
        f"{result['ts_code'].nunique() if not result.empty else 0} 只股票"
    )
    return result


def add_stat(stats, key):
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def check_signal(df, i, ts_code, trade_dates, dividend_year, dividend_cache_ref, shareholder_cache_ref, stats=None):
    row = df.iloc[i]
    prev = df.iloc[i - 1]

    if pd.isna(row["eps"]):
        add_stat(stats, "基础面数据不足")
        return False
    if row["eps"] < MIN_EPS:
        add_stat(stats, "每股盈利不达标")
        return False

    if CONDITION_FLAGS["trend_above_ma20"] and pd.isna(row["ma20"]):
        add_stat(stats, "指标数据不足")
        return False
    if CONDITION_FLAGS["bullish_ma_alignment"] and (
        pd.isna(row["ma5"]) or pd.isna(row["ma10"]) or pd.isna(row["ma20"])
    ):
        add_stat(stats, "指标数据不足")
        return False
    if CONDITION_FLAGS["volume_rule"] and pd.isna(row["vol_ma5"]):
        add_stat(stats, "指标数据不足")
        return False
    if CONDITION_FLAGS["position_rule"] and (
        pd.isna(row["ma10"]) or pd.isna(row["ma20"]) or pd.isna(row["vol_ma5"])
    ):
        add_stat(stats, "指标数据不足")
        return False
    if CONDITION_FLAGS["rsi_not_overheated"] and pd.isna(row["rsi"]):
        add_stat(stats, "指标数据不足")
        return False
    if CONDITION_FLAGS["volume_ratio_high"] and pd.isna(row["volume_ratio"]):
        add_stat(stats, "基础面数据不足")
        return False
    if CONDITION_FLAGS["turnover_rate_range"] and pd.isna(row["turnover_rate"]):
        add_stat(stats, "基础面数据不足")
        return False
    if CONDITION_FLAGS["pe_reasonable"] and pd.isna(row["pe"]):
        add_stat(stats, "基础面数据不足")
        return False
    if CONDITION_FLAGS["external_internal_ratio_high"] and pd.isna(row["external_internal_ratio"]):
        add_stat(stats, "资金流数据不足")
        return False
    if CONDITION_FLAGS["main_money_inflow_2days"] and pd.isna(row["main_inflow_2days"]):
        add_stat(stats, "资金流数据不足")
        return False

    # 1. 股价在20日线之上
    if CONDITION_FLAGS["trend_above_ma20"]:
        cond_trend_1 = row["close"] > row["ma20"]
        if not cond_trend_1:
            add_stat(stats, "股价未站上20日线")
            return False

    # 2. 5日 > 10日 > 20日
    if CONDITION_FLAGS["bullish_ma_alignment"]:
        cond_trend_2 = row["ma5"] > row["ma10"] > row["ma20"]
        if not cond_trend_2:
            add_stat(stats, "均线未多头排列")
            return False

    # 3. 上涨放量 or 回调缩量
    price_up = row["close"] > prev["close"]
    price_down = row["close"] < prev["close"]
    vol_up = row["vol"] > row["vol_ma5"]
    vol_down = row["vol"] < row["vol_ma5"]
    if CONDITION_FLAGS["volume_rule"]:
        cond_volume = (price_up and vol_up) or (price_down and vol_down)
        if not cond_volume:
            add_stat(stats, "量价条件不满足")
            return False

    # 4. 回踩10/20日线缩量，或突破前高/压力位放量
    if CONDITION_FLAGS["position_rule"]:
        near_ma10 = abs(row["close"] - row["ma10"]) / row["ma10"] <= NEAR_MA_THRESHOLD
        near_ma20 = abs(row["close"] - row["ma20"]) / row["ma20"] <= NEAR_MA_THRESHOLD
        pullback_shrink = (near_ma10 or near_ma20) and vol_down
        recent_high = df.iloc[max(0, i - RECENT_HIGH_LOOKBACK_DAYS):i]["high"].max()
        breakout = row["close"] > recent_high and vol_up
        cond_position = pullback_shrink or breakout
        if not cond_position:
            add_stat(stats, "位置条件不满足")
            return False

    # 5. MACD金叉
    if CONDITION_FLAGS["macd_golden_cross"]:
        cond_macd = row["macd_gold"]
        if not cond_macd:
            add_stat(stats, "MACD未金叉")
            return False

    # 6. RSI < 70
    if CONDITION_FLAGS["rsi_not_overheated"]:
        cond_rsi = row["rsi"] < RSI_MAX
        if not cond_rsi:
            add_stat(stats, "RSI过热")
            return False

    # 7. 换手量比达标
    if CONDITION_FLAGS["volume_ratio_high"]:
        if row["volume_ratio"] < MIN_VOLUME_RATIO:
            add_stat(stats, "换手量比不达标")
            return False

    # 8. 外盘 / 内盘达标
    if CONDITION_FLAGS["external_internal_ratio_high"]:
        if row["external_internal_ratio"] < MIN_EXTERNAL_INTERNAL_RATIO:
            add_stat(stats, "外盘内盘比不达标")
            return False

    # 9. 换手率在合理区间
    if CONDITION_FLAGS["turnover_rate_range"]:
        if row["turnover_rate"] < MIN_TURNOVER_RATE or row["turnover_rate"] > MAX_TURNOVER_RATE:
            add_stat(stats, "换手率不达标")
            return False

    # 10. 市盈率达标
    if CONDITION_FLAGS["pe_reasonable"]:
        if row["pe"] <= 0 or row["pe"] > MAX_PE:
            add_stat(stats, "市盈率不达标")
            return False

    # 11. 股东成分包含全国社保基金
    if CONDITION_FLAGS["social_security_holder"]:
        if not get_social_security_holder_flag(ts_code, shareholder_cache_ref):
            add_stat(stats, "股东成分不含全国社保基金")
            return False

    # 12. 上一年度现金分红较高
    if CONDITION_FLAGS["prev_year_high_dividend"]:
        if not is_prev_year_high_dividend(ts_code, dividend_year, dividend_cache_ref):
            add_stat(stats, "上一年度分红不高")
            return False

    # 13. 主力资金连续流入2天
    if CONDITION_FLAGS["main_money_inflow_2days"]:
        cond_money = bool(row["main_inflow_2days"])
        if not cond_money:
            add_stat(stats, "主力资金未连续流入")
            return False

    add_stat(stats, "筛选通过")
    return True


# ======================
# 主逻辑
# ======================
def load_stock_pool(ts_codes=None):
    stock_pool = basic_api.stock_basic()
    if RUNTIME_CONFIG["exclude_st_stocks"]:
        stock_pool = stock_pool[~stock_pool["name"].astype(str).str.contains("ST", na=False)]
    if ts_codes:
        stock_pool = stock_pool[stock_pool["ts_code"].isin(ts_codes)]
    return stock_pool


def choose_strategy(stock_pool=None, end_date=END_DATE):
    if stock_pool is None:
        stock_pool = load_stock_pool()

    if DATA_LOOKBACK_TRADE_DAYS < SIGNAL_DAYS:
        raise ValueError("DATA_LOOKBACK_TRADE_DAYS 不能小于 SIGNAL_DAYS")

    if end_date is None:
        end_date = get_latest_completed_trade_date()

    enabled_conditions = [key for key, value in CONDITION_FLAGS.items() if value]
    print(
        f"当前策略：{RUNTIME_CONFIG['strategy_name']}，"
        f"{RUNTIME_CONFIG.get('description', '')}"
    )
    print(f"启用条件：{', '.join(enabled_conditions)}")
    print(f"统计截止交易日：{end_date}")

    trade_dates = get_trade_dates(end_date, count=DATA_LOOKBACK_TRADE_DAYS)
    if not trade_dates:
        raise ValueError("未获取到可用交易日，请检查 end_date")

    signal_dates = trade_dates[-SIGNAL_DAYS:]
    print(
        f"交易日窗口：{trade_dates[0]} ~ {trade_dates[-1]}，"
        f"共 {len(trade_dates)} 个交易日；筛选日期：{', '.join(signal_dates)}"
    )

    stock_info = {
        row["ts_code"]: row["name"]
        for _, row in stock_pool.iterrows()
    }
    ts_codes = list(stock_info.keys())
    all_daily = load_all_daily(ts_codes, trade_dates)
    if all_daily.empty:
        return pd.DataFrame()
    all_basic = load_all_basic(ts_codes, trade_dates)
    if not all_basic.empty:
        all_daily = all_daily.merge(
            all_basic,
            on=["ts_code", "trade_date"],
            how="left"
        )
    for col in ["eps", "volume_ratio", "turnover_rate", "pe"]:
        if col not in all_daily.columns:
            all_daily[col] = pd.NA
    moneyflow_needed = (
        CONDITION_FLAGS["external_internal_ratio_high"]
        or CONDITION_FLAGS["main_money_inflow_2days"]
    )
    if moneyflow_needed:
        # 资金流条件依赖信号日前一日，用完整交易日窗口预计算可避免逐股逐日请求接口。
        all_moneyflow = load_all_moneyflow(trade_dates)
        if not all_moneyflow.empty:
            all_daily = all_daily.merge(
                all_moneyflow,
                on=["ts_code", "trade_date"],
                how="left"
            )
    for col in ["external_internal_ratio", "main_inflow_2days"]:
        if col not in all_daily.columns:
            all_daily[col] = pd.NA

    results = []
    stats = {}
    dividend_year = int(end_date[:4]) - 1
    dividend_cache_ref = {
        "df": load_dividend_cache() if CONDITION_FLAGS["prev_year_high_dividend"] else pd.DataFrame(),
        "dirty": False
    }
    shareholder_cache_ref = {
        "df": load_shareholder_cache() if CONDITION_FLAGS["social_security_holder"] else pd.DataFrame(),
        "dirty": False
    }
    if CONDITION_FLAGS["prev_year_high_dividend"]:
        print(
            f"分红筛选年度：{dividend_year}，"
            f"每10股税前现金分红下限：{PREV_YEAR_MIN_CASH_DIV_TAX}"
        )

    for ts_code, raw_df in all_daily.groupby("ts_code"):
        try:
            df = add_daily_indicators(raw_df)
            if df.empty or len(df) < 2:
                add_stat(stats, "日线数据不足")
                continue

            name = stock_info.get(ts_code, "")
            for signal_date in signal_dates:
                matched = df[df["trade_date"] == signal_date]
                if matched.empty:
                    add_stat(stats, "筛选日无日线")
                    continue

                i = matched.index[0]
                if i < 1:
                    add_stat(stats, "缺少前一交易日")
                    continue

                if not check_signal(
                    df,
                    i,
                    ts_code,
                    trade_dates,
                    dividend_year,
                    dividend_cache_ref,
                    shareholder_cache_ref,
                    stats
                ):
                    continue

                base_close = df.loc[i, "close"]
                base_high = df.loc[i, "high"]
                base_low = df.loc[i, "low"]

                results.append({
                    "ts_code": ts_code,
                    "name": name,
                    "signal_date": signal_date,
                    "base_close": base_close,
                    "base_high": base_high,
                    "base_low": base_low,
                    "forward_day": 0,
                    "future_date": signal_date,

                    "future_close": base_close,
                    "close_diff": 0,
                    "close_pct": 0,

                    "future_high": base_high,
                    "high_diff": 0,
                    "high_pct": 0,

                    "future_low": base_low,
                    "low_diff": 0,
                    "low_pct": 0,
                })

                available_forward_days = len(df) - i - 1
                forward_days = available_forward_days
                if MAX_FORWARD_DAYS is not None:
                    forward_days = min(available_forward_days, MAX_FORWARD_DAYS)

                for n in range(1, forward_days + 1):
                    if i + n >= len(df):
                        continue

                    future = df.loc[i + n]

                    results.append({
                        "ts_code": ts_code,
                        "name": name,
                        "signal_date": signal_date,
                        "base_close": base_close,
                        "base_high": base_high,
                        "base_low": base_low,
                        "forward_day": n,
                        "future_date": future["trade_date"],

                        "future_close": future["close"],
                        "close_diff": future["close"] - base_close,
                        "close_pct": (future["close"] / base_close - 1) * 100,

                        "future_high": future["high"],
                        "high_diff": future["high"] - base_high,
                        "high_pct": (future["high"] / base_high - 1) * 100,

                        "future_low": future["low"],
                        "low_diff": future["low"] - base_low,
                        "low_pct": (future["low"] / base_low - 1) * 100,
                    })

        except Exception as e:
            print(f"{ts_code} error: {e}")

    if dividend_cache_ref["dirty"]:
        save_dividend_cache(dividend_cache_ref["df"])
    if shareholder_cache_ref["dirty"]:
        save_shareholder_cache(shareholder_cache_ref["df"])

    print("筛选诊断：")
    for key, value in stats.items():
        print(f"- {key}: {value}")

    return pd.DataFrame(results)


def format_price(value):
    return f"{value:.2f}"


def format_diff(value):
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}"


def init_display_row(columns):
    return {column: "" for column in columns}


def get_enabled_condition_names():
    return [
        CONDITION_NAMES.get(key, key)
        for key, enabled in CONDITION_FLAGS.items()
        if enabled
    ]


def build_display_table(detail_df):
    base_df = detail_df[detail_df["forward_day"] == 0].copy()
    future_df = detail_df[detail_df["forward_day"] > 0].copy()

    signal_dates = set(base_df["signal_date"])
    dates = sorted(set(detail_df["signal_date"]).union(set(detail_df["future_date"])))
    columns = []
    for date in dates:
        columns.append(date)
        if date in signal_dates:
            columns.append(f"{date}_价格")

    rows = []
    block_index = {}

    base_df = base_df.sort_values(by=["signal_date", "ts_code"]).reset_index(drop=True)
    for _, row in base_df.iterrows():
        start_row = len(rows)
        block_index[(row["signal_date"], row["ts_code"])] = start_row

        for _ in range(3):
            rows.append(init_display_row(columns))

        date_col = row["signal_date"]
        price_col = f"{row['signal_date']}_价格"

        rows[start_row][date_col] = row["ts_code"]
        rows[start_row + 1][date_col] = row["name"]
        rows[start_row][price_col] = f"收盘价{format_price(row['base_close'])}"
        rows[start_row + 1][price_col] = f"最高价{format_price(row['base_high'])}"
        rows[start_row + 2][price_col] = f"最低价{format_price(row['base_low'])}"

    future_df = future_df.sort_values(
        by=["signal_date", "ts_code", "forward_day"]
    ).reset_index(drop=True)

    for _, row in future_df.iterrows():
        start_row = block_index.get((row["signal_date"], row["ts_code"]))
        if start_row is None:
            continue

        date_col = row["future_date"]
        rows[start_row][date_col] = format_diff(row["close_diff"])
        rows[start_row + 1][date_col] = format_diff(row["high_diff"])
        rows[start_row + 2][date_col] = format_diff(row["low_diff"])

    return pd.DataFrame(rows, columns=columns)


def save_display_excel(display_table, filename=RESULT_XLSX):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "策略筛选"
    summary_sheet = workbook.create_sheet("策略说明")
    red_font = Font(color="FF0000")
    green_font = Font(color="008000")

    enabled_condition_names = get_enabled_condition_names()
    summary_sheet["A1"] = "当前策略"
    summary_sheet["B1"] = RUNTIME_CONFIG["strategy_name"]
    summary_sheet["A2"] = "策略说明"
    summary_sheet["B2"] = RUNTIME_CONFIG.get("description", "")
    summary_sheet["A3"] = "基础过滤"
    summary_sheet["B3"] = f"排除ST：{RUNTIME_CONFIG['exclude_st_stocks']}；EPS >= {MIN_EPS}"
    summary_sheet["A4"] = "启用条件"
    summary_sheet["B4"] = "、".join(enabled_condition_names)
    summary_sheet["A6"] = "启用条件明细"
    for row_index, condition_name in enumerate(enabled_condition_names, start=7):
        summary_sheet.cell(row=row_index, column=1, value=condition_name)
    for col_index in range(1, 3):
        summary_sheet.column_dimensions[get_column_letter(col_index)].width = 36

    column_count = len(display_table.columns)
    col_index = 1
    while col_index <= column_count:
        date = display_table.columns[col_index - 1]
        has_price_column = (
            col_index < column_count
            and display_table.columns[col_index] == f"{date}_价格"
        )
        if has_price_column:
            worksheet.merge_cells(
                start_row=1,
                start_column=col_index,
                end_row=1,
                end_column=col_index + 1
            )
        cell = worksheet.cell(row=1, column=col_index, value=date)
        cell.font = Font(bold=True, size=14)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        col_index += 2 if has_price_column else 1

    for row_index, row in enumerate(display_table.itertuples(index=False), start=2):
        for col_index, value in enumerate(row, start=1):
            cell = worksheet.cell(row=row_index, column=col_index, value=value)
            cell.alignment = Alignment(vertical="center")
            if isinstance(value, str) and value.startswith("+"):
                cell.font = red_font
            elif isinstance(value, str) and value.startswith("-"):
                cell.font = green_font

    for col_index in range(1, column_count + 1):
        worksheet.column_dimensions[get_column_letter(col_index)].width = 18

    workbook.save(filename)
    return True


def save_result_tables(detail_df):
    if detail_df.empty:
        print(f"最近 {SIGNAL_DAYS} 个交易日没有筛选出符合条件的股票")
        return None

    display_table = build_display_table(detail_df)
    saved_xlsx = save_display_excel(display_table)

    if saved_xlsx:
        print(f"策略筛选横向展示表：{RESULT_XLSX}")
    print("\n===== 策略筛选横向展示表 =====")
    print(display_table)

    return display_table


def main():
    detail_df = choose_strategy()
    save_result_tables(detail_df)


if __name__ == '__main__':
    main()
