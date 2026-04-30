import tushare as ts

if __name__ == '__main__':
    df = ts.get_stock_basics()
    print(df.head())