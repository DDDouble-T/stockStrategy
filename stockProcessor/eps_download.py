import os
import time
from copy import deepcopy
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts

from module.config import tushare_config
from stockProcessor.download.constants import data_path
import strategy_choose_config


# ======================
# 运行配置
# ======================
# 可选值：
# - download：保留现有缓存，只补缺失/不完整的 EPS
# - update：按当前区间全部重下 EPS
RUN_MODE = "download"
END_DATE = None
# 仅在 RUN_MODE = "update" 时生效。
# None / ""：从基础面缓存中的最早 trade_date 开始更新。
# 例如 "20250101"：从指定日期开始更新到 END_DATE 或最近已完成交易日。
UPDATE_START_DATE = None


def load_strategy_runtime_config():
    # 下载脚本只负责构建稳定缓存，不应随着 ACTIVE_STRATEGY 切换而改变下载口径。
    # 这里固定基于默认配置，避免选股 preset 影响基础数据准备。
    config = deepcopy(strategy_choose_config.DEFAULT_CONFIG)
    config["strategy_name"] = "default_download"
    return config


RUNTIME_CONFIG = load_strategy_runtime_config()
MARKET_CLOSE_HOUR = int(RUNTIME_CONFIG.get("market_close_hour", 15))
BAK_BASIC_MIN_INTERVAL_SECONDS = int(RUNTIME_CONFIG.get("bak_basic_min_interval_seconds", 30))


BASIC_CACHE_CSV = data_path("strategy_basic_cache.csv")
LAST_BAK_BASIC_FETCH_TS = None
KEY_COLUMNS = ["ts_code", "trade_date"]
BASIC_NUMERIC_COLUMNS = ["volume_ratio", "turnover_rate", "pe", "eps"]


def pro_api():
    return ts.pro_api(tushare_config.TuShareConst.TOKEN)


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
        return trade_dates[-1]
    if len(trade_dates) < 2:
        raise ValueError("当前交易日未结束，且没有可用的上一交易日")
    return trade_dates[-2]


def get_trade_dates(start_date, end_date):
    pro = pro_api()
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        is_open="1"
    )
    cal = cal.sort_values("cal_date")
    trade_dates = cal["cal_date"].tolist()
    if not trade_dates:
        raise ValueError("未获取到可用交易日，请检查交易日历接口")
    return trade_dates


def normalize_basic_cache_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "volume_ratio", "turnover_rate", "pe", "eps"])

    df = df.copy()
    for col in ["ts_code", "trade_date"]:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = df[col].astype(str)

    drop_columns = [col for col in ["total_mv"] if col in df.columns]
    if drop_columns:
        df = df.drop(columns=drop_columns)

    for col in BASIC_NUMERIC_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")

    base_columns = KEY_COLUMNS + ["volume_ratio", "turnover_rate", "pe", "eps"]
    extra_columns = [col for col in df.columns if col not in base_columns]
    df = df[base_columns + extra_columns]
    df = df.drop_duplicates(subset=KEY_COLUMNS, keep="last")
    df = df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    return df


def load_basic_cache_file():
    if not os.path.exists(BASIC_CACHE_CSV):
        return normalize_basic_cache_df(pd.DataFrame())

    df = pd.read_csv(BASIC_CACHE_CSV, dtype={"ts_code": str, "trade_date": str})
    return normalize_basic_cache_df(df)


def save_basic_cache_file(df):
    os.makedirs(os.path.dirname(BASIC_CACHE_CSV), exist_ok=True)
    df = normalize_basic_cache_df(df)
    df.to_csv(BASIC_CACHE_CSV, index=False, encoding="utf-8-sig")


def load_eps_cache():
    cache_df = load_basic_cache_file()
    return cache_df[["ts_code", "trade_date", "eps"]].copy()


