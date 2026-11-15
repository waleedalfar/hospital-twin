"""Time-based splits shared by the models: later rows never train a model that is validated on earlier ones."""

from dataclasses import dataclass

import pandas as pd

TRAIN_FRAC = 0.6
VAL_FRAC = 0.2


@dataclass
class Split:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


def split_by_time(rows: pd.DataFrame, train_frac: float = TRAIN_FRAC, val_frac: float = VAL_FRAC) -> Split:
    """Split rows by sim time so that every validation row is later than every training row, and so on."""
    ordered = rows.sort_values("minute", kind="stable")
    low, high = float(ordered["minute"].min()), float(ordered["minute"].max())
    cut1 = low + (high - low) * train_frac
    cut2 = low + (high - low) * (train_frac + val_frac)
    minute = ordered["minute"]
    return Split(ordered[minute <= cut1], ordered[(minute > cut1) & (minute <= cut2)], ordered[minute > cut2])
