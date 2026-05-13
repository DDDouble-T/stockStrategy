import os

import pandas as pd
import tushare as ts

from module.config import tushare_config
from stockProcessor import eps_download as eps_downloader
from stockProcessor.download.constants import data_path


# ======================
# 运行配置
# ======================
# 可选值：
# - download：保留现有缓存，只补缺失/不完整的上一年度分红
# - update：按当前区间全部重下上一年度分红
RUN_MODE = "download"
END_DATE = None
# 仅在 RUN_MODE = "update" 时生效。
# None / ""：从基础面缓存中的最早 trade_date 开始更新。
# 例如 "20250101"：从指定日期开始更新到 END_DATE 或最近已完成交易日。
UPDATE_START_DATE = None
DIVIDEND_CACHE_CSV = data_path("strategy_dividend_cache.csv")
KEY_COLUMNS = ["ts_code", "dividend_year"]


def pro_api():
    return ts.pro_api(tushare_config.TuShareConst.TOKEN)


def normalize_dividend_cache_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_code", "dividend_year", "cash_div_tax"])

    df = df.copy()
    for col in KEY_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
        df = df[df[col].notna()]
        df[col] = df[col].astype(str).str.strip()
        df = df[df[col] != ""]

    if "cash_div_tax" not in df.columns:
        df["cash_div_tax"] = pd.NA
    df["cash_div_tax"] = pd.to_numeric(df["cash_div_tax"], errors="coerce")

    base_columns = KEY_COLUMNS + ["cash_div_tax"]
    extra_columns = [col for col in df.columns if col not in base_columns]
    df = df[base_columns + extra_columns]
    df = df.drop_duplicates(subset=KEY_COLUMNS, keep="last")
    df = df.sort_values(by=["dividend_year", "ts_code"]).reset_index(drop=True)
    return df


def normalize_required_pairs_df(required_pairs):
    if required_pairs is None:
        return pd.DataFrame(columns=KEY_COLUMNS)

    if isinstance(required_pairs, pd.DataFrame):
        df = required_pairs.copy()
    else:
        df = pd.DataFrame(required_pairs, columns=KEY_COLUMNS)

    if df.empty:
        return pd.DataFrame(columns=KEY_COLUMNS)

    for col in KEY_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
        df = df[df[col].notna()]
        df[col] = df[col].astype(str).str.strip()
        df = df[df[col] != ""]

    df = df[KEY_COLUMNS].drop_duplicates(subset=KEY_COLUMNS, keep="last")
    df = df.sort_values(by=["dividend_year", "ts_code"]).reset_index(drop=True)
    return df


def load_dividend_cache():
    if not os.path.exists(DIVIDEND_CACHE_CSV):
        return normalize_dividend_cache_df(pd.DataFrame())

    df = pd.read_csv(
        DIVIDEND_CACHE_CSV,
        dtype={"ts_code": str, "dividend_year": str}
    )
    return normalize_dividend_cache_df(df)


def save_dividend_cache(df):
    os.makedirs(os.path.dirname(DIVIDEND_CACHE_CSV), exist_ok=True)
    df = normalize_dividend_cache_df(df)
    df.to_csv(DIVIDEND_CACHE_CSV, index=False, encoding="utf-8-sig")


def build_required_pairs_from_ts_codes(ts_codes, dividend_year):
    if dividend_year is None:
        return pd.DataFrame(columns=KEY_COLUMNS)

    normalized_ts_codes = sorted({
        str(ts_code).strip()
        for ts_code in ts_codes
        if pd.notna(ts_code) and str(ts_code).strip()
    })
    if not normalized_ts_codes:
        return pd.DataFrame(columns=KEY_COLUMNS)

    df = pd.DataFrame({
        "ts_code": normalized_ts_codes,
        "dividend_year": [str(dividend_year)] * len(normalized_ts_codes)
    })
    return normalize_required_pairs_df(df)


def resolve_prev_dividend_year(trade_dates):
    if not trade_dates:
        raise ValueError("trade_dates 为空，无法推导上一年度分红年份")

    latest_trade_date = max(str(item) for item in trade_dates)
    return str(int(latest_trade_date[:4]) - 1)


def resolve_prev_dividend_year_for_trade_date(trade_date):
    trade_date = str(trade_date).strip()
    if len(trade_date) < 4 or not trade_date[:4].isdigit():
        raise ValueError(f"trade_date 格式非法，无法推导上一年度分红年份: {trade_date}")
    return str(int(trade_date[:4]) - 1)