def upsert_basic_cache_rows(basic_df):
    cache_df = load_basic_cache_file()
    basic_df = normalize_basic_cache_df(basic_df)

    if basic_df.empty:
        return cache_df

    if not cache_df.empty:
        eps_df = cache_df[["ts_code", "trade_date", "eps"]].copy()
        basic_df = basic_df.drop(columns=["eps"], errors="ignore")
        basic_df = basic_df.merge(eps_df, on=KEY_COLUMNS, how="left")

    merged_df = pd.concat([cache_df, basic_df], ignore_index=True, sort=False)
    merged_df = normalize_basic_cache_df(merged_df)
    save_basic_cache_file(merged_df)
    return merged_df


def upsert_eps_cache_rows(eps_df, clear_trade_dates=None):
    cache_df = load_basic_cache_file()
    eps_df = normalize_basic_cache_df(eps_df)[["ts_code", "trade_date", "eps"]]

    if clear_trade_dates:
        clear_trade_dates = {str(item) for item in clear_trade_dates}
        if not cache_df.empty:
            mask = cache_df["trade_date"].isin(clear_trade_dates)
            cache_df.loc[mask, "eps"] = pd.NA

    if eps_df.empty:
        save_basic_cache_file(cache_df)
        return cache_df

    cache_without_eps = cache_df.drop(columns=["eps"], errors="ignore")
    eps_payload = pd.merge(
        cache_without_eps,
        eps_df,
        on=KEY_COLUMNS,
        how="right"
    )
    merged_df = pd.concat([cache_df, eps_payload], ignore_index=True, sort=False)
    merged_df = normalize_basic_cache_df(merged_df)
    save_basic_cache_file(merged_df)
    return merged_df


def get_expected_counts_from_basic_cache():
    cache_df = load_basic_cache_file()
    if cache_df.empty:
        return {}
    return cache_df.groupby("trade_date")["ts_code"].nunique().to_dict()


def get_cached_trade_dates():
    cache_df = load_basic_cache_file()
    if cache_df.empty or "trade_date" not in cache_df.columns:
        return []
    trade_dates = (
        cache_df["trade_date"]
        .dropna()
        .astype(str)
        .sort_values()
        .unique()
        .tolist()
    )
    return trade_dates


def fetch_bak_basic_by_trade_date(trade_date):
    pro = pro_api()
    return pro.bak_basic(trade_date=trade_date)


def fetch_bak_basic_by_trade_date_with_limit(trade_date):
    global LAST_BAK_BASIC_FETCH_TS

    if LAST_BAK_BASIC_FETCH_TS is not None:
        elapsed = time.time() - LAST_BAK_BASIC_FETCH_TS
        wait_seconds = BAK_BASIC_MIN_INTERVAL_SECONDS - elapsed
        if wait_seconds > 0:
            print(f"bak_basic 限频等待 {wait_seconds:.1f} 秒：{trade_date}")
            time.sleep(wait_seconds)

    df = fetch_bak_basic_by_trade_date(trade_date)
    LAST_BAK_BASIC_FETCH_TS = time.time()
    return df


def fetch_eps_by_trade_date(trade_date):
    bak_basic_df = fetch_bak_basic_by_trade_date_with_limit(trade_date)
    if bak_basic_df is None or bak_basic_df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "eps"])

    bak_basic_df = bak_basic_df.copy()
    if "trade_date" not in bak_basic_df.columns:
        bak_basic_df["trade_date"] = trade_date
    if "eps" not in bak_basic_df.columns:
        bak_basic_df["eps"] = pd.NA
    return normalize_basic_cache_df(bak_basic_df[["ts_code", "trade_date", "eps"]])[["ts_code", "trade_date", "eps"]]


