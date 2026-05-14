import os
import pandas as pd


def normalize_daily_cache_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].astype(str)
    return df


def get_daily_cache_file_path(trade_date, daily_cache_csv):
    file_name = f"{str(trade_date)}_{os.path.basename(daily_cache_csv)}"
    return os.path.join(os.path.dirname(daily_cache_csv), file_name)


def read_daily_cache_file(cache_file):
    if not os.path.exists(cache_file):
        return pd.DataFrame()
    df = pd.read_csv(cache_file, dtype={"ts_code": str, "trade_date": str})
    return normalize_daily_cache_df(df)


def load_daily_cache(trade_dates, daily_cache_csv):
    cached_frames = []
    cached_dates = set()
    for trade_date in trade_dates:
        cache_file = get_daily_cache_file_path(trade_date, daily_cache_csv)
        date_df = read_daily_cache_file(cache_file)
        if date_df.empty:
            continue
        cached_frames.append(date_df)
        cached_dates.add(str(trade_date))

    if not cached_frames:
        return pd.DataFrame(), cached_dates

    cache_df = pd.concat(cached_frames, ignore_index=True)
    cache_df = cache_df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    cache_df = cache_df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    return cache_df, cached_dates


def save_daily_cache(df, daily_cache_csv):
    if df is None or df.empty:
        return
    if "trade_date" not in df.columns:
        raise ValueError("daily 缓存缺少 trade_date，无法按交易日拆分保存")

    os.makedirs(os.path.dirname(daily_cache_csv), exist_ok=True)
    df = normalize_daily_cache_df(df)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    for trade_date, date_df in df.groupby("trade_date"):
        cache_file = get_daily_cache_file_path(trade_date, daily_cache_csv)
        date_df = date_df.sort_values(by=["ts_code"]).reset_index(drop=True)
        date_df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def load_all_daily(ts_codes, trade_dates, daily_cache_csv, fetch_daily_by_trade_date, fetch_with_retry):
    cache_df, cached_dates = load_daily_cache(trade_dates, daily_cache_csv)
    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
    if missing_dates:
        print(f"日线缓存缺失 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}")
    else:
        print(f"日线缓存已命中最近 {len(trade_dates)} 个交易日，无需重新拉取 daily")

    for trade_date in missing_dates:
        df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_daily_by_trade_date(trade_date),
            f"daily {trade_date}",
        )
        if df.empty:
            raise RuntimeError(f"daily {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
        df["trade_date"] = df["trade_date"].astype(str)
        save_daily_cache(df, daily_cache_csv)
        cache_df = pd.concat([cache_df, df], ignore_index=True)
        print(f"已补齐日线数据：{trade_date}")

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


def load_moneyflow_cache(moneyflow_cache_csv):
    if not os.path.exists(moneyflow_cache_csv):
        return pd.DataFrame()
    df = pd.read_csv(moneyflow_cache_csv, dtype={"ts_code": str, "trade_date": str})
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].astype(str)
    return df


def save_moneyflow_cache(df, moneyflow_cache_csv):
    os.makedirs(os.path.dirname(moneyflow_cache_csv), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    df = df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    df.to_csv(moneyflow_cache_csv, index=False, encoding="utf-8-sig")


def load_all_moneyflow(trade_dates, moneyflow_cache_csv, fetch_moneyflow_by_trade_date, fetch_with_retry):
    cache_df = load_moneyflow_cache(moneyflow_cache_csv)
    cached_dates = set(cache_df["trade_date"].astype(str)) if not cache_df.empty and "trade_date" in cache_df.columns else set()
    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in cached_dates]
    if missing_dates:
        print(f"资金流缓存缺失 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}")
    else:
        print(f"资金流缓存已命中最近 {len(trade_dates)} 个交易日，无需重新拉取")

    for trade_date in missing_dates:
        df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_moneyflow_by_trade_date(trade_date),
            f"moneyflow {trade_date}",
        )
        if df.empty:
            raise RuntimeError(f"moneyflow {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
        df["trade_date"] = df["trade_date"].astype(str)
        cache_df = pd.concat([cache_df, df], ignore_index=True)
        save_moneyflow_cache(cache_df, moneyflow_cache_csv)
        print(f"已补齐资金流数据：{trade_date}")

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
    cache_df["external_internal_ratio"] = cache_df["external_vol"] / cache_df["internal_vol"].where(cache_df["internal_vol"] > 0)
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


def load_basic_cache(eps_downloader):
    df = eps_downloader.load_basic_cache_file()
    if df.empty:
        return df
    drop_columns = [col for col in ["total_mv", "eps"] if col in df.columns]
    if drop_columns:
        df = df.drop(columns=drop_columns)
    numeric_columns = ["volume_ratio", "turnover_rate", "pe", "dv_ttm"]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def save_basic_cache(df, eps_downloader):
    df = df.drop(columns=["total_mv"], errors="ignore")
    eps_downloader.upsert_basic_cache_rows(df)


def fetch_daily_basic_by_trade_date(trade_date, pro_api):
    pro = pro_api()
    fields = "ts_code,trade_date,pe,pe_ttm,volume_ratio,turnover_rate,dv_ttm"
    return pro.daily_basic(trade_date=trade_date, fields=fields)


def fetch_total_mv_by_trade_date(trade_date, pro_api):
    pro = pro_api()
    return pro.daily_basic(trade_date=trade_date, fields="ts_code,trade_date,total_mv")


def load_latest_total_mv(ts_codes, trade_date, total_mv_filter_enabled, fetch_with_retry, pro_api):
    if not total_mv_filter_enabled:
        return pd.DataFrame(columns=["ts_code", "total_mv"])
    total_mv_df = fetch_with_retry(
        lambda: fetch_total_mv_by_trade_date(trade_date, pro_api),
        f"daily_basic total_mv {trade_date}",
    )
    if total_mv_df.empty:
        raise RuntimeError(f"daily_basic total_mv {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
    total_mv_df = total_mv_df.copy()
    total_mv_df["ts_code"] = total_mv_df["ts_code"].astype(str)
    total_mv_df["total_mv"] = pd.to_numeric(total_mv_df["total_mv"], errors="coerce")
    ts_code_set = set(ts_codes)
    total_mv_df = total_mv_df[total_mv_df["ts_code"].isin(ts_code_set)].copy()
    total_mv_df = total_mv_df.drop_duplicates(subset=["ts_code"], keep="last")
    print(f"已拉取最近交易日总市值：{trade_date}，{len(total_mv_df)} 只股票")
    return total_mv_df[["ts_code", "total_mv"]]


def merge_basic_frames(daily_basic_df, trade_date):
    daily_basic_columns = ["ts_code", "trade_date", "pe", "pe_ttm", "volume_ratio", "turnover_rate", "dv_ttm"]
    if daily_basic_df is None or daily_basic_df.empty:
        daily_basic_df = pd.DataFrame(columns=daily_basic_columns)
    daily_basic_df = daily_basic_df.copy()
    if "trade_date" not in daily_basic_df.columns:
        daily_basic_df["trade_date"] = trade_date
    merged = daily_basic_df.copy()
    if "pe_ttm" in merged.columns:
        merged["pe"] = merged["pe_ttm"].where(merged["pe_ttm"].notna(), merged.get("pe"))
    columns = ["ts_code", "trade_date", "volume_ratio", "turnover_rate", "pe", "dv_ttm"]
    for col in columns:
        if col not in merged.columns:
            merged[col] = pd.NA
    return merged[columns].copy()


def load_all_basic(
    ts_codes,
    trade_dates,
    *,
    daily_df,
    eps_filter_enabled,
    eps_downloader,
    fetch_with_retry,
    pro_api,
):
    cache_df = load_basic_cache(eps_downloader)
    required_columns = {"ts_code", "trade_date", "volume_ratio", "turnover_rate", "pe", "dv_ttm"}
    cache_has_required_columns = required_columns.issubset(set(cache_df.columns))
    valid_cached_dates = set()
    invalid_cached_dates = []
    expected_counts = {}
    if daily_df is not None and not daily_df.empty and "trade_date" in daily_df.columns:
        expected_counts = (
            daily_df.assign(trade_date=daily_df["trade_date"].astype(str))
            .groupby("trade_date")["ts_code"]
            .nunique()
            .to_dict()
        )
    if cache_has_required_columns and not cache_df.empty and "trade_date" in cache_df.columns:
        trade_date_cache = cache_df["trade_date"].astype(str)
        for trade_date in trade_dates:
            date_df = cache_df[trade_date_cache == trade_date]
            if date_df.empty:
                continue
            daily_basic_columns = ["volume_ratio", "turnover_rate", "pe", "dv_ttm"]
            daily_basic_ready = date_df[daily_basic_columns].notna().any(axis=0).all()
            expected_count = expected_counts.get(trade_date)
            coverage_ready = True
            if expected_count:
                coverage_ready = date_df["ts_code"].nunique() >= max(1, int(expected_count * 0.9))
            if daily_basic_ready and coverage_ready:
                valid_cached_dates.add(trade_date)
            else:
                invalid_cached_dates.append(trade_date)

    missing_dates = [trade_date for trade_date in trade_dates if trade_date not in valid_cached_dates]
    if missing_dates:
        message = f"基础面缓存缺失或不完整 {len(missing_dates)} 个交易日，开始补齐：{', '.join(missing_dates)}"
        if invalid_cached_dates:
            message += f"；其中缓存不完整日期：{', '.join(invalid_cached_dates)}"
        print(message)
    else:
        print(f"基础面缓存已命中最近 {len(trade_dates)} 个交易日，无需重新拉取")

    for trade_date in missing_dates:
        daily_basic_df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_daily_basic_by_trade_date(trade_date, pro_api),
            f"daily_basic {trade_date}",
        )
        if daily_basic_df.empty:
            raise RuntimeError(f"daily_basic {trade_date} 返回空数据，已停止本次任务，避免使用不完整数据")
        merged = merge_basic_frames(daily_basic_df, trade_date)
        if not merged.empty:
            cache_df = pd.concat([cache_df, merged], ignore_index=True)
            save_basic_cache(cache_df, eps_downloader)
            print(f"已补齐基础面数据：{trade_date}")

    if cache_df.empty:
        columns = ["ts_code", "trade_date", "volume_ratio", "turnover_rate", "pe", "dv_ttm"]
        if eps_filter_enabled:
            columns.insert(2, "eps")
        return pd.DataFrame(columns=columns)

    ts_code_set = set(ts_codes)
    trade_date_set = set(trade_dates)
    result = cache_df[
        cache_df["ts_code"].isin(ts_code_set)
        & cache_df["trade_date"].isin(trade_date_set)
    ].copy()
    result_columns = ["ts_code", "trade_date", "volume_ratio", "turnover_rate", "pe"]
    result = result[[col for col in result_columns if col in result.columns]].copy()
    if eps_filter_enabled:
        eps_cache_df = eps_downloader.load_eps_cache()
        if not eps_cache_df.empty:
            eps_result = eps_cache_df[
                eps_cache_df["ts_code"].isin(ts_code_set)
                & eps_cache_df["trade_date"].isin(trade_date_set)
            ][["ts_code", "trade_date", "eps"]].copy()
            result = result.merge(eps_result, on=["ts_code", "trade_date"], how="left")
        else:
            result["eps"] = pd.NA
        result_columns.insert(2, "eps")
        result = result[[col for col in result_columns if col in result.columns]].copy()
    print(
        f"本次使用基础面缓存：{len(result)} 行，"
        f"{result['trade_date'].nunique() if not result.empty else 0} 个交易日，"
        f"{result['ts_code'].nunique() if not result.empty else 0} 只股票"
    )
    return result


def prepare_initial_daily_data(
    strategy_module,
    stock_pool,
    ts_codes,
    trade_dates,
    signal_dates,
    stock_info,
    *,
    exclude_st=False,
    exclude_bj=False,
    prefer_pe_ttm=False,
    estimate_eps_when_missing=False,
    filter_context_label="信号窗口",
    enable_industry_metrics=True,
):
    """
    统一的前置数据链路：
    1) 缓存检查与数据下载（daily / basic / total_mv）
    2) 基础字段兜底
    3) 信号窗口基础过滤（ST/BJ/EPS/PE/总市值）
    """
    all_daily = strategy_module.load_all_daily(ts_codes, trade_dates)
    if all_daily.empty:
        return {
            "all_daily": all_daily,
            "filtered_signal_df": pd.DataFrame(),
            "basic_filter_summary": {
                "filter_names": [],
                "before_stock_count": 0,
                "after_stock_count": 0,
                "before_row_count": 0,
                "after_row_count": 0,
            },
            "eligible_signal_keys": set(),
        }

    if getattr(strategy_module, "TOTAL_MV_FILTER_ENABLED", False):
        latest_total_mv_df = strategy_module.load_latest_total_mv(ts_codes, trade_dates[-1])
        all_daily = all_daily.merge(latest_total_mv_df, on=["ts_code"], how="left")

    all_basic = strategy_module.load_all_basic(ts_codes, trade_dates, daily_df=all_daily)
    if not all_basic.empty:
        all_daily = all_daily.merge(
            all_basic,
            on=["ts_code", "trade_date"],
            how="left",
        )

    required_basic_columns = ["volume_ratio", "turnover_rate", "pe", "pe_ttm", "dv_ttm"]
    if getattr(strategy_module, "EPS_FILTER_ENABLED", False):
        required_basic_columns.append("eps")
    if getattr(strategy_module, "TOTAL_MV_FILTER_ENABLED", False):
        required_basic_columns.append("total_mv")
    for col in required_basic_columns:
        if col not in all_daily.columns:
            all_daily[col] = pd.NA

    if enable_industry_metrics and hasattr(strategy_module, "add_industry_valuation_metrics"):
        all_daily = strategy_module.add_industry_valuation_metrics(all_daily, stock_pool)

    signal_date_set = set(signal_dates)
    signal_df = all_daily[all_daily["trade_date"].astype(str).isin(signal_date_set)].copy()
    filtered_signal_df, basic_filter_summary = strategy_module.apply_basic_filters(
        signal_df,
        stock_name_map=stock_info,
        exclude_st=exclude_st,
        exclude_bj=exclude_bj,
        prefer_pe_ttm=prefer_pe_ttm,
        estimate_eps_when_missing=estimate_eps_when_missing,
    )
    strategy_module.print_basic_filter_summary(basic_filter_summary, filter_context_label)

    eligible_signal_keys = set(zip(
        filtered_signal_df["ts_code"].astype(str),
        filtered_signal_df["trade_date"].astype(str),
    ))

    return {
        "all_daily": all_daily,
        "filtered_signal_df": filtered_signal_df,
        "basic_filter_summary": basic_filter_summary,
        "eligible_signal_keys": eligible_signal_keys,
    }
