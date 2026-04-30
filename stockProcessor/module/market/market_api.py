from module.config import tushare_config
from module.common import tushare_parallel,hdf5_util
import tushare as ts
import pandas as pd


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


def multi_weekly_api(tickers, start_date, end_date):
    def data(ticker):
        stocks = weekly_api(ticker, start_date, end_date)
        return [stocks, ticker]

    datas = map(data, tickers)
    # datas = tushare_parallel.map_with_minute_limit(data, tickers, 50)

    filtered_data = [x for x in datas if x is not None]
    stock_data = []
    final_tickers = []
    for item in filtered_data:
        stock_data.append(item[0])
        final_tickers.append(item[1])

    result = pd.concat(stock_data, keys=final_tickers, names=['Ticker', 'Date'])
    return result


def monthly_api(ts_code, start_date, end_date):
    pro = ts.pro_api(tushare_config.TuShareConst.TOKEN)

    # df = pro.monthly(ts_code='000001.SZ', start_date='20180101', end_date='20181101',fields='ts_code,trade_date,open,high,low,close,vol,amount')
    df = pro.monthly(ts_code=ts_code, start_date=start_date, end_date=end_date,
                     fields='ts_code,trade_date,open,high,low,close,vol,amount')

    return df


def stk_weekly_monthly(ts_code,start_date,end_date,freq):
    pro = ts.pro_api(tushare_config.TuShareConst.TOKEN)
    # df = pro.stk_weekly_monthly('000001.SZ', '20180101', '20181101', 'week/month')
    df = pro.stk_weekly_monthly(ts_code, start_date, end_date, freq)

    return df


if __name__ == '__main__':
    # stock_basic_df = hdf5_util.load_hdf5("../../data/stock_basic.h5", 'stock_basic')
    # my_tickers = stock_basic_df['ts_code']
    # df = multi_weekly_api(my_tickers, '20240916', '20240920')
    # print(df.head())
    # hdf5_util.save_hdf5("../../data/week_20240920.h5", df , 'week_20240920')

    # week_20240920_df = hdf5_util.load_hdf5("../../data/week_20240920.h5", "week_20240920")
    # week_20240920_df['change'] = week_20240920_df['close'].div(week_20240920_df['open']) - 1
    # sorted_df = week_20240920_df.sort_values(by='change', ascending=False)
    # sorted_df.to_csv('../../data/week_20240920.csv', index=False)
    # print(week_20240920_df.head())

    # df1 = daily_api("000001.SZ", "20240917", "20240919")
    # df = daily_api("000001.SZ", "20240920", "20240925")


    df1 = daily_api("000001.SZ", "20180101", "20181231")
    df1 = daily_api("000001.SZ", "20190101", "20191231")
    df1 = daily_api("000001.SZ", "20200101", "20201231")
    df1 = daily_api("000001.SZ", "20210101", "20211231")
    df1 = daily_api("000001.SZ", "20220101", "20221231")
    df1 = daily_api("000001.SZ", "20230101", "20231231")
    df1 = daily_api("000001.SZ", "20240101", "20240925")
    print(df1.head())
    print(1111)

