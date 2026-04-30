import tushare as ts
from ..config import tushare_config


def stock_basic():
    pro = ts.pro_api(token=tushare_config.TuShareConst.TOKEN)
    data = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')

    return data