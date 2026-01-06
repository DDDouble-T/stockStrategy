strategy/strategy_short_term.py（短线涨停+放量+行业共振）
- 数据源：读取 ../data/daily_{START_DATE}_{END_DATE}.h5 的 data 表（Tushare pro 日线数据）
- 买入信号 calcul_buy_signal：
    - 当日涨幅 ≥ 7%。
    - 行业计数：记录同一行业涨停个数。
    - 放量判定：把最近一行之外的其余行求 amount 均值，若当日成交额 / 均值 ≥ 2 认为放量。
    - 行业共振：同一行业涨停数量 ≥ 4 才入选。
    - 输出字段：代码、名称、行业、涨幅、成交额、放量倍数（降序排序）
- 卖出信号（占位）

strategy_mid_term.py（中线趋势+量价配合）
- 数据源：调用 ts.get_k_data 抓过去 before_days（默认示例 168 天）到指定 start_time 的 K 线，或者直接读现存 HDF5 data/get_k_data_2024-09-22.h5。
- 买入信号 calcul_buy_signal：
  - 找区间内最低价日期 min_index 与最高价日期 max_index，要求时间上先低后高，且涨幅 ≥ 40%。
  - 成交量放大：低点到高点区间的日均成交量 / 之前同长度区间日均成交量 ≥ 2。
  - 价格位置：最近一天的最低价 ≤ 50 日均价。
  - 命中则记录最低/最高日期与价、区间/前区间量均、最近低点、50 日均价。
  - 返回字典；主流程示例把结果写 data/buy_result.csv。
- 卖出信号 calcul_sell_signal：
    - 输入持仓列表含 code/buy_date/buy_price。
    - 规则：跌破买价 -5% 直接卖；持有 ≥5 天且涨幅 ≤5% 卖；否则若涨幅>5%，但收盘价 ≤ 10 日均价则卖。
