import pandas as pd


def save_hdf5(filename, df, key):
    hdf5 = pd.HDFStore(filename, "w")
    hdf5.open()
    hdf5[key] = df
    hdf5.close()


def load_hdf5(filename, key):
    hdf5 = pd.HDFStore(filename, "r")
    df = hdf5[key]
    hdf5.close()

    return df