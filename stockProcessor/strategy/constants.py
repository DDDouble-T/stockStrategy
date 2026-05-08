from module.config import tushare_config


# 开始日期
START_DATE = "20250530"
# 结束日期
END_DATE = "20250606"
CURRENT_DATE = "2025-06-05"

SHARE_DATA_DIR = tushare_config.ShareDataConst.SHARE_DATA_DIR
DATA_DIR = tushare_config.ShareDataConst.DATA_DIR
RESULT_DIR = tushare_config.ShareDataConst.RESULT_DIR
SCORE_RESULT_DIR = RESULT_DIR


def data_path(filename):
    return tushare_config.data_path(filename)


def result_path(filename):
    return tushare_config.result_path(filename)


def score_result_path(filename):
    return result_path(filename)