def get_missing_or_invalid_eps_dates(trade_dates):
    cache_df = load_basic_cache_file()
    expected_counts = get_expected_counts_from_basic_cache()
    valid_cached_dates = set()
    invalid_cached_dates = []

    if not cache_df.empty and "trade_date" in cache_df.columns:
        trade_date_cache = cache_df["trade_date"].astype(str)
        for trade_date in [str(item) for item in trade_dates]:
            date_df = cache_df[trade_date_cache == trade_date]
            if date_df.empty:
                continue

            eps_ready = date_df["eps"].notna().any() if "eps" in date_df.columns else False
            expected_count = expected_counts.get(trade_date)
            coverage_ready = True
            if expected_count:
                coverage_ready = date_df["ts_code"].nunique() >= max(1, int(expected_count * 0.9))

            if eps_ready and coverage_ready:
                valid_cached_dates.add(trade_date)
            else:
                invalid_cached_dates.append(trade_date)

    trade_dates = [str(trade_date) for trade_date in trade_dates]
    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in valid_cached_dates]
    hit_dates = [trade_date for trade_date in trade_dates if trade_date in valid_cached_dates]
    return hit_dates, missing_dates, invalid_cached_dates


def download_eps(trade_dates):
    hit_dates, missing_dates, invalid_cached_dates = get_missing_or_invalid_eps_dates(trade_dates)
    print(f"EPS 缓存命中 {len(hit_dates)} 个交易日")
    if not missing_dates:
        print(f"EPS 缓存已命中最近 {len(trade_dates)} 个交易日，无需下载")
        return load_eps_cache()

    message = f"EPS 缓存缺失或不完整 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}"
    if invalid_cached_dates:
        message += f"；其中缓存不完整日期：{', '.join(invalid_cached_dates)}"
    print(message)

    for trade_date in missing_dates:
        eps_df = fetch_eps_by_trade_date(trade_date)
        if eps_df.empty:
            print(f"bak_basic {trade_date} 返回空数据，跳过该交易日")
            continue
        upsert_eps_cache_rows(eps_df)
        print(f"已补齐 EPS 数据：{trade_date}")

    return load_eps_cache()


def update_eps(trade_dates):
    trade_dates = [str(trade_date) for trade_date in trade_dates]
    print(f"开始顺序更新 EPS 数据，共 {len(trade_dates)} 个交易日")

    for trade_date in trade_dates:
        eps_df = fetch_eps_by_trade_date(trade_date)
        if eps_df.empty:
            print(f"bak_basic {trade_date} 返回空数据，跳过该交易日")
            continue
        upsert_eps_cache_rows(eps_df, clear_trade_dates=[trade_date])
        print(f"已更新 EPS 数据：{trade_date}")

    return load_eps_cache()


def validate_runtime_config():
    if RUN_MODE not in {"download", "update"}:
        raise ValueError(f"RUN_MODE 配置错误: {RUN_MODE}")


def main():
    validate_runtime_config()
    cached_trade_dates = get_cached_trade_dates()
    if not cached_trade_dates:
        raise ValueError("strategy_basic_cache.csv 中没有可用 trade_date，无法补齐或更新 EPS，请先准备基础面缓存")

    if RUN_MODE == "download":
        trade_dates = cached_trade_dates
        print(
            f"EPS 处理模式：{RUN_MODE}；"
            f"按基础面缓存遍历：{trade_dates[0]} ~ {trade_dates[-1]}；"
            f"共 {len(trade_dates)} 个交易日"
        )
        download_eps(trade_dates)
    else:
        end_date = END_DATE or get_latest_completed_trade_date()
        start_date = str(UPDATE_START_DATE).strip() if UPDATE_START_DATE is not None else ""
        if not start_date:
            start_date = cached_trade_dates[0]
        trade_dates = get_trade_dates(start_date, end_date)
        print(
            f"EPS 处理模式：{RUN_MODE}；"
            f"更新起点：{start_date}；"
            f"区间：{trade_dates[0]} ~ {trade_dates[-1]}；"
            f"共 {len(trade_dates)} 个交易日"
        )
        update_eps(trade_dates)


if __name__ == "__main__":
    main()
