import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import time
import pandas as pd


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


def multiple_stocks(tickers, start_date, end_date, func):
    def data(ticker):

        stocks = func(ticker, start_date, end_date)
        if 'trade_date' in stocks.columns:
            stocks.set_index('trade_date', inplace=True)
            stocks.index = pd.to_datetime(stocks.index)
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

    return result