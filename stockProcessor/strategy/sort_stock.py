import pandas as pd
import csv


if __name__ == '__main__':
    hdf5 = pd.HDFStore("../data/daily_20250421_20250430.h5","r")
    all_stocks = hdf5['data']
    hdf5.close()

    hdf5 = pd.HDFStore("../data/stock_basic.h5", "r")
    stock_basic_df = hdf5['stock_basic']
    hdf5.close()

    code_dict = {}
    for index, row in stock_basic_df.iterrows():
        ts_code = row['ts_code']
        name = row['name']
        industry = row['industry']
        code_dict[ts_code] = {'name':name, 'industry':industry}


    my_tickers = stock_basic_df['ts_code']

    pct_change_dict = {}
    for ticker in my_tickers:
        try:
            ticker_info = all_stocks.loc[ticker]
        except:
            continue

        last_day_close = ticker_info.loc[ticker_info.index[0]]['close']
        first_day_close = ticker_info.loc[ticker_info.index[-1]]['close']

        pct_change = last_day_close/first_day_close - 1
        pct_change_dict[ticker] = pct_change

    sorted_dict = dict(sorted(pct_change_dict.items(), key=lambda x: x[1]))
    result_list = []
    result_list.append(['股票代码', '区间收益率', '股票名称', '行业'])
    for code in sorted_dict.keys():
        pct_change = sorted_dict[code]

        name = code_dict[code]['name']
        industry = code_dict[code]['industry']
        result_list.append([
            code,
            pct_change,
            name,
            industry
        ])

    with open("../data/sort_stock_20240923_20241010.csv", 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(result_list)

