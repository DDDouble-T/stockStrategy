import pandas as pd
import datetime
import csv
from constants import *

def calcul_buy_signal(tickers: pd.core.series.Series, code_dict):
    file_name = "../data/daily_" + START_DATE + "_" + END_DATE + ".h5"
    hdf5 = pd.HDFStore(file_name, "r")
    all_stocks = hdf5['data']
    hdf5.close()

    amount_pct_match_ticker = []
    industry_num_dict = {}

    for ticker in tickers:
        try:
            ticker_info = all_stocks.loc[ticker]
        except:
            continue

        last_day_pct_chg = ticker_info.loc[ticker_info.index[0]]['pct_chg']
        last_day_amount = ticker_info.loc[ticker_info.index[0]]['amount']

        # 当日上涨7%以上
        if last_day_pct_chg >= 7:
            industry = code_dict[ticker]['industry']
            name = code_dict[ticker]['name']

            if industry in industry_num_dict.keys():
                num = industry_num_dict[industry]
                num = num + 1
                industry_num_dict[industry] = num
            else:
                industry_num_dict[industry] = 1

            df_without_last_row = ticker_info[1:]
            sum_of_amount = df_without_last_row.loc[:, ['amount']].mean()[0]

            # 放量
            if last_day_amount/sum_of_amount >= 2:
                amount_pct_match_ticker.append(
                    {
                        "ts_code": ticker,
                        "pct_chg": last_day_pct_chg,
                        "last_day_amount": last_day_amount,
                        "amount_pct": last_day_amount / sum_of_amount
                    }
                                                )

    result_list = []

    for ticker_dict in amount_pct_match_ticker:
        ts_code = ticker_dict['ts_code']
        industry = code_dict[ts_code]['industry']
        name = code_dict[ts_code]['name']

        num = industry_num_dict[industry]

        # 同行业4个以上股票涨幅超7%
        if  num >=4 :
            result_list.append([
                ts_code,
                name,
                industry,
                ticker_dict["pct_chg"],
                ticker_dict["last_day_amount"],
                ticker_dict["amount_pct"]
            ])

    result_list.sort(key=lambda item: item[5], reverse=True)

    final_result_list = []
    final_result_list.append(['股票代码', '股票名称', '行业', '最近一个交易日涨幅', '最近一个交易日成交额', '成交额比例'])
    final_result_list = final_result_list + result_list
    file_name = "../data/sort_daily_" + START_DATE + "_" + END_DATE + ".csv"
    with open(file_name,'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(final_result_list)


def calcul_sell_signal(ticker_dicts: list, start_time: datetime):
    print(1111)


if __name__ == '__main__':
    hdf5 = pd.HDFStore("../data/stock_basic.h5", "r")
    stock_basic_df = hdf5['stock_basic']
    hdf5.close()

    my_tickers = stock_basic_df['ts_code']

    code_dict = {}
    for index, row in stock_basic_df.iterrows():
        ts_code = row['ts_code']
        name = row['name']
        industry = row['industry']
        code_dict[ts_code] = {'name':name, 'industry':industry}

    calcul_buy_signal(my_tickers, code_dict)
