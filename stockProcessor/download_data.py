import tushare as ts
import pandas as pd
from datetime import datetime, timedelta
import concurrent.futures
import time
from concurrent.futures import ThreadPoolExecutor


def parallel_map(func, iterable):
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        results = executor.map(func, iterable)
        return list(results)

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
            return [stocks, ticker]

        return None

    datas = map_with_minute_limit(data, tickers, 400)
    filtered_data = [x for x in datas if x is not None]

    stock_data = []
    final_tickers = []
    for item in filtered_data:
        stock_data.append(item[0])
        final_tickers.append(item[1])

    result = pd.concat(stock_data, keys=final_tickers, names=['Ticker', 'Date'])

    hdf5 = pd.HDFStore("data/get_k_data_2024-09-22.h5", "w")
    hdf5.open()
    hdf5['get_k_data'] = result
    hdf5.close()

    return result


if __name__ == '__main__':
    now = datetime.now()
    hdf5 = pd.HDFStore("data/stock_basic.h5", "r")
    stock_basic_df = hdf5['stock_basic']
    hdf5.close()

    my_tickers = stock_basic_df['symbol']
    # my_tickers = pd.Series(['002827', '603129', '300827', '002827', '002294'])
    # my_tickers = ['002827', '603129', '300827', '002827', '002294']
    all_stocks = multiple_stocks(my_tickers, 168, now)
    print(1111)