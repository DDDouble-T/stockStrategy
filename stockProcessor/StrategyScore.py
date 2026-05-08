# -*- coding: utf-8 -*-
"""
StrategyScore.py

用途：
1. 遍历当前策略条件的“3个及以上”组合；
2. 用 base_close 作为信号验证基准价，不模拟真实买入成交；
3. 统计信号出现后第 3/5/10/20/30 个交易日的表现；
4. 为每个组合在不同周期上的能力打分，并导出 Excel。

本版评分机制：
- period_scores 同时输出 raw_score 与 score；
- raw_score 可以为负，用于总分与排名；
- score = max(0, raw_score)，仅用于展示；
- 回撤惩罚采用“周期容忍回撤”机制，只惩罚超过正常波动的部分；
- 不再鼓励大样本：新增“筛选密度惩罚”，筛出太多股票会扣分；
- 筛选密度分母使用 EPS 基础过滤 + ST/BJ 过滤之后的候选信号池；
- 样本惩罚仅保留极小样本轻惩罚，避免精选策略被大幅压分；
- 收益分权重上调，让策略排名更偏向真实收益兑现能力。

放置位置：
建议和 StrategyChoose.py、strategy_choose_config.py 放在同一目录下运行。

运行：
python StrategyScore.py
"""

import os
from itertools import combinations
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# 复用你现有 StrategyChoose.py 里的 TuShare 配置、日线缓存、指标计算、股票池等逻辑
import StrategyChoose as sc
from stockProcessor.download.constants import data_path, result_path


# ======================
# 可调参数区
# ======================

# 只验证这些周期：这里的 3/5/10/20/30 都是“交易日”，不是自然日。
# 3：信号快速生效能力；5：约一周；10：约两周；20：约一个月；30：约一个半月。
FORWARD_DAYS = [3, 5, 10, 20, 30]

# 最近多少个交易日作为“候选信号日”。
# 注意：如果信号日距离最近交易日不足 30 天，则 30 日结果自动不统计。
BACKTEST_SIGNAL_DAYS = 120

# 指标预热区间。MA20、MACD、RSI 都需要历史数据，预热不参与信号评分。
WARMUP_TRADE_DAYS = 80

# 组合至少包含几个条件。你说的是“每三个及以上”。
MIN_COMBO_SIZE = 4

# 输出文件
RESULT_XLSX = result_path("strategy_score_result.xlsx")
DETAIL_CSV = result_path("strategy_score_detail.csv")
MONEYFLOW_CACHE_CSV = data_path("strategy_moneyflow_cache.csv")

# 是否只测试少数股票。None 表示全市场。
# TEST_TS_CODES = ["002709.SZ", "000938.SZ"]
TEST_TS_CODES = None

# 是否排除 ST / *ST。建议开启。
EXCLUDE_ST = True

# 是否排除北交所。TuShare ts_code 后缀一般为 .BJ。先跑全市场慢的话可以开启。
EXCLUDE_BJ = True

# ----------------------
# 基础过滤 / 交易热度阈值
# ----------------------
# EPS、总市值和 ST 是基础过滤：先排掉，再计算“总股票数量/候选信号池”。
# EPS 如果 daily_basic 没直接给，会用 close / pe_ttm 或 close / pe 粗略反推。
MIN_EPS = getattr(sc, "MIN_EPS", 0.0)
EPS_FILTER_ENABLED = getattr(sc, "EPS_FILTER_ENABLED", MIN_EPS is not None)
MIN_TOTAL_MV = getattr(sc, "MIN_TOTAL_MV", None)
TOTAL_MV_FILTER_ENABLED = getattr(sc, "TOTAL_MV_FILTER_ENABLED", MIN_TOTAL_MV is not None)

# 量比：过低代表不活跃，过高可能是高潮或异常。先用宽松区间。
MIN_VOLUME_RATIO = getattr(sc, "MIN_VOLUME_RATIO", 0.8)
MAX_VOLUME_RATIO = getattr(sc, "MAX_VOLUME_RATIO", 3.5)

# 换手率：排除太冷清和太情绪化的票。
MIN_TURNOVER_RATE = getattr(sc, "MIN_TURNOVER_RATE", 1.0)
MAX_TURNOVER_RATE = getattr(sc, "MAX_TURNOVER_RATE", 12.0)

# 市盈率：用 pe_ttm 优先，pe 兜底。成长股先不要卡太死。
MIN_PE = getattr(sc, "MIN_PE", 0.0)
MAX_PE = getattr(sc, "MAX_PE", 80.0)

# 内外盘/主动买卖强度：用大单+特大单买卖量近似，避免全量买卖天然接近平衡。
MIN_EXTERNAL_INTERNAL_RATIO = getattr(sc, "MIN_EXTERNAL_INTERNAL_RATIO", 1.05)
MAX_EXTERNAL_INTERNAL_RATIO = getattr(sc, "MAX_EXTERNAL_INTERNAL_RATIO", 2.50)

# ----------------------
# 筛选密度惩罚
# ----------------------
# selection_rate = 当前策略命中样本数 / EPS+总市值+ST/BJ过滤后的候选信号总数。
# 例如 5000只股票 * 120个信号日，经 EPS/总市值/ST/BJ 过滤后可能剩 420000 行候选信号。
# 如果某组合命中 20000 行，selection_rate≈4.76%，说明太宽，会扣分。
TARGET_SELECTION_RATE = 0.005   # <=0.5%：精选，不扣分
MAX_OK_SELECTION_RATE = 0.02    # 0.5%~2%：轻扣；>2%：明显扣分

# 周期权重：最终 total_raw_score 会按这个权重加权。
# 你的策略是一周到一个月，所以 10/20 日权重最高；5 日贴近一周；30 日用于观察延续性。
# 注意：排名使用 raw_score 的加权总分，负分会参与总分，不会被抹平。
PERIOD_WEIGHTS = {
    3: 0.10,
    5: 0.15,
    10: 0.25,
    20: 0.35,
    30: 0.15,
}

# 梯度分布区间，单位是百分比。
BUCKET_BINS = [-np.inf, -10, -5, -3, 0, 3, 5, 10, np.inf]
BUCKET_LABELS = ["<=-10%", "-10~-5%", "-5~-3%", "-3~0%", "0~3%", "3~5%", "5~10%", ">=10%"]


# ======================
# 条件定义区
# ======================

# EPS 和 ST 属于基础过滤：先排除不合格样本，不参与策略条件组合评分。
# 这里默认不加入 prev_year_high_dividend，因为你这次描述的策略没有包含分红条件。
# 分红偏基本面，和 3/10/20/30 个交易日的短中线表现不一定强相关。
CONDITION_KEYS = [
    "bullish_ma_alignment",          # 5日 > 10日 > 20日
    "volume_rule",                   # 上涨放量或回调缩量
    "position_rule",                 # 回踩10/20日线缩量，或突破前高放量
    "macd_golden_cross",             # MACD金叉
    "rsi_not_overheated",            # RSI < 70
    "volume_ratio_high",             # 量比达标
    "external_internal_ratio_high",  # 外盘 / 内盘达标
    "turnover_rate_range",           # 换手率在合理区间
    "pe_reasonable",                 # 市盈率合理
    "social_security_holder",        # 股东成分包含全国社保基金（如果 StrategyChoose 支持）
    "main_money_inflow_2days",       # 主力资金连续流入2天
]

CONDITION_NAME = {
    "trend_above_ma20": "股价>20日线",
    "bullish_ma_alignment": "MA5>MA10>MA20",
    "volume_rule": "上涨放量/回调缩量",
    "position_rule": "回踩缩量/突破放量",
    "macd_golden_cross": "MACD金叉",
    "rsi_not_overheated": "RSI不过热",
    "volume_ratio_high": "量比合理",
    "external_internal_ratio_high": "外盘/内盘达标",
    "turnover_rate_range": "换手率合理",
    "pe_reasonable": "市盈率合理",
    "social_security_holder": "含全国社保基金",
    "main_money_inflow_2days": "主力连续流入2天",
}


# ======================
# TuShare / 缓存辅助函数
# ======================

def get_score_trade_dates(end_date: str):
    """获取本次回测需要的交易日。"""
    total_days = WARMUP_TRADE_DAYS + BACKTEST_SIGNAL_DAYS + max(FORWARD_DAYS) + 5
    return sc.get_trade_dates(end_date, count=total_days)


def fetch_with_retry(fetch_func, label):
    try:
        return fetch_func()
    except Exception as e:
        raise RuntimeError(f"{label} 下载失败，已停止本次评分，避免使用不完整数据：{e}") from e


def load_all_basic(ts_codes, trade_dates, daily_df=None) -> pd.DataFrame:
    """统一复用 StrategyChoose 的基础面缓存与补齐逻辑。"""
    return sc.load_all_basic(ts_codes, trade_dates, daily_df=daily_df)


# ----------------------
# moneyflow 缓存：主力连续流入、内外盘近似
# ----------------------

def load_moneyflow_cache() -> pd.DataFrame:
    if not os.path.exists(MONEYFLOW_CACHE_CSV):
        return pd.DataFrame()
    df = pd.read_csv(MONEYFLOW_CACHE_CSV, dtype={"ts_code": str, "trade_date": str})
    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].astype(str)
    return df


def save_moneyflow_cache(df: pd.DataFrame):
    os.makedirs(os.path.dirname(MONEYFLOW_CACHE_CSV), exist_ok=True)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
    df = df.sort_values(by=["trade_date", "ts_code"]).reset_index(drop=True)
    df.to_csv(MONEYFLOW_CACHE_CSV, index=False, encoding="utf-8-sig")


def fetch_moneyflow_by_trade_date(trade_date: str) -> pd.DataFrame:
    """
    按交易日一次性拉取全市场资金流。
    这样比每个股票、每个日期单独请求快很多。
    """
    pro = sc.pro_api()
    return pro.moneyflow(trade_date=trade_date)


def load_all_moneyflow(trade_dates):
    """
    加载资金流缓存。只按交易日补齐缺失数据。
    用于计算“主力资金连续流入2天”和“外盘/内盘近似”。
    """
    cache_df = load_moneyflow_cache()
    cached_dates = set(cache_df["trade_date"].astype(str)) if not cache_df.empty and "trade_date" in cache_df.columns else set()

    missing_dates = [d for d in trade_dates if d not in cached_dates]
    if missing_dates:
        print(f"资金流缓存缺失 {len(missing_dates)} 个交易日，开始补齐")

    for trade_date in missing_dates:
        df = fetch_with_retry(
            lambda trade_date=trade_date: fetch_moneyflow_by_trade_date(trade_date),
            f"moneyflow {trade_date}"
        )
        if df.empty:
            raise RuntimeError(f"moneyflow {trade_date} 返回空数据，已停止本次评分，避免使用不完整数据")
        df["trade_date"] = df["trade_date"].astype(str)
        cache_df = pd.concat([cache_df, df], ignore_index=True)
        save_moneyflow_cache(cache_df)
        print(f"已补齐资金流数据：{trade_date}")

    if cache_df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "external_internal_ratio", "main_net", "main_inflow_2days"])

    # 主力口径：大单 + 特大单。全量买卖合计天然接近平衡，不适合做内外盘强弱过滤。
    buy_vol_columns = ["buy_lg_vol", "buy_elg_vol"]
    sell_vol_columns = ["sell_lg_vol", "sell_elg_vol"]
    amount_columns = ["buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"]
    for col in buy_vol_columns + sell_vol_columns + amount_columns:
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

    return cache_df[["ts_code", "trade_date", "external_internal_ratio", "main_net", "main_inflow_2days"]].copy()


# ======================
# 股票池 / 条件预计算
# ======================

def load_score_stock_pool():
    stock_pool = sc.load_stock_pool(TEST_TS_CODES)

    if EXCLUDE_ST:
        # 比 startswith("ST") 更严格，会排除 *ST、ST、带ST字样的风险股。
        stock_pool = stock_pool[~stock_pool["name"].astype(str).str.contains("ST", na=False)]

    if EXCLUDE_BJ:
        stock_pool = stock_pool[~stock_pool["ts_code"].astype(str).str.endswith(".BJ")]

    return stock_pool.reset_index(drop=True)


def load_shareholder_cache_safe():
    if hasattr(sc, "load_shareholder_cache"):
        return sc.load_shareholder_cache()
    return pd.DataFrame()


def save_shareholder_cache_safe(df: pd.DataFrame):
    if hasattr(sc, "save_shareholder_cache"):
        return sc.save_shareholder_cache(df)
    return None


def get_social_security_holder_flag_safe(ts_code: str, shareholder_cache_ref: dict) -> bool:
    """
    如果 StrategyChoose.py 支持全国社保基金股东缓存，就复用；否则默认 False。
    默认 False 的效果：包含 social_security_holder 的组合不会命中，但不影响其他组合。
    """
    if hasattr(sc, "get_social_security_holder_flag"):
        try:
            return bool(sc.get_social_security_holder_flag(ts_code, shareholder_cache_ref))
        except Exception:
            return False
    return False


def ensure_numeric_column(df: pd.DataFrame, col: str):
    if col not in df.columns:
        df[col] = pd.NA
    df[col] = pd.to_numeric(df[col], errors="coerce")


def print_basic_filter_stock_counts(all_daily: pd.DataFrame, signal_dates: list, stock_pool_count: int):
    if all_daily.empty:
        print(f"基础过滤前股票数（ST/BJ过滤后）：{stock_pool_count}")
        print("EPS过滤后股票数：0")
        print("总市值过滤后股票数：0")
        return

    signal_date_set = set(signal_dates)
    eps_stock_codes = set()
    total_mv_stock_codes = set()

    for ts_code, raw_df in all_daily.groupby("ts_code"):
        df = raw_df.sort_values("trade_date").reset_index(drop=True).copy()

        basic_columns = ["pe", "pe_ttm", "total_mv"]
        if EPS_FILTER_ENABLED:
            basic_columns.append("eps")
        for col in basic_columns:
            ensure_numeric_column(df, col)

        if EPS_FILTER_ENABLED:
            pe_ref = df["pe_ttm"].where(df["pe_ttm"] > 0, df["pe"])
            eps_estimated = df["close"] / pe_ref.where(pe_ref > 0)
            df["eps"] = df["eps"].where(df["eps"].notna(), eps_estimated)

        signal_df = df[df["trade_date"].astype(str).isin(signal_date_set)].copy()
        if signal_df.empty:
            continue

        signal_df = signal_df[pd.notna(signal_df["close"]) & (signal_df["close"] > 0)]
        if signal_df.empty:
            continue

        eps_mask = pd.Series(True, index=signal_df.index)
        if EPS_FILTER_ENABLED:
            eps_mask &= signal_df["eps"].isna() | (signal_df["eps"] >= MIN_EPS)

        total_mv_mask = pd.Series(True, index=signal_df.index)
        if TOTAL_MV_FILTER_ENABLED:
            total_mv_mask &= signal_df["total_mv"].isna() | (signal_df["total_mv"] > MIN_TOTAL_MV)

        if bool(eps_mask.any()):
            eps_stock_codes.add(ts_code)
        if bool(total_mv_mask.any()):
            total_mv_stock_codes.add(ts_code)

    print(f"基础过滤前股票数（ST/BJ过滤后）：{stock_pool_count}")
    print(f"EPS过滤后股票数（信号窗口内至少1天通过EPS）：{len(eps_stock_codes)}")
    print(f"总市值过滤后股票数（最近交易日总市值通过）：{len(total_mv_stock_codes)}")


def build_condition_base_df(
    all_daily: pd.DataFrame,
    stock_info: dict,
    signal_dates: list,
    moneyflow_df: pd.DataFrame,
    shareholder_cache_ref: dict,
):
    """
    生成“信号候选表”。

    每一行 = 某只股票在某个信号日。
    行里包含：
    - base_close：筛选日收盘价，作为本次信号验证基准价；
    - 每个单项条件的 True/False；
    - 第 3/5/10/20/30 个交易日后的 close/high/low 差值与涨跌幅；
    - 信号后 1~N 日区间最高/最低，用于评分时衡量冲高能力和回撤风险。

    重要：
    - ST/BJ 在股票池阶段过滤；
    - EPS、总市值在这里做基础过滤；
    - 因此 base_df 的总行数就是“EPS + 总市值 + ST/BJ 过滤之后的候选信号总数”，
      后续筛选密度惩罚会用它作为分母。
    """
    if all_daily.empty:
        return pd.DataFrame()

    signal_date_set = set(signal_dates)
    main_inflow_map = {}
    external_internal_ratio_map = {}
    if moneyflow_df is not None and not moneyflow_df.empty:
        for row in moneyflow_df.itertuples(index=False):
            key = (row.ts_code, row.trade_date)
            main_inflow_map[key] = bool(row.main_inflow_2days)
            external_internal_ratio_map[key] = row.external_internal_ratio

    rows = []

    for ts_code, raw_df in all_daily.groupby("ts_code"):
        try:
            df = sc.add_daily_indicators(raw_df)
            if df.empty or len(df) < WARMUP_TRADE_DAYS // 2:
                continue

            df = df.sort_values("trade_date").reset_index(drop=True)
            name = stock_info.get(ts_code, "")

            # 确保 basic 字段存在并为数值。
            basic_columns = ["volume_ratio", "turnover_rate", "pe", "pe_ttm"]
            if EPS_FILTER_ENABLED:
                basic_columns.append("eps")
            if TOTAL_MV_FILTER_ENABLED:
                basic_columns.append("total_mv")
            for col in basic_columns:
                ensure_numeric_column(df, col)

            if EPS_FILTER_ENABLED:
                # 如果 eps 缺失，则用 close / pe_ttm 或 close / pe 反推一个近似 EPS。
                # 这不是严格财报 EPS，但作为“排除亏损/极差样本”的基础过滤足够实用。
                pe_ref = df["pe_ttm"].where(df["pe_ttm"] > 0, df["pe"])
                eps_estimated = df["close"] / pe_ref.where(pe_ref > 0)
                df["eps"] = df["eps"].where(df["eps"].notna(), eps_estimated)

            # 基础派生列
            df["price_up"] = df["close"] > df["close"].shift(1)
            df["price_down"] = df["close"] < df["close"].shift(1)
            df["vol_up"] = df["vol"] > df["vol_ma5"]
            df["vol_down"] = df["vol"] < df["vol_ma5"]

            # 最近前高：必须 shift(1)，避免把当天 high 算进“前高”，造成当前数据污染。
            recent_high = df["high"].shift(1).rolling(sc.RECENT_HIGH_LOOKBACK_DAYS).max()
            near_ma10 = (df["close"] - df["ma10"]).abs() / df["ma10"] <= sc.NEAR_MA_THRESHOLD
            near_ma20 = (df["close"] - df["ma20"]).abs() / df["ma20"] <= sc.NEAR_MA_THRESHOLD

            df["trend_above_ma20"] = df["close"] > df["ma20"]
            df["bullish_ma_alignment"] = (df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"])
            df["volume_rule"] = (df["price_up"] & df["vol_up"]) | (df["price_down"] & df["vol_down"])
            df["position_rule"] = ((near_ma10 | near_ma20) & df["vol_down"]) | ((df["close"] > recent_high) & df["vol_up"])
            df["macd_golden_cross"] = df["macd_gold"].fillna(False)
            df["rsi_not_overheated"] = df["rsi"] < sc.RSI_MAX

            df["eps_basic_filter"] = True
            if EPS_FILTER_ENABLED:
                df["eps_basic_filter"] = df["eps"].isna() | (df["eps"] >= MIN_EPS)
            df["volume_ratio_high"] = (
                (df["volume_ratio"] >= MIN_VOLUME_RATIO)
                & (df["volume_ratio"] <= MAX_VOLUME_RATIO)
            )

            external_internal_ratio = [
                external_internal_ratio_map.get((ts_code, trade_date), pd.NA)
                for trade_date in df["trade_date"].astype(str)
            ]
            external_internal_ratio = pd.to_numeric(pd.Series(external_internal_ratio, index=df.index), errors="coerce")
            df["external_internal_ratio_high"] = (
                (external_internal_ratio >= MIN_EXTERNAL_INTERNAL_RATIO)
                & (external_internal_ratio <= MAX_EXTERNAL_INTERNAL_RATIO)
            )

            df["turnover_rate_range"] = (
                (df["turnover_rate"] >= MIN_TURNOVER_RATE)
                & (df["turnover_rate"] <= MAX_TURNOVER_RATE)
            )

            pe_for_filter = df["pe_ttm"].where(df["pe_ttm"] > 0, df["pe"])
            df["pe_reasonable"] = (pe_for_filter > MIN_PE) & (pe_for_filter <= MAX_PE)

            holder_flag = get_social_security_holder_flag_safe(ts_code, shareholder_cache_ref)
            df["social_security_holder"] = holder_flag

            df["main_money_inflow_2days"] = [
                main_inflow_map.get((ts_code, trade_date), False)
                for trade_date in df["trade_date"].astype(str)
            ]

            # NaN 条件统一按 False 处理
            for key in CONDITION_KEYS:
                df[key] = df[key].fillna(False).astype(bool)

            for i, row in df.iterrows():
                signal_date = str(row["trade_date"])
                if signal_date not in signal_date_set:
                    continue

                base_close = row["close"]
                if pd.isna(base_close) or base_close <= 0:
                    continue

                # EPS 基础过滤关闭时，缺失 EPS 不会影响候选池。
                if EPS_FILTER_ENABLED and not bool(row["eps_basic_filter"]):
                    continue
                if TOTAL_MV_FILTER_ENABLED and pd.notna(row["total_mv"]) and row["total_mv"] <= MIN_TOTAL_MV:
                    continue

                item = {
                    "ts_code": ts_code,
                    "name": name,
                    "signal_date": signal_date,
                    "base_close": base_close,
                    "pe_ref": row.get("pe_ttm", row.get("pe", pd.NA)),
                    "volume_ratio": row.get("volume_ratio", pd.NA),
                    "turnover_rate": row.get("turnover_rate", pd.NA),
                }
                if EPS_FILTER_ENABLED:
                    item["eps"] = row.get("eps", pd.NA)
                if TOTAL_MV_FILTER_ENABLED:
                    item["total_mv"] = row.get("total_mv", pd.NA)

                for key in CONDITION_KEYS:
                    item[key] = bool(row[key])

                for h in FORWARD_DAYS:
                    future_index = i + h
                    valid = future_index < len(df)
                    item[f"valid_{h}"] = valid

                    if not valid:
                        item[f"future_date_{h}"] = None
                        item[f"close_diff_{h}"] = np.nan
                        item[f"close_pct_{h}"] = np.nan
                        item[f"high_diff_{h}"] = np.nan
                        item[f"high_pct_{h}"] = np.nan
                        item[f"low_diff_{h}"] = np.nan
                        item[f"low_pct_{h}"] = np.nan
                        item[f"period_high_pct_{h}"] = np.nan
                        item[f"period_low_pct_{h}"] = np.nan
                        continue

                    future = df.iloc[future_index]
                    window = df.iloc[i + 1: future_index + 1]

                    future_close = future["close"]
                    future_high = future["high"]
                    future_low = future["low"]
                    period_high = window["high"].max()
                    period_low = window["low"].min()

                    item[f"future_date_{h}"] = future["trade_date"]

                    # 重点：全部以 base_close 为基准，不用 base_high/base_low。
                    item[f"close_diff_{h}"] = future_close - base_close
                    item[f"close_pct_{h}"] = (future_close / base_close - 1) * 100

                    item[f"high_diff_{h}"] = future_high - base_close
                    item[f"high_pct_{h}"] = (future_high / base_close - 1) * 100

                    item[f"low_diff_{h}"] = future_low - base_close
                    item[f"low_pct_{h}"] = (future_low / base_close - 1) * 100

                    # 区间最高/最低比“第N天当天最高/最低”更能表达止盈空间和过程回撤。
                    item[f"period_high_pct_{h}"] = (period_high / base_close - 1) * 100
                    item[f"period_low_pct_{h}"] = (period_low / base_close - 1) * 100

                rows.append(item)

        except Exception as e:
            print(f"build condition error {ts_code}: {e}")

    return pd.DataFrame(rows)


# ======================
# 组合、评分、汇总
# ======================

def generate_condition_combinations():
    combos = []
    for size in range(MIN_COMBO_SIZE, len(CONDITION_KEYS) + 1):
        combos.extend(combinations(CONDITION_KEYS, size))
    return combos


def combo_to_name(combo):
    return " + ".join(CONDITION_NAME.get(k, k) for k in combo)


def calc_small_sample_penalty(sample_count: int) -> float:
    """
    极小样本轻惩罚。

    你的目标是“精选少量股票”，所以不再用过去那种 <30 样本就重扣的逻辑。
    但如果历史样本极少，例如只有 1~4 个，也可能是偶然性很强，所以保留轻惩罚。
    """
    if sample_count < 5:
        return 8.0
    if sample_count < 10:
        return 3.0
    return 0.0


def calc_selection_penalty(selection_rate: float) -> float:
    """
    筛选密度惩罚。

    selection_rate = 命中样本数 / EPS+总市值+ST/BJ 过滤后的候选信号总数。

    设计目标：
    - 你希望每天筛出的是少量精选票，而不是几百只大样本；
    - 因此“筛得太多”要扣分；
    - 筛得少不扣分，但极小历史样本由 calc_small_sample_penalty 轻扣。

    阈值说明：
    - <=0.5%：精选，不扣；
    - 0.5%~2%：轻微扣分；
    - >2%：明显扣分。
    """
    if pd.isna(selection_rate) or selection_rate <= 0:
        return 0.0
    if selection_rate <= TARGET_SELECTION_RATE:
        return 0.0
    if selection_rate <= MAX_OK_SELECTION_RATE:
        return (selection_rate - TARGET_SELECTION_RATE) * 500.0
    return 7.5 + (selection_rate - MAX_OK_SELECTION_RATE) * 1000.0


def calc_period_score(metric: dict, forward_day: int) -> dict:
    """
    中短线策略评分函数：适合 3/5/10/20/30 个交易日的策略信号验证。

    重要设计：
    1. raw_score 可以为负，用于排名和总分。
       原因：如果某个周期表现明显差，应该拖累总分；否则把负分抹成0会高估策略。

    2. score = max(0, raw_score)，只用于展示。
       这样 Excel 里既能看真实 raw_score，也能看非负展示分。

    3. 回撤惩罚不是“有回撤就扣很多”，而是“超过可容忍回撤才扣”。
       因为你做的是一周到一个月的短中线，正常回踩并不一定是坏事。

    4. 样本惩罚只保留“极小样本轻惩罚”。
       你希望筛出小样本，所以不再鼓励大样本，也不再因为 <30 样本就重扣。
    """
    sample_count = int(metric["sample_count"])
    avg_close_pct = metric["avg_close_pct"]
    win_rate = metric["win_rate"]  # 0~1
    avg_period_high_pct = metric["avg_period_high_pct"]
    avg_period_low_pct = metric["avg_period_low_pct"]
    std_close_pct = metric["std_close_pct"]

    # 收益权重：本版上调收益分比重。
    # 目的：让排名更偏向“第N日真实收益兑现”，而不是被胜率/冲高/样本数量过度影响。
    # 10/20日仍是核心，3日只是验证信号短期反应，30日看趋势延续。
    RETURN_WEIGHT_BY_DAY = {
        3: 6.0,
        5: 7.5,
        10: 10.0,
        20: 12.0,
        30: 10.0,
    }

    # 胜率基准：短周期要求略高；20/30日允许胜率略低但收益空间更大。
    WIN_RATE_BASE_BY_DAY = {
        3: 0.52,
        5: 0.52,
        10: 0.50,
        20: 0.48,
        30: 0.48,
    }

    # 周期容忍回撤：只惩罚超过正常波动的部分。
    # 单位是百分比，例如 20日容忍 -6%，表示平均区间最低回撤在 -6% 内不扣回撤分。
    TOLERATED_DRAWDOWN_BY_DAY = {
        3: 2.0,
        5: 3.0,
        10: 4.0,
        20: 6.0,
        30: 8.0,
    }

    # 回撤惩罚权重：周期越长，对正常回撤越宽容。
    DRAWDOWN_WEIGHT_BY_DAY = {
        3: 1.5,
        5: 1.3,
        10: 1.0,
        20: 0.8,
        30: 0.7,
    }

    return_weight = RETURN_WEIGHT_BY_DAY.get(forward_day, 6.0)
    win_base = WIN_RATE_BASE_BY_DAY.get(forward_day, 0.5)
    tolerated_drawdown = TOLERATED_DRAWDOWN_BY_DAY.get(forward_day, 5.0)
    drawdown_weight = DRAWDOWN_WEIGHT_BY_DAY.get(forward_day, 1.0)

    # 1. 收盘收益贡献：平均收益越高，分数越高。
    return_score = avg_close_pct * return_weight

    # 2. 胜率贡献：高于周期基准加分，低于周期基准扣分。
    # 乘以80而不是100，避免胜率过度压制“低胜率高盈亏比”的中线策略。
    win_score = (win_rate - win_base) * 80.0

    # 3. 冲高能力贡献：中短线策略常常需要中途止盈，所以区间最高收益要加分。
    high_score = avg_period_high_pct * 0.8

    # 4. 回撤惩罚：只惩罚“超过容忍回撤”的部分。
    # avg_period_low_pct 通常为负数，例如 -7.5。
    real_drawdown = abs(min(avg_period_low_pct, 0))
    excess_drawdown = max(0, real_drawdown - tolerated_drawdown)
    drawdown_penalty = excess_drawdown * drawdown_weight

    # 5. 波动惩罚：收益波动过大，说明策略稳定性差或依赖少数极端样本。
    volatility_penalty = std_close_pct * 0.4

    # 6. 样本惩罚：只对极小样本轻扣，不再因为 <30 就大幅扣分。
    sample_penalty = calc_small_sample_penalty(sample_count)

    raw_score = (
        return_score
        + win_score
        + high_score
        - drawdown_penalty
        - volatility_penalty
        - sample_penalty
    )

    display_score = max(0, raw_score)

    return {
        "raw_score": round(raw_score, 2),
        "score": round(display_score, 2),
        "return_score": round(return_score, 2),
        "win_score": round(win_score, 2),
        "high_score": round(high_score, 2),
        "drawdown_penalty": round(drawdown_penalty, 2),
        "volatility_penalty": round(volatility_penalty, 2),
        "sample_penalty": round(sample_penalty, 2),
        "tolerated_drawdown": tolerated_drawdown,
        "excess_drawdown": round(excess_drawdown, 2),
    }


def evaluate_combos(base_df: pd.DataFrame):
    """遍历所有组合，计算各周期分数、总分、梯度分布、明细。"""
    combos = generate_condition_combinations()
    print(f"共生成 {len(combos)} 个条件组合")

    period_rows = []
    rank_rows = []
    gradient_rows = []
    detail_rows = []

    # 这里的分母已经是 EPS + ST/BJ 过滤后的候选信号池。
    # base_df 每一行 = 某只股票在某个候选信号日。
    candidate_signal_count = len(base_df)
    candidate_stock_count = base_df["ts_code"].nunique() if not base_df.empty else 0
    signal_day_count = base_df["signal_date"].nunique() if not base_df.empty else 0

    for combo_index, combo in enumerate(combos, start=1):
        combo_id = f"S{combo_index:03d}"
        combo_name = combo_to_name(combo)

        mask = np.ones(len(base_df), dtype=bool)
        for key in combo:
            mask &= base_df[key].values

        combo_df = base_df[mask].copy()
        if combo_df.empty:
            continue

        selection_count = len(combo_df)
        selected_stock_count = combo_df["ts_code"].nunique()
        selected_signal_day_count = combo_df["signal_date"].nunique()
        avg_signals_per_day = selection_count / signal_day_count if signal_day_count else 0
        selection_rate = selection_count / candidate_signal_count if candidate_signal_count else 0
        selection_penalty = calc_selection_penalty(selection_rate)

        total_raw_score = 0.0
        total_display_score = 0.0
        total_weight = 0.0
        sample_count_max = 0

        for h in FORWARD_DAYS:
            hdf = combo_df[combo_df[f"valid_{h}"]].copy()
            hdf = hdf.dropna(subset=[f"close_pct_{h}", f"period_high_pct_{h}", f"period_low_pct_{h}"])

            sample_count = len(hdf)
            sample_count_max = max(sample_count_max, sample_count)
            if sample_count == 0:
                continue

            close_pct = hdf[f"close_pct_{h}"]
            period_high_pct = hdf[f"period_high_pct_{h}"]
            period_low_pct = hdf[f"period_low_pct_{h}"]

            metric = {
                "sample_count": sample_count,
                "avg_close_pct": close_pct.mean(),
                "median_close_pct": close_pct.median(),
                "win_rate": (close_pct > 0).mean(),
                "avg_period_high_pct": period_high_pct.mean(),
                "avg_period_low_pct": period_low_pct.mean(),
                "std_close_pct": close_pct.std(ddof=0),
                "best_close_pct": close_pct.max(),
                "worst_close_pct": close_pct.min(),
            }
            score_result = calc_period_score(metric, h)
            raw_score = score_result["raw_score"]
            score = score_result["score"]

            period_rows.append({
                "combo_id": combo_id,
                "combo_size": len(combo),
                "conditions": combo_name,
                "forward_day": h,
                "sample_count": sample_count,
                "raw_score": raw_score,
                "score": score,
                "return_score": score_result["return_score"],
                "win_score": score_result["win_score"],
                "high_score": score_result["high_score"],
                "drawdown_penalty": score_result["drawdown_penalty"],
                "volatility_penalty": score_result["volatility_penalty"],
                "sample_penalty": score_result["sample_penalty"],
                "tolerated_drawdown": score_result["tolerated_drawdown"],
                "excess_drawdown": score_result["excess_drawdown"],
                "avg_close_pct": round(metric["avg_close_pct"], 2),
                "median_close_pct": round(metric["median_close_pct"], 2),
                "win_rate_pct": round(metric["win_rate"] * 100, 2),
                "avg_period_high_pct": round(metric["avg_period_high_pct"], 2),
                "avg_period_low_pct": round(metric["avg_period_low_pct"], 2),
                "std_close_pct": round(metric["std_close_pct"], 2),
                "best_close_pct": round(metric["best_close_pct"], 2),
                "worst_close_pct": round(metric["worst_close_pct"], 2),
            })

            weight = PERIOD_WEIGHTS.get(h, 1 / len(FORWARD_DAYS))
            # 排名总分先使用 raw_score 加权，负分会参与总分；score 只是非负展示分。
            total_raw_score += raw_score * weight
            total_display_score += score * weight
            total_weight += weight

            # 梯度分布：看收益分布是否健康，避免平均值被少数大涨样本拉高。
            buckets = pd.cut(close_pct, bins=BUCKET_BINS, labels=BUCKET_LABELS)
            bucket_counts = buckets.value_counts().reindex(BUCKET_LABELS, fill_value=0)
            bucket_row = {
                "combo_id": combo_id,
                "conditions": combo_name,
                "forward_day": h,
                "sample_count": sample_count,
            }
            for label in BUCKET_LABELS:
                bucket_row[label] = int(bucket_counts[label])
            gradient_rows.append(bucket_row)

            # 明细数据可能比较大，但前期调试很有用。
            # 如果全市场跑很慢，可以注释这一段。
            for r in hdf.itertuples(index=False):
                detail_rows.append({
                    "combo_id": combo_id,
                    "conditions": combo_name,
                    "forward_day": h,
                    "ts_code": r.ts_code,
                    "name": r.name,
                    "signal_date": r.signal_date,
                    "base_close": r.base_close,
                    "future_date": getattr(r, f"future_date_{h}"),
                    "close_diff": getattr(r, f"close_diff_{h}"),
                    "close_pct": getattr(r, f"close_pct_{h}"),
                    "high_diff": getattr(r, f"high_diff_{h}"),
                    "high_pct": getattr(r, f"high_pct_{h}"),
                    "low_diff": getattr(r, f"low_diff_{h}"),
                    "low_pct": getattr(r, f"low_pct_{h}"),
                    "period_high_pct": getattr(r, f"period_high_pct_{h}"),
                    "period_low_pct": getattr(r, f"period_low_pct_{h}"),
                })

        if total_weight > 0:
            total_raw = total_raw_score / total_weight
            total_display = total_display_score / total_weight
            adjusted_total_raw = total_raw - selection_penalty

            rank_rows.append({
                "combo_id": combo_id,
                "combo_size": len(combo),
                "conditions": combo_name,
                "candidate_stock_count_after_eps_st": candidate_stock_count,
                "candidate_signal_count_after_eps_st": candidate_signal_count,
                "signal_day_count": signal_day_count,
                "selection_count": selection_count,
                "selected_stock_count": selected_stock_count,
                "selected_signal_day_count": selected_signal_day_count,
                "avg_signals_per_day": round(avg_signals_per_day, 2),
                "selection_rate_pct": round(selection_rate * 100, 4),
                "selection_penalty": round(selection_penalty, 2),
                "sample_count_max": sample_count_max,
                "total_raw_score": round(total_raw, 2),
                "adjusted_total_raw_score": round(adjusted_total_raw, 2),
                "total_score": round(total_display, 2),
            })

    rank_df = pd.DataFrame(rank_rows)
    period_df = pd.DataFrame(period_rows)
    gradient_df = pd.DataFrame(gradient_rows)
    detail_df = pd.DataFrame(detail_rows)

    if not rank_df.empty:
        # 追加每个周期的 raw_score/score 到总表，便于横向看哪种组合是短线强/中线强。
        # raw_score 可以为负，用于真实判断；score 是 max(0, raw_score)，仅用于展示。
        raw_score_pivot = period_df.pivot_table(
            index="combo_id",
            columns="forward_day",
            values="raw_score",
            aggfunc="first"
        ).reset_index()
        raw_score_pivot.columns = ["combo_id"] + [f"raw_score_{c}d" for c in raw_score_pivot.columns[1:]]

        score_pivot = period_df.pivot_table(
            index="combo_id",
            columns="forward_day",
            values="score",
            aggfunc="first"
        ).reset_index()
        score_pivot.columns = ["combo_id"] + [f"score_{c}d" for c in score_pivot.columns[1:]]

        sample_pivot = period_df.pivot_table(
            index="combo_id",
            columns="forward_day",
            values="sample_count",
            aggfunc="first"
        ).reset_index()
        sample_pivot.columns = ["combo_id"] + [f"sample_{c}d" for c in sample_pivot.columns[1:]]

        rank_df = rank_df.merge(raw_score_pivot, on="combo_id", how="left")
        rank_df = rank_df.merge(score_pivot, on="combo_id", how="left")
        rank_df = rank_df.merge(sample_pivot, on="combo_id", how="left")
        rank_df = rank_df.sort_values(
            ["adjusted_total_raw_score", "total_raw_score", "selection_count"],
            ascending=[False, False, True]
        ).reset_index(drop=True)
        rank_df.insert(0, "rank", range(1, len(rank_df) + 1))

    return rank_df, period_df, gradient_df, detail_df


# ======================
# 导出
# ======================

def save_outputs(rank_df, period_df, gradient_df, detail_df, base_df, run_summary_df):
    os.makedirs(os.path.dirname(RESULT_XLSX), exist_ok=True)
    os.makedirs(os.path.dirname(DETAIL_CSV), exist_ok=True)

    with pd.ExcelWriter(RESULT_XLSX, engine="openpyxl") as writer:
        rank_df.to_excel(writer, sheet_name="strategy_rank", index=False)
        period_df.to_excel(writer, sheet_name="period_scores", index=False)
        gradient_df.to_excel(writer, sheet_name="gradient", index=False)
        run_summary_df.to_excel(writer, sheet_name="run_summary", index=False)

        # 明细表可能非常大，Excel 单表最多 1048576 行；超出则只写前 100 万，完整明细写 CSV。
        if len(detail_df) <= 1_000_000:
            detail_df.to_excel(writer, sheet_name="detail", index=False)
        else:
            detail_df.head(1_000_000).to_excel(writer, sheet_name="detail_head", index=False)

        # 单项条件通过率，帮助你看哪个条件太苛刻。
        condition_stats = []
        for key in CONDITION_KEYS:
            condition_stats.append({
                "condition": key,
                "name": CONDITION_NAME.get(key, key),
                "pass_count": int(base_df[key].sum()) if not base_df.empty else 0,
                "total_count_after_eps_st": len(base_df),
                "pass_rate_pct": round(base_df[key].mean() * 100, 2) if not base_df.empty else 0,
            })
        pd.DataFrame(condition_stats).to_excel(writer, sheet_name="condition_stats", index=False)

    detail_df.to_csv(DETAIL_CSV, index=False, encoding="utf-8-sig")
    print(f"已导出：{RESULT_XLSX}")
    print(f"已导出明细CSV：{DETAIL_CSV}")


# ======================
# 主入口
# ======================

def main():
    end_date = sc.get_latest_completed_trade_date()
    trade_dates = get_score_trade_dates(end_date)
    signal_dates = trade_dates[-BACKTEST_SIGNAL_DAYS:]

    print(f"统计截止交易日：{end_date}")
    print(f"交易日窗口：{trade_dates[0]} ~ {trade_dates[-1]}，共 {len(trade_dates)} 个交易日")
    print(f"候选信号日：{signal_dates[0]} ~ {signal_dates[-1]}，共 {len(signal_dates)} 个交易日")
    print(f"观察周期：{FORWARD_DAYS} 个交易日")

    stock_pool = load_score_stock_pool()
    stock_info = {row["ts_code"]: row["name"] for _, row in stock_pool.iterrows()}
    ts_codes = list(stock_info.keys())
    print(f"股票池数量（ST/BJ过滤后，EPS/总市值过滤前）：{len(ts_codes)}")

    all_daily = sc.load_all_daily(ts_codes, trade_dates)
    if all_daily.empty:
        print("没有获取到日线数据")
        return
    if TOTAL_MV_FILTER_ENABLED:
        # 评分阶段与筛选阶段保持一致：总市值统一使用最近一个交易日口径。
        latest_total_mv_df = sc.load_latest_total_mv(ts_codes, trade_dates[-1])
        all_daily = all_daily.merge(latest_total_mv_df, on=["ts_code"], how="left")

    all_basic = load_all_basic(ts_codes, trade_dates, daily_df=all_daily)
    if not all_basic.empty:
        all_daily = all_daily.merge(
            all_basic,
            on=["ts_code", "trade_date"],
            how="left"
        )
    basic_columns = ["volume_ratio", "turnover_rate", "pe", "pe_ttm"]
    if EPS_FILTER_ENABLED:
        basic_columns.append("eps")
    if TOTAL_MV_FILTER_ENABLED:
        basic_columns.append("total_mv")
    for col in basic_columns:
        if col not in all_daily.columns:
            all_daily[col] = pd.NA
    print_basic_filter_stock_counts(all_daily, signal_dates, len(ts_codes))

    # 只要条件组合里包含资金流/内外盘相关条件，就需要资金流预计算。
    moneyflow_df = pd.DataFrame()
    if "main_money_inflow_2days" in CONDITION_KEYS or "external_internal_ratio_high" in CONDITION_KEYS:
        # 需要覆盖候选信号日以及它的前一日。
        signal_start_index = trade_dates.index(signal_dates[0])
        moneyflow_dates = trade_dates[max(0, signal_start_index - 1):]
        moneyflow_df = load_all_moneyflow(moneyflow_dates)

    shareholder_cache_ref = {
        "df": load_shareholder_cache_safe(),
        "dirty": False,
    }

    base_df = build_condition_base_df(
        all_daily,
        stock_info,
        signal_dates,
        moneyflow_df,
        shareholder_cache_ref,
    )
    if base_df.empty:
        print("没有生成候选信号表，请检查数据窗口、EPS过滤、ST过滤或股票池")
        return

    if shareholder_cache_ref.get("dirty"):
        save_shareholder_cache_safe(shareholder_cache_ref["df"])

    candidate_stock_count = base_df["ts_code"].nunique()
    candidate_signal_count = len(base_df)
    signal_day_count = base_df["signal_date"].nunique()
    avg_candidate_per_day = candidate_signal_count / signal_day_count if signal_day_count else 0

    print(
        f"候选信号表：{candidate_signal_count} 行；"
        f"EPS+总市值+ST/BJ过滤后股票数：{candidate_stock_count}；"
        f"平均每天候选数：{avg_candidate_per_day:.2f}"
    )

    rank_df, period_df, gradient_df, detail_df = evaluate_combos(base_df)

    if rank_df.empty:
        print("没有任何组合产生有效样本")
        return

    run_summary_df = pd.DataFrame([
        {"key": "end_date", "value": end_date},
        {"key": "trade_date_start", "value": trade_dates[0]},
        {"key": "trade_date_end", "value": trade_dates[-1]},
        {"key": "signal_date_start", "value": signal_dates[0]},
        {"key": "signal_date_end", "value": signal_dates[-1]},
        {"key": "forward_days", "value": str(FORWARD_DAYS)},
        {"key": "return_weight_mode", "value": "收益分权重已上调，排名更偏向真实收益兑现"},
        {"key": "stock_count_after_st_bj_before_eps_total_mv", "value": len(ts_codes)},
        {"key": "stock_count_after_eps_total_mv_st_bj", "value": candidate_stock_count},
        {"key": "candidate_signal_count_after_eps_total_mv_st_bj", "value": candidate_signal_count},
        {"key": "signal_day_count", "value": signal_day_count},
        {"key": "avg_candidate_per_day_after_eps_total_mv_st_bj", "value": round(avg_candidate_per_day, 2)},
        {"key": "target_selection_rate", "value": TARGET_SELECTION_RATE},
        {"key": "max_ok_selection_rate", "value": MAX_OK_SELECTION_RATE},
        {"key": "enable_eps_filter", "value": EPS_FILTER_ENABLED},
        {"key": "min_eps", "value": MIN_EPS},
        {"key": "enable_total_mv_filter", "value": TOTAL_MV_FILTER_ENABLED},
        {"key": "min_total_mv", "value": MIN_TOTAL_MV},
        {"key": "min_volume_ratio", "value": MIN_VOLUME_RATIO},
        {"key": "max_volume_ratio", "value": MAX_VOLUME_RATIO},
        {"key": "min_turnover_rate", "value": MIN_TURNOVER_RATE},
        {"key": "max_turnover_rate", "value": MAX_TURNOVER_RATE},
        {"key": "min_pe", "value": MIN_PE},
        {"key": "max_pe", "value": MAX_PE},
        {"key": "min_external_internal_ratio", "value": MIN_EXTERNAL_INTERNAL_RATIO},
        {"key": "max_external_internal_ratio", "value": MAX_EXTERNAL_INTERNAL_RATIO},
    ])

    save_outputs(rank_df, period_df, gradient_df, detail_df, base_df, run_summary_df)

    print("\n===== Top 20 策略组合 =====")
    print(rank_df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
