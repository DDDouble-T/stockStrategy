import os

from module.config import local_tushare_config


class TuShareConst:
    TOKEN = local_tushare_config.TOKEN


class ShareDataConst:
    SHARE_DATA_DIR = getattr(local_tushare_config, "SHARE_DATA_DIR", "/Users/tengteng/other/shareData")
    DATA_DIR = getattr(local_tushare_config, "DATA_DIR", os.path.join(SHARE_DATA_DIR, "data"))
    RESULT_DIR = getattr(local_tushare_config, "RESULT_DIR", os.path.join(SHARE_DATA_DIR, "result"))


def data_path(filename):
    if hasattr(local_tushare_config, "data_path"):
        return local_tushare_config.data_path(filename)
    return os.path.join(ShareDataConst.DATA_DIR, filename)


def result_path(filename):
    if hasattr(local_tushare_config, "result_path"):
        return local_tushare_config.result_path(filename)
    return os.path.join(ShareDataConst.RESULT_DIR, filename)
