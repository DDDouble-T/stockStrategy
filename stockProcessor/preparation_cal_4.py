import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from module.config import tushare_config

# 初始化Tushare
pro = ts.pro_api(tushare_config.TuShareConst.TOKEN)


def get_stock_data(ts_code, days):
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    return df.sort_values('trade_date') if not df.empty else df


def check_first_condition(df):
    if len(df) < 121: return False, ""

    df_window = df.tail(121)
    low_idx = df_window['close'].values.argmin()
    low_price = df_window.iloc[low_idx]['close']

    # 寻找最低点后的最高点
    high_idx = df_window.iloc[low_idx:]['close'].values.argmax() + low_idx
    high_price = df_window.iloc[high_idx]['close']

    # 检查涨幅
    if (high_price - low_price) / low_price < 0.4:
        return False, ""

    # 计算成交量比率
    # 区间最低的日成交额
    prev_vol = df_window['amount'].values.argmin()
    # 最高点往前推9天，然后加当天，总共10天的平均成交额
    current_start = max(0, high_idx - 9)
    current_vol = df_window.iloc[current_start:high_idx + 1]['amount'].mean()

    return current_vol >= 2 * prev_vol


def check_second_condition(df):
    if len(df) < 21: return False

    df_window = df.tail(21)
    low_idx = df_window['close'].values.argmin()
    low_price = df_window.iloc[low_idx]['close']

    # 寻找最低点后的最高点
    high_idx = df_window.iloc[low_idx:]['close'].values.argmax() + low_idx
    high_price = df_window.iloc[high_idx]['close']

    # 检查涨幅
    if (high_price - low_price) / low_price < 0.2:
        return False

    # 计算成交量比率
    # 区间最低的日成交额
    prev_vol = df_window['amount'].values.argmin()
    # 最高点往前推4天，然后加当天，总共5天的平均成交额
    current_start = max(0, high_idx - 4)
    current_vol = df_window.iloc[current_start:high_idx + 1]['amount'].mean()

    return current_vol >= 2 * prev_vol


def check_ma_condition(df):
    if len(df) < 20: return False
    ma20 = df['close'].iloc[-20:].mean()
    ma10 = df['close'].iloc[-10:].mean()
    close = df.iloc[-1]['close']
    # 踩均线 并且 均线多头分布
    return 0.94 * ma20 <= close <= 1.06 * ma20 , ma10 >= ma20


# 主程序
stock_list = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
selected = []
multihead_selected = []

for _, row in stock_list.iterrows():
    try:
        df = get_stock_data(row['ts_code'], 200)
        if df.empty: continue

        if not  check_first_condition(df): continue
        if not check_second_condition(df): continue
        touch_ma20, multihead = check_ma_condition(df)
        if not touch_ma20: continue

        selected.append({
            '代码': row['ts_code'],
            '名称': row['name'],
            '收盘价': df.iloc[-1]['close'],
            '20日均价': df['close'].iloc[-20:].mean(),
            '触发日期': df.iloc[-1]['trade_date']
        })

        if multihead:
            multihead_selected.append({
            '代码': row['ts_code'],
            '名称': row['name'],
            '收盘价': df.iloc[-1]['close'],
            '20日均价': df['close'].iloc[-20:].mean(),
            '触发日期': df.iloc[-1]['trade_date']
        })

    except Exception as e:
        print(f"处理{row['ts_code']}时出错: {str(e)}")

# 展示结果
result_df = pd.DataFrame(selected)
print(f"符合条件股票数量（二段上涨、踩均线）: {len(result_df)}")
result_df.to_csv('result_1.csv', index=False, sep=',', line_terminator='\n', encoding='utf-8')
print(result_df)

multihead_result_df = pd.DataFrame(multihead_selected)
multihead_result_df.to_csv('result_2.csv', index=False, sep=',', line_terminator='\n', encoding='utf-8')
print(f"符合条件股票数量(二段上涨、踩均线、均线多头): {len(multihead_result_df)}")
print(multihead_result_df)
