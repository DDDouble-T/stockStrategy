from datetime import datetime, timedelta
import tushare as ts
import pandas as pd


if __name__ == '__main__':
    # pro = ts.pro_api(token='')
    #
    # # 查询当前所有正常上市交易的股票列表
    # data = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
    # hdf5 = pd.HDFStore("data/stock_basic.h5", "w")
    # hdf5.open()
    # hdf5['stock_basic'] = data
    # hdf5.close()

    # 获取当前日期
    now = datetime.now()

    # 计算168天前的日期
    days_before = now - timedelta(days=168)

    # 格式化输出168天前的日期
    formatted_date = days_before.strftime('%Y-%m-%d')
    formatted_currentdate = now.strftime('%Y-%m-%d')

    print(formatted_date)
    print(formatted_currentdate)
    print(type(datetime.now()))

