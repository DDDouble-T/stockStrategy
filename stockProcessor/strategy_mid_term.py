import tushare as ts
import pandas as pd
from datetime import datetime, timedelta
import csv
import concurrent.futures
import time
from concurrent.futures import ThreadPoolExecutor
from constants import *


def map_with_minute_limit(func, iterable, max_per_minute):
    start_time = time.time()
    items_processed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_item = {executor.submit(func, item): item for item in iterable}
        while future_to_item or (time.time() - start_time < 60):
            finished, _ = concurrent.futures.wait(
                future_to_item,
                timeout=60 / max_per_minute
            )
            for future in finished:
                item = future_to_item[future]
                exception = future.exception()
                if exception:
                    raise exception
                yield future.result()
                del future_to_item[future]
                items_processed += 1
                if (time.time() - start_time >= 60):
                    break
                elif len(future_to_item) < max_per_minute:
                    item = next(iterable)
                    future = executor.submit(func, item)
                    future_to_item[future] = item


def multiple_stocks(tickers, before_days: int, start_time: datetime):
    days_before = start_time - timedelta(days=before_days)
    current_date = start_time.strftime('%Y-%m-%d')
    last_120_date = days_before.strftime('%Y-%m-%d')

    def data(ticker):

        stocks = ts.get_k_data(ticker, last_120_date, current_date)
        if 'date' in stocks.columns:
            stocks.set_index('date', inplace=True)
            stocks.index = pd.to_datetime(stocks.index)
            return stocks

        return None

    datas = map_with_minute_limit(data, tickers, 400)
    filtered_data = [x for x in datas if x is not None]

    stock_data = []
    final_tickers = []
    for item in filtered_data:
        stock_data.append(item[0])
        final_tickers.append(item[1])

    result = pd.concat(stock_data, keys=final_tickers, names=['Ticker', 'Date'])

    # hdf5 = pd.HDFStore("data/get_k_data_2024-09-22.h5", "w")
    # hdf5.open()
    # hdf5['get_k_data'] = result
    # hdf5.close()

    return result


def calcul_buy_signal(tickers: pd.core.series.Series, start_time: datetime):
    result_dict = {}
    hdf5 = pd.HDFStore("data/get_k_data_2024-09-22.h5", "r")
    all_stocks = hdf5['get_k_data']
    hdf5.close()

    # all_stocks = multiple_stocks(tickers, 168, start_time)

    unique_index_values = set(all_stocks.index)

    for ticker in tickers:
        try:
            ticker_info = all_stocks.loc[ticker]
        except:
            continue

        min_index = ticker_info['close'].idxmin()
        max_index = ticker_info['close'].idxmax()
        close_min = ticker_info['close'].min()
        close_max = ticker_info['close'].max()

        if (max_index > min_index and close_max / close_min >= 1.4):
            # 比较成交量
            target_section_df = ticker_info.loc[min_index:max_index]
            before_target_section_df = ticker_info.loc[:min_index].tail(len(target_section_df))

            target_section_df_len = len(target_section_df)
            before_target_section_df_len = len(before_target_section_df)

            if target_section_df_len<=0:
                target_section_df_len = 1

            if before_target_section_df_len <= 0:
                before_target_section_df_len = 1

            target_section_volume_sum = target_section_df['volume'].sum()/target_section_df_len
            before_target_section_volume_sum = before_target_section_df['volume'].sum()/before_target_section_df_len

            if target_section_volume_sum / before_target_section_volume_sum >= 2:
                # 比较均值
                last_low_price = ticker_info.tail(1)['low'][0]
                before_51days_df = ticker_info.tail(51)
                before_50days_df = before_51days_df.drop(before_51days_df.index[-1])
                before_50days_df_len = len(before_50days_df)
                if before_50days_df_len <= 0:
                    before_50days_df_len = 1

                percent_50days_price = before_50days_df['close'].sum() / before_50days_df_len

                if last_low_price <= percent_50days_price:
                    result_dict[ticker] = {
                        'min_date': min_index.strftime('%Y-%m-%d'),
                        'close_min': close_min,
                        'max_date': max_index.strftime('%Y-%m-%d'),
                        'close_max': close_max,
                        'target_section_volume_sum': target_section_volume_sum,
                        'before_target_section_volume_sum': before_target_section_volume_sum,
                        'last_low_price': last_low_price,
                        'percent_50days_price': percent_50days_price
                                              }
    return result_dict


