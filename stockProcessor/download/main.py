import tushare as ts
from matplotlib import pyplot as plt
import numpy as np
import pandas as pd
import seaborn


def multiple_stocks(tickers):
    def data(ticker):
        stocks = ts.get_k_data(ticker, '2024-08-01', '2024-09-04')
        stocks.set_index('date', inplace=True)
        stocks.index = pd.to_datetime(stocks.index)
        return stocks

    datas = map(data, tickers)
    return pd.concat(datas, keys=tickers, names=['Ticker', 'Date'])


if __name__ == '__main__':
    tickers = ['600030','000001','600426']
    all_stocks = multiple_stocks(tickers)
    # print(all_stocks.tail())
    # print(all_stocks[['close']].tail)
    close_price = all_stocks[['close']].reset_index()
    daily_close = close_price.pivot(index = 'Date', columns='Ticker', values='close')
    # print(daily_close.head())
    # data = ts.get_stock_basics("2024-09-02")
    # print(data.head())
    # df = ts.get_k_data('600030', '2024-08-01', '2024-09-04')
    # df.set_index('date', inplace=True)
    # type(df)
    # print(df.head())
    # hdf5 = pd.HDFStore("data/hs300_2024-08-01_2024-09-04.h5","w")
    # hdf5.open()
    # hdf5['data'] = df
    # hdf5.close()

    # profit_data = ts.get_profit_data(2017, 1)
    # print(profit_data.head())

    # hdf5 = pd.HDFStore("data/hs300_2024-08-01_2024-09-04.h5","r")
    # data_read = hdf5['data']
    # print(data_read.head())
    # hdf5.close()
    # del df['date']
    # print(df.tail())

    # ds = pd.Series(df['close'], index=df['date'])
    # plt.plot(df['close'])
    # plt.show()

    # np.random.seed(100)
    # data = np.random.standard_normal((5,100))
    # x= np.arange(len(data.cumsum()))
    # y= data.cumsum()
    # rg1 = np.polyfit(x,y,1)
    # rg2 = np.polyfit(x, y, 2)
    # rg3 = np.polyfit(x, y, 3)
    # plt.figure(figsize=(10,6))
    # plt.plot(x,y,'r',label='data')
    # plt.plot(x, np.polyval(rg1, x), 'b--', label='linear')
    # plt.plot(x, np.polyval(rg2, x), 'g-', label='quadratic')
    # plt.plot(x, np.polyval(rg3, x), 'm:', label='cubic')
    # plt.show()

    # ds = pd.Series(range(10,20))
    # print(ds[ds>15].values)
    #
    # array = np.random.randn(6,4)
    # df = pd.DataFrame(array, columns = ['a','b','c','d'], index = ['1','2','3','4','5','6'])
    # print(df.head())

#计算每日收益
    # price_change = daily_close/daily_close.shift(1)-1
    # print(price_change.head())
    price_change = daily_close.pct_change()
    # print(price_change.iloc[:,0:2].head())
    price_change.fillna(0, inplace=True)
# 计算累积收益
    # cum_daily_return = (1+price_change).cumprod()
    # plt.figure(figsize=(10,6))
    #
    # fig, ax = plt.subplots()
    # for i, column in enumerate(cum_daily_return):
    #     ax.plot(cum_daily_return[column], label=column)
    #
    # plt.show()

# 股价分布
    # zxzq = price_change['600030']
    # 绘制频数分布直方图，分析中信证券的return分布
    # price_change.hist(bins=50,sharex=True,figsize=(12,8))
    # plt.figure(figsize=(10, 6))
    # plt.hist(price_change)
    # plt.show()

    # print(zxzq.describe())
    # zxzq.describe(percentiles=[0.025, 0.5, 0.975])
    #
    # # QQ plots： 使用QQ图来验证股价return分布
    # fig = plt.figure(figsize=(7,5))
    # ax = fig.add_subplot(111)
    # stats.probplot(zxzq, dist='norm', plot=plt)
    # plt.show()

# 股价return相关性
    # 两只股票的相关性
    # 一只股票和沪深300指数的相关性
    # seaborn热力图找到股价两两之间的相关性

    # 计算hs300指数收益
    hs300 = ts.get_k_data('hs300', '2024-08-01', '2024-09-04')
    hs300.set_index('date', inplace=True)
    hs300_return = hs300['close'].pct_change().fillna(0)
    print(hs300_return.head())

    # 将hs300的数据，加入旧的收益表中
    return_all = pd.concat([hs300_return, price_change], axis=1)
    return_all.rename(columns={'close':'hs300'}, inplace=True)

    # 计算四个资产累积收益
    cumreturn_all = (1+return_all).cumprod()

    # 累积收益作图
    cumreturn_all[['hs300','600030','600426']].plot(figsize=(8,6))

    # 计算相关性
    corrs = return_all.corr()
    # corrs.loc('hs300')
    # 热力图求股票两两之间的相关性
    fig = plt.figure(figsize=(8,6))
    seaborn.heatmap(corrs,vmin=0.4)
    plt.show()
    # 两个股票之间的相关性，散点图
    plt.figure(figsize=(8,6))
    plt.title('Stock Correlation')
    plt.plot(daily_close['600030'], daily_close['000001'], '.')
    plt.xlabel('600030')
    plt.ylabel('000001')

    plt.show()