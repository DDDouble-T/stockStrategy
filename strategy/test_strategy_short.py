import pandas as pd
import datetime
import csv


def cal_buy_and_sell():
    industry_num_dict = {}

    hdf5 = pd.HDFStore("../data/stock_basic.h5", "r")
    stock_basic_df = hdf5['stock_basic']
    hdf5.close()

    code_dict = {}
    for index, row in stock_basic_df.iterrows():
        ts_code = row['ts_code']
        name = row['name']
        industry = row['industry']
        code_dict[ts_code] = {'name':name, 'industry':industry}

    hdf5 = pd.HDFStore("../data/daily_20240101_20240925.h5", "r")
    all_stocks = hdf5['data']
    hdf5.close()

    ts_codes = all_stocks.index.get_level_values(0).values
    for ts_code in ts_codes:
        ticker_info = all_stocks.loc[ts_code]

        date_indexes = ticker_info.index.values
        for current_date in date_indexes:

            industry = code_dict[ts_code]['industry']
            name = code_dict[ts_code]['name']

            if industry in industry_num_dict.keys():
                date_dict = industry_num_dict[industry]
                num = 1
                if current_date in date_dict.keys():
                    num = date_dict[current_date]
                    num = num + 1
                industry_num_dict[industry] = {current_date: num}
            else:
                industry_num_dict[industry] = {current_date:1}

            current_row = ticker_info.loc[current_date]
            last_day_amount = current_row['amount']
            last_day_close = current_row['close']
            rows = ticker_info.loc[ticker_info.index <= current_date].head(6)

            row_len = len(rows)
            if row_len == 6:
                df_without_last_row = rows[1:]
                df_without_first_row = rows[:row_len-1]
                sum_of_amount = df_without_last_row.loc[:, ['amount']].mean()[0]
                # pct_close_price = df_without_first_row.loc[:, ['amount']].mean()[0]
                #
                # row_2 = ticker_info[1:2]
                # row_3 = ticker_info[2:3]

                all_stocks.loc[(ts_code, current_date), 'pct_amount'] = sum_of_amount/last_day_amount
                # all_stocks.loc[(ts_code, current_date), 'after_one_day_pct_chg'] = (last_day_close/row_2['close'][0])-1
                # all_stocks.loc[(ts_code, current_date), 'after_two_day_pct_chg'] = (last_day_close / row_3['close'][0]) - 1
                # all_stocks.loc[(ts_code, current_date), 'after_one_day'] = row_2.index[0]
                # all_stocks.loc[(ts_code, current_date), 'after_two_day'] = row_3.index[0]
                # all_stocks.loc[(ts_code, current_date), 'pct_price_cp'] = last_day_close-pct_close_price

            else:
                all_stocks.loc[(ts_code, current_date), 'pct_amount'] = 0
                all_stocks.loc[(ts_code, current_date), 'after_one_day_pct_chg'] = 0
                all_stocks.loc[(ts_code, current_date), 'after_two_day_pct_chg'] = 0
                all_stocks.loc[(ts_code, current_date), 'after_one_day'] = 0
                all_stocks.loc[(ts_code, current_date), 'after_two_day'] = 0
                all_stocks.loc[(ts_code, current_date), 'pct_price_cp'] = 0

    for ts_code in ts_codes:
        ticker_info = all_stocks.loc[ts_code]
        date_indexes = ticker_info.index.values
        for current_date in date_indexes:
            try:
                industry = code_dict[ts_code]['industry']
                num = industry_num_dict[industry][current_date]
            except:
                all_stocks.loc[(ts_code, current_date), 'industry_num'] = 0
                continue

            all_stocks.loc[(ts_code, current_date), 'industry_num'] = num


    result_list = []

    for ts_code in ts_codes:
        ticker_info = all_stocks.loc[ts_code]
        date_indexes = ticker_info.index.values

        industry = code_dict[ts_code]['industry']
        name = code_dict[ts_code]['name']

        for current_date in date_indexes:
            current_row = ticker_info.loc[current_date]
            pct_chg = current_row['pct_chg']
            industry_num = current_row['industry_num']
            pct_amount = current_row['pct_amount']
            close_price = current_row['close']

            if pct_chg >= 7 and industry_num>=4:
                result_list.append([
                    ts_code,
                    name,
                    industry,
                    current_date.strftime('%Y-%m-%d'),
                    close_price,
                    pct_chg,
                    pct_amount
                ])

    result_list.sort(key=lambda item: item[4], reverse=True)

    final_result_list = []
    final_result_list.append(['股票代码', '股票名称', '行业','交易日','收盘价', '最近一个交易日涨幅', '成交额比例'])
    final_result_list = final_result_list + result_list

    with open("../data/sort_daily_20240101_20240925.csv", 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(final_result_list)


if __name__ == '__main__':
    cal_buy_and_sell()