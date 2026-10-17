"""Research module.

Public dataset manifest types and helpers, the scored-window pin, the
trial record log, and the holdout disjointness check. The module owns
the content-addressed dataset record, the coverage label, the
window-pin store, the per-trial record, and the predicate that
refuses a score whose window touches the holdout. It does not own
network IO, the OS keyring, or pack evaluation; those concerns live
elsewhere and are composed by the caller.
"""

from __future__ import annotations

from .datasets import DatasetManifest, coverage_label, manifest_for
from .experiments import DuplicateTrial, record_trial
from .holdout import HoldoutOverlap, assert_disjoint
from .windows import WindowChanged, pin_window

__all__ = [
    "DatasetManifest",
    "DuplicateTrial",
    "HoldoutOverlap",
    "WindowChanged",
    "assert_disjoint",
    "coverage_label",
    "manifest_for",
    "pin_window",
    "record_trial",
]
