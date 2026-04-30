import os


# 开始日期
START_DATE = "20250530"
# 结束日期
END_DATE = "20250606"
CURRENT_DATE = "2025-06-05"

SHARE_DATA_DIR = "/Users/tengteng/other/shareData"
DATA_DIR = os.path.join(SHARE_DATA_DIR, "data")
SCORE_RESULT_DIR = os.path.join(SHARE_DATA_DIR, "scoreResult")


def data_path(filename):
    return os.path.join(DATA_DIR, filename)


def score_result_path(filename):
    return os.path.join(SCORE_RESULT_DIR, filename)
