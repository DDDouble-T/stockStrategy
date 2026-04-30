import pandas as pd
import tushare as ts
from datetime import datetime
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import os
import time
from constants import *
from module.config import tushare_config



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


def save_hdf5(filename, df, key):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    hdf5 = pd.HDFStore(filename, "w")
    hdf5.open()
    hdf5[key] = df
    hdf5.close()


def load_hdf5(filename, key):
    hdf5 = pd.HDFStore(filename, "r")
    df = hdf5[key]
    hdf5.close()

    return df

def daily_api(ts_code, start_date, end_date):
    pro = ts.pro_api(tushare_config.TuShareConst.TOKEN)
    # df = pro.daily(ts_code='000001.SZ,600000.SH', start_date='20180701', end_date='20180718')
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

    return df


def multi_daily_api(ts_code_list, start_date, end_date):


    df_list = []
    sub_lists = [ts_code_list[i::40] for i in range(40)]

    for sub_list in sub_lists:
        df = daily_api(",".join(sub_list), start_date, end_date)
        df_list.append(df)

    return pd.concat(df_list)


def weekly_api(ts_code, start_date, end_date):
    pro = ts.pro_api(tushare_config.TuShareConst.TOKEN)
    # df = pro.weekly(ts_code='000001.SZ', start_date='20180101', end_date='20181101',
    #                 fields='ts_code,trade_date,open,high,low,close,vol,amount')
    df = pro.weekly(ts_code=ts_code, start_date=start_date, end_date=end_date,fields='ts_code,trade_date,open,high,low,close,vol,amount')

    return df

def monthly_api(ts_code, start_date, end_date):
    pro = ts.pro_api(tushare_config.TuShareConst.TOKEN)

    # df = pro.monthly(ts_code='000001.SZ', start_date='20180101', end_date='20181101',fields='ts_code,trade_date,open,high,low,close,vol,amount')
    df = pro.monthly(ts_code=ts_code, start_date=start_date, end_date=end_date,
                     fields='ts_code,trade_date,open,high,low,close,vol,amount')

    return df


def multiple_stocks(tickers, start_date, end_date, func):
    now = datetime.now()
    time_string = now.strftime('%Y-%m-%d %H:%M:%S')

    print(time_string + " start process tickers: "+ str(len(tickers)))

    def data(ticker):

        stocks = func(ticker, start_date, end_date)
        if 'trade_date' in stocks.columns:
            stocks.set_index('trade_date', inplace=True)
            stocks.index = pd.to_datetime(stocks.index)
            # if len(stocks) == 0:
            #     time.sleep(1)
            return [stocks, ticker]

        return None

    datas = map(data, tickers)

    filtered_data = [x for x in datas if x is not None]

    stock_data = []
    final_tickers = []
    for item in filtered_data:
        stock_data.append(item[0])
        final_tickers.append(item[1])

    result = pd.concat(stock_data, keys=final_tickers, names=['Ticker', 'Date'])

    now = datetime.now()
    time_string = now.strftime('%Y-%m-%d %H:%M:%S')
    print(time_string + " end process tickers: " + str(len(tickers)))
    return result


if __name__ == '__main__':
    print(ts.__version__)
    stock_basic_df = load_hdf5(data_path("stock_basic.h5"), 'stock_basic')
    my_tickers = stock_basic_df['ts_code']
    file_name = data_path("daily_" + START_DATE + "_" + END_DATE + ".h5")
    all_stocks = multiple_stocks(my_tickers, START_DATE, END_DATE, daily_api)
    save_hdf5(file_name, all_stocks, 'data')
    #
    # all_stocks = multiple_stocks(my_tickers, '20240101', '20240925', weekly_api)
    # save_hdf5("data/weekly_20240101_20240925.h5", all_stocks, 'data')
    #


    # all_stocks = multiple_stocks(my_tickers, '20230101', '20231231', weekly_api)
    # save_hdf5("data/weekly_20230101_20231231.h5", all_stocks, 'data')

    # all_stocks = multiple_stocks(my_tickers, '20220101', '20221231', weekly_api)
    # save_hdf5("data/weekly_20220101_20221231.h5", all_stocks, 'data')
    #
    # all_stocks = multiple_stocks(my_tickers, '20210101', '20211231', weekly_api)
    # save_hdf5("data/weekly_20210101_20211231.h5", all_stocks, 'data')
    # all_stocks = multiple_stocks(my_tickers, '20200101', '20201231', weekly_api)
    # save_hdf5("data/weekly_20200101_20201231.h5", all_stocks, 'data')
    # all_stocks = multiple_stocks(my_tickers, '20190101', '20191231', weekly_api)
    # save_hdf5("data/weekly_20190101_20191231.h5", all_stocks, 'data')
    #
    # all_stocks = multiple_stocks(my_tickers, '20180101','20181231', weekly_api)
    # save_hdf5("data/weekly_20180101_20181231.h5", all_stocks , 'data')

