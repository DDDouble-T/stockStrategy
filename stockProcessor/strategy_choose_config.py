ACTIVE_STRATEGY = "sharechoose"


DEFAULT_CONFIG = {
    # 拉取最近多少个交易日的日线数据；需覆盖指标计算、信号筛选和后续表现回看窗口。
    "data_lookback_trade_days": 120,
    # 交易日收盘小时；当前时间早于该小时且当天是交易日时，默认回退到上一交易日。
    "market_close_hour": 15,
    # bak_basic 接口限频等待秒数。
    "bak_basic_min_interval_seconds": 30,
    # 在最近多少个交易日内逐日筛选信号；不能大于 data_lookback_trade_days。
    "signal_days": 30,
    # 信号出现后最多向后统计多少个交易日表现；None 表示统计到已拉取数据末尾。
    "max_forward_days": None,
    # 成交量均线窗口，用于判断上涨放量、回调缩量。
    "vol_ma_days": 5,
    # RSI 计算周期，周期越短越敏感。
    "rsi_period": 6,
    # RSI 上限，超过该值视为短期过热并过滤。
    "rsi_max": 70,
    # 股价接近 10/20 日均线的允许偏离比例，0.015 表示 1.5%。
    "near_ma_threshold": 0.015,
    # 突破前高时回看多少个交易日的最高价作为压力位。
    "recent_high_lookback_days": 20,
    # 上一年度每 10 股税前现金分红下限，单位与 TuShare dividend.cash_div_tax 保持一致。
    "prev_year_min_cash_div_tax": 1.0,
    # 是否启用每股收益 EPS 基础过滤；关闭后不拉取 EPS，也不按 EPS 过滤。
    "enable_eps_filter": True,
    # 每股收益 EPS 基础过滤下限；仅在 enable_eps_filter 为 True 且 eps 有值时生效。
    "min_eps": 0.2,
    # 是否启用总市值基础过滤；关闭后不按 total_mv 过滤。
    "enable_total_mv_filter": True,
    # 总市值基础过滤下限；开启过滤后，按最近一个交易日拉取的 total_mv 过滤。
    # TuShare daily_basic.total_mv 单位为万元；500000 万元 = 50 亿元。
    "min_total_mv": 500000.0,
    # 量比下限。
    "min_volume_ratio": 1.0,
    # 外盘 / 内盘下限；外盘按 moneyflow 主动买入成交量合计，内盘按主动卖出成交量合计。
    "min_external_internal_ratio": 1.05,
    # 换手率下限，单位为百分比，1.0 表示 1%。
    "min_turnover_rate": 1.0,
    # 换手率上限，单位为百分比，12.0 表示 12%。
    "max_turnover_rate": 12.0,
    # 市盈率上限；同时会过滤小于等于 0 的市盈率。
    "max_pe": 80.0,
    # 是否排除名称包含 ST 的股票，包括 ST、*ST 等风险股。
    "exclude_st_stocks": True,
    # 条件开关说明：
    # trend_above_ma20: 股价在20日线之上
    # bullish_ma_alignment: 5日 > 10日 > 20日
    # volume_rule: 上涨放量或回调缩量
    # position_rule: 回踩10/20日线缩量，或突破前高放量
    # macd_golden_cross: MACD金叉
    # rsi_not_overheated: RSI 不超过阈值
    # volume_ratio_high: 量比不低于
    # external_internal_ratio_high: 外盘 / 内盘不低于1.05
    # turnover_rate_range: 换手率在设定区间内 1-12
    # pe_reasonable: 市盈率在合理区间 0-80
    # social_security_holder: 股东成分包含全国社保基金
    # prev_year_high_dividend: 上一年度现金分红较高，10股税前大于1
    # main_money_inflow_2days: 主力资金连续流入2天
    "conditions": {
        "trend_above_ma20": False,
        "bullish_ma_alignment": True,
        "volume_rule": True,
        "position_rule": True,
        "macd_golden_cross": False,
        "rsi_not_overheated": True,
        "volume_ratio_high": True,
        "external_internal_ratio_high": False,
        "turnover_rate_range": True,
        "pe_reasonable": True,
        "social_security_holder": False,
        "prev_year_high_dividend": False,
        "main_money_inflow_2days": True,
    },
}


STRATEGY_PRESETS = {
    "sharechoose": {
        "description": "强化版 ShareChoose，基础过滤每股盈利和 ST，增加换手量比、外盘内盘比、换手率、市盈率、社保基金股东成分。",
    },
    "balanced": {
        "description": "默认均衡策略，保留当前技术面、分红和资金流条件。",
        "conditions": {
            "volume_ratio_high": False,
            "external_internal_ratio_high": False,
            "turnover_rate_range": False,
            "pe_reasonable": False,
            "social_security_holder": False,
        },
    },
    "trend_relaxed": {
        "description": "偏技术趋势，去掉分红和主力资金限制，便于扩大候选。",
        "signal_days": 10,
        "conditions": {
            "volume_ratio_high": False,
            "external_internal_ratio_high": False,
            "turnover_rate_range": False,
            "pe_reasonable": False,
            "social_security_holder": False,
            "prev_year_high_dividend": False,
            "main_money_inflow_2days": False,
        },
    },
    "dividend_quality": {
        "description": "偏分红质量，保留趋势条件，提高上一年度分红门槛。",
        "signal_days": 15,
        "prev_year_min_cash_div_tax": 2.0,
        "conditions": {
            "volume_ratio_high": False,
            "external_internal_ratio_high": False,
            "turnover_rate_range": False,
            "pe_reasonable": True,
            "social_security_holder": True,
            "main_money_inflow_2days": False,
        },
    },
}