def calcul_sell_signal(ticker_dicts: list, start_time: datetime):
    result_dict = {}

    ticker_codes = []
    ticker_code_dict = {}
    for ticker_item in ticker_dicts:
        ticker_codes.append(ticker_item['code'])
        ticker_code_dict[ticker_item['code']] = ticker_item

    all_stocks = multiple_stocks(ticker_codes, 20, start_time)

    for ticker_code in ticker_codes:
        ticker_info = all_stocks.loc[ticker_code]

        buy_info_dict = ticker_code_dict[ticker_code]
        last_close_price = ticker_info.tail(1)['close'][0]

        buy_date = datetime.strptime(buy_info_dict['buy_date'], "%Y-%m-%d")
        ticker_after_buy_info = ticker_info.loc[buy_date:]

        # 收盘价跌至买入价格的-5%; 直接卖出
        if last_close_price <= buy_info_dict['buy_price'] * 0.95:
            result_dict[ticker_code] = {"buy_date":buy_info_dict['buy_date'], "buy_price": buy_info_dict['buy_price']}
        elif len(ticker_after_buy_info) >= 5:
            # 持有5天以上
            if last_close_price <= 1.05 * buy_info_dict['buy_price'] :
                # 静止5天后，涨幅小于等于5%；直接卖出
                result_dict[ticker_code] = {"buy_date":buy_info_dict['buy_date'], "buy_price": buy_info_dict['buy_price']}
            else:
                # 达到涨幅要求,判断均线
                ticker_info_tail10days_len = len(ticker_info.tail(10))
                if ticker_info_tail10days_len <= 0:
                    ticker_info_tail10days_len = 1
                percent_10days_price = ticker_info.tail(10)['close'].sum() / ticker_info_tail10days_len
                if last_close_price <= percent_10days_price:
                    result_dict[ticker_code] = {"buy_date":buy_info_dict['buy_date'],}
    return result_dict


if __name__ == '__main__':
    now = datetime.now()

    # 可以用test_date 当做今天，来进行任何一天的测试
    test_date = datetime.strptime("2024-04-24", "%Y-%m-%d")

    # 用今天开始往前120个交易日的数据，计算下一个交易日可以买的股票
    hdf5 = pd.HDFStore("data/stock_basic.h5", "r")
    stock_basic_df = hdf5['stock_basic']
    hdf5.close()

    my_tickers = stock_basic_df['symbol']
    # my_tickers = ['002827','603129','300827','002827','002294']
    buy_stock_dict = calcul_buy_signal(my_tickers, now)

    result_list = []
    result_list.append(['股票代码','最低点日期', '最低点收盘价', '最高点日期','最高点收盘价','区间成交量(日均)','前一区间成交量（日均）','上一交易日最低价格','50日均价'])
    for code  in buy_stock_dict.keys():
        result_dict = buy_stock_dict[code]
        result_list.append([
            code,
            result_dict['min_date'],
            result_dict['close_min'],
            result_dict['max_date'],
            result_dict['close_max'],
            result_dict['target_section_volume_sum'],
            result_dict['before_target_section_volume_sum'],
            result_dict['last_low_price'],
            result_dict['percent_50days_price'],
        ])

    with open("data/buy_result.csv", 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(result_list)

    print(buy_stock_dict)

    # 计算应该卖出的股票
    # exist_my_tickers = [
    #     {"code":"600030", "buy_date":"2024-09-16", "buy_price":19.93},
    #     {"code": "000001", "buy_date": "2024-09-16", "buy_price": 19.93},
    # ]
    #
    # sell_stock_dict = calcul_sell_signal(exist_my_tickers, now)
    # print(sell_stock_dict)