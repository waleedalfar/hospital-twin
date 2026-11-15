"""Rollback proposals (extra X3): the live model is flagged for replacement when it stops doing what it did on
validation. Two triggers: the AUROC on recent labelled data falls more than 0.05 below the validation AUROC, or more
than three features have drifted past PSI 0.3. A person confirms in the UI; nothing is swapped automatically."""

from dataclasses import dataclass
from datetime import datetime

from twin.ml.governance import DriftReading

AUROC_DROP = 0.05
DRIFT_PSI = 0.3
DRIFT_FEATURES = 3
PREFERRED = ("lgbm-v1", "fed-mlp-v1")  # the order in which a replacement is chosen


@dataclass(frozen=True)
class Proposal:
    reason: str  # "live_auroc_drop" or "drift_spread"
    detail: str
    from_version: str
    to_version: str
    created: datetime


def pick_target(active: str, available: list[str]) -> str | None:
    """The version to roll back to: the first preferred one that is not live, else any other."""
    others = [v for v in available if v != active]
    for version in PREFERRED:
        if version in others:
            return version
    return sorted(others)[0] if others else None


def propose(
    live_auroc: float | None,
    validation_auroc: float | None,
    drift: list[DriftReading],
    active: str,
    available: list[str],
    now: datetime,
) -> Proposal | None:
    """A proposal if a trigger fires and there is another version to go to, else None."""
    target = pick_target(active, available)
    if target is None:
        return None
    if live_auroc is not None and validation_auroc is not None and live_auroc < validation_auroc - AUROC_DROP:
        detail = f"AUROC on recent labelled data is {live_auroc:.3f}, more than {AUROC_DROP} below validation ({validation_auroc:.3f})"
        return Proposal("live_auroc_drop", detail, active, target, now)
    drifted = sorted({r.feature for r in drift if r.psi > DRIFT_PSI})
    if len(drifted) > DRIFT_FEATURES:
        detail = f"{len(drifted)} features have drifted past PSI {DRIFT_PSI}: {', '.join(drifted[:6])}"
        return Proposal("drift_spread", detail, active, target, now)
    return None