def normalize_signal_records_df(signal_df, trade_date_col="trade_date"):
    if signal_df is None:
        return pd.DataFrame(columns=["ts_code", trade_date_col])

    if isinstance(signal_df, pd.DataFrame):
        df = signal_df.copy()
    else:
        df = pd.DataFrame(signal_df)

    required_columns = ["ts_code", trade_date_col]
    for col in required_columns:
        if col not in df.columns:
            return pd.DataFrame(columns=required_columns)

    df = df[required_columns].copy()
    df = df[df["ts_code"].notna() & df[trade_date_col].notna()]
    df["ts_code"] = df["ts_code"].astype(str).str.strip()
    df[trade_date_col] = df[trade_date_col].astype(str).str.strip()
    df = df[(df["ts_code"] != "") & (df[trade_date_col] != "")]
    df = df.drop_duplicates(subset=required_columns, keep="last").reset_index(drop=True)
    return df


def build_required_pairs_from_signal_records(signal_df, trade_date_col="trade_date"):
    records_df = normalize_signal_records_df(signal_df, trade_date_col=trade_date_col)
    if records_df.empty:
        return pd.DataFrame(columns=KEY_COLUMNS)

    working_df = records_df.copy()
    working_df["dividend_year"] = working_df[trade_date_col].apply(resolve_prev_dividend_year_for_trade_date)
    return normalize_required_pairs_df(working_df[["ts_code", "dividend_year"]])


def get_required_dividend_pairs_from_basic_cache(trade_dates=None, strict=False, dividend_year=None):
    basic_cache_df = eps_downloader.load_basic_cache_file()
    if basic_cache_df.empty:
        raise ValueError("strategy_basic_cache.csv 中没有可用数据，无法推导分红下载范围")

    df = basic_cache_df.copy()
    df["trade_date"] = df["trade_date"].astype(str)

    if trade_dates:
        trade_dates = [str(item) for item in trade_dates]
        df = df[df["trade_date"].isin(set(trade_dates))].copy()
        if strict:
            cached_dates = set(df["trade_date"].unique().tolist())
            missing_trade_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
            if missing_trade_dates:
                raise ValueError(
                    "基础面缓存缺少以下 trade_date，无法按该区间更新分红缓存："
                    + ", ".join(missing_trade_dates)
                )

    if df.empty:
        return pd.DataFrame(columns=KEY_COLUMNS)

    if dividend_year is None:
        source_trade_dates = trade_dates if trade_dates else df["trade_date"].dropna().astype(str).tolist()
        dividend_year = resolve_prev_dividend_year(source_trade_dates)

    # prev_year_high_dividend 只看“当前目标区间对应的上一年度”，
    # 不因为历史 trade_date 更早而额外请求更久以前的分红年份。
    return build_required_pairs_from_ts_codes(df["ts_code"].tolist(), dividend_year)


def filter_dividend_cache_by_pairs(cache_df, required_pairs_df):
    required_pairs_df = normalize_required_pairs_df(required_pairs_df)
    if cache_df is None or cache_df.empty or required_pairs_df.empty:
        return pd.DataFrame(columns=["ts_code", "dividend_year", "cash_div_tax"])

    cache_df = normalize_dividend_cache_df(cache_df)
    return normalize_dividend_cache_df(
        cache_df.merge(required_pairs_df, on=KEY_COLUMNS, how="inner")
    )


def fetch_prev_year_cash_div_tax(ts_code, dividend_year):
    pro = pro_api()
    # TuShare dividend 官方输入参数不支持按 end_date/分红年度直接过滤，
    # 这里只能按股票请求后在本地收敛到目标上一年度。
    df = pro.dividend(
        ts_code=ts_code,
        fields="ts_code,end_date,div_proc,cash_div,cash_div_tax,record_date,ex_date,pay_date"
    )
    if df.empty or "end_date" not in df.columns:
        return 0.0

    df = df.copy()
    df["end_date"] = df["end_date"].astype(str)
    year_df = df[df["end_date"].str.startswith(str(dividend_year))]
    if year_df.empty:
        return 0.0

    cash_col = "cash_div_tax" if "cash_div_tax" in year_df.columns else "cash_div"
    return float(pd.to_numeric(year_df[cash_col], errors="coerce").fillna(0).sum())


def upsert_dividend_cache_rows(dividend_df, clear_pairs=None):
    cache_df = load_dividend_cache()
    dividend_df = normalize_dividend_cache_df(dividend_df)
    clear_pairs_df = normalize_required_pairs_df(clear_pairs)

    if not clear_pairs_df.empty and not cache_df.empty:
        cache_df = (
            cache_df
            .merge(clear_pairs_df.assign(_drop=1), on=KEY_COLUMNS, how="left")
        )
        cache_df = cache_df[cache_df["_drop"].isna()].drop(columns="_drop")

    if dividend_df.empty:
        save_dividend_cache(cache_df)
        return normalize_dividend_cache_df(cache_df)

    merged_df = pd.concat([cache_df, dividend_df], ignore_index=True, sort=False)
    merged_df = normalize_dividend_cache_df(merged_df)
    save_dividend_cache(merged_df)
    return merged_df


def get_missing_or_invalid_dividend_pairs(required_pairs):
    required_pairs_df = normalize_required_pairs_df(required_pairs)
    if required_pairs_df.empty:
        empty_df = pd.DataFrame(columns=KEY_COLUMNS)
        return empty_df, empty_df, empty_df

    cache_df = load_dividend_cache()
    lookup_df = cache_df[KEY_COLUMNS + ["cash_div_tax"]].copy() if not cache_df.empty else pd.DataFrame(columns=KEY_COLUMNS + ["cash_div_tax"])
    lookup_df["_cache_hit"] = True
    merged_df = required_pairs_df.merge(lookup_df, on=KEY_COLUMNS, how="left")

    hit_mask = merged_df["_cache_hit"].fillna(False) & merged_df["cash_div_tax"].notna()
    invalid_mask = merged_df["_cache_hit"].fillna(False) & merged_df["cash_div_tax"].isna()
    missing_mask = merged_df["_cache_hit"].isna()

    hit_pairs_df = normalize_required_pairs_df(merged_df.loc[hit_mask, KEY_COLUMNS])
    invalid_pairs_df = normalize_required_pairs_df(merged_df.loc[invalid_mask, KEY_COLUMNS])
    pending_pairs_df = normalize_required_pairs_df(merged_df.loc[invalid_mask | missing_mask, KEY_COLUMNS])
    return hit_pairs_df, pending_pairs_df, invalid_pairs_df


def summarize_pairs_by_year(required_pairs_df):
    required_pairs_df = normalize_required_pairs_df(required_pairs_df)
    if required_pairs_df.empty:
        return "无"

    grouped = (
        required_pairs_df
        .groupby("dividend_year")["ts_code"]
        .nunique()
        .sort_index()
    )
    return "；".join(f"{dividend_year}: {count} 只" for dividend_year, count in grouped.items())


def run_dividend_sync(required_pairs_df, mode):
    if mode not in {"download", "update"}:
        raise ValueError(f"不支持的分红同步模式: {mode}")

    total = len(required_pairs_df)
    failures = []
    action_label = "补齐" if mode == "download" else "更新"

    for index, row in enumerate(required_pairs_df.itertuples(index=False), start=1):
        try:
            cash_div_tax = fetch_prev_year_cash_div_tax(row.ts_code, row.dividend_year)
            upsert_dividend_cache_rows(
                pd.DataFrame([{
                    "ts_code": row.ts_code,
                    "dividend_year": row.dividend_year,
                    "cash_div_tax": cash_div_tax
                }]),
                clear_pairs=[(row.ts_code, row.dividend_year)] if mode == "update" else None
            )
        except Exception as exc:
            failures.append(f"{row.ts_code}/{row.dividend_year}: {exc}")
            print(f"分红数据{action_label}失败 {index}/{total}: {row.ts_code}/{row.dividend_year} - {exc}")
            continue

        if index == total or index % 50 == 0:
            print(f"已{action_label}分红数据 {index}/{total}")

    if failures:
        raise RuntimeError(
            "分红数据处理存在失败，但已成功写入已拉取结果："
            + "；".join(failures[:20])
            + ("；..." if len(failures) > 20 else "")
        )


def download_prev_year_high_dividend(required_pairs=None, trade_dates=None):
    required_pairs_df = normalize_required_pairs_df(required_pairs)
    if required_pairs_df.empty:
        required_pairs_df = get_required_dividend_pairs_from_basic_cache(trade_dates)

    hit_pairs_df, pending_pairs_df, invalid_pairs_df = get_missing_or_invalid_dividend_pairs(required_pairs_df)
    print(f"分红缓存命中 {len(hit_pairs_df)} 条股票年度记录")
    if pending_pairs_df.empty:
        print(f"分红缓存已命中目标范围，无需下载；范围：{summarize_pairs_by_year(required_pairs_df)}")
        return filter_dividend_cache_by_pairs(load_dividend_cache(), required_pairs_df)

    message = (
        f"分红缓存缺失或不完整 {len(pending_pairs_df)} 条股票年度记录，开始补齐；"
        f"范围：{summarize_pairs_by_year(pending_pairs_df)}"
    )
    if not invalid_pairs_df.empty:
        message += f"；其中缓存不完整：{summarize_pairs_by_year(invalid_pairs_df)}"
    print(message)

    run_dividend_sync(pending_pairs_df, mode="download")

    return filter_dividend_cache_by_pairs(load_dividend_cache(), required_pairs_df)


def update_prev_year_high_dividend(required_pairs=None, trade_dates=None):
    required_pairs_df = normalize_required_pairs_df(required_pairs)
    if required_pairs_df.empty:
        required_pairs_df = get_required_dividend_pairs_from_basic_cache(trade_dates, strict=True)

    print(
        f"开始顺序更新分红数据，共 {len(required_pairs_df)} 条股票年度记录；"
        f"范围：{summarize_pairs_by_year(required_pairs_df)}"
    )
    run_dividend_sync(required_pairs_df, mode="update")

    return filter_dividend_cache_by_pairs(load_dividend_cache(), required_pairs_df)


def download_prev_year_high_dividend_for_ts_codes(ts_codes, dividend_year):
    required_pairs_df = build_required_pairs_from_ts_codes(ts_codes, dividend_year)
    if required_pairs_df.empty:
        return pd.DataFrame(columns=["ts_code", "dividend_year", "cash_div_tax"])
    return download_prev_year_high_dividend(required_pairs=required_pairs_df)


def load_dividend_cache_for_signal_records(signal_df, trade_date_col="trade_date"):
    required_pairs_df = build_required_pairs_from_signal_records(signal_df, trade_date_col=trade_date_col)
    if required_pairs_df.empty:
        return pd.DataFrame(columns=["ts_code", "dividend_year", "cash_div_tax"])
    return download_prev_year_high_dividend(required_pairs=required_pairs_df)


def get_prev_year_cash_div_tax(ts_code, dividend_year, dividend_cache_ref=None):
    cache_df = dividend_cache_ref["df"] if dividend_cache_ref is not None else load_dividend_cache()
    cache_df = normalize_dividend_cache_df(cache_df)
    year = str(dividend_year)
    cached = cache_df[
        (cache_df["ts_code"] == str(ts_code))
        & (cache_df["dividend_year"] == year)
    ]
    if not cached.empty:
        return float(cached.iloc[-1]["cash_div_tax"])

    cash_div_tax = fetch_prev_year_cash_div_tax(ts_code, dividend_year)
    new_row = pd.DataFrame([{
        "ts_code": str(ts_code),
        "dividend_year": year,
        "cash_div_tax": cash_div_tax
    }])
    if dividend_cache_ref is None:
        upsert_dividend_cache_rows(new_row)
        return cash_div_tax

    if cache_df.empty:
        dividend_cache_ref["df"] = new_row
    else:
        dividend_cache_ref["df"] = normalize_dividend_cache_df(
            pd.concat([cache_df, new_row], ignore_index=True, sort=False)
        )
    dividend_cache_ref["dirty"] = True
    return cash_div_tax


def validate_runtime_config():
    if RUN_MODE not in {"download", "update"}:
        raise ValueError(f"RUN_MODE 配置错误: {RUN_MODE}")


def main():
    validate_runtime_config()
    cached_trade_dates = eps_downloader.get_cached_trade_dates()
    if not cached_trade_dates:
        raise ValueError("strategy_basic_cache.csv 中没有可用 trade_date，无法补齐或更新分红，请先准备基础面缓存")

    if RUN_MODE == "download":
        trade_dates = cached_trade_dates
        required_pairs_df = get_required_dividend_pairs_from_basic_cache(trade_dates)
        print(
            f"分红处理模式：{RUN_MODE}；"
            f"按基础面缓存遍历：{trade_dates[0]} ~ {trade_dates[-1]}；"
            f"共 {len(trade_dates)} 个交易日；"
            f"{len(required_pairs_df)} 条股票年度记录"
        )
        download_prev_year_high_dividend(required_pairs=required_pairs_df)
    else:
        end_date = END_DATE or eps_downloader.get_latest_completed_trade_date()
        start_date = str(UPDATE_START_DATE).strip() if UPDATE_START_DATE is not None else ""
        if not start_date:
            start_date = cached_trade_dates[0]
        trade_dates = eps_downloader.get_trade_dates(start_date, end_date)
        required_pairs_df = get_required_dividend_pairs_from_basic_cache(trade_dates, strict=True)
        print(
            f"分红处理模式：{RUN_MODE}；"
            f"更新起点：{start_date}；"
            f"区间：{trade_dates[0]} ~ {trade_dates[-1]}；"
            f"共 {len(trade_dates)} 个交易日；"
            f"{len(required_pairs_df)} 条股票年度记录"
        )
        update_prev_year_high_dividend(required_pairs=required_pairs_df)


if __name__ == "__main__":
    main()
