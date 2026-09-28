"""Research module.

Public dataset manifest types and helpers, the scored-window pin, and
the trial record log. The module owns the content-addressed dataset
record, the coverage label, the window-pin store, and the per-trial
record. It does not own network IO, the OS keyring, or pack
evaluation; those concerns live elsewhere and are composed by the
caller.
"""

from __future__ import annotations

from .datasets import DatasetManifest, coverage_label, manifest_for
from .experiments import DuplicateTrial, record_trial
from .windows import WindowChanged, pin_window

__all__ = [
    "DatasetManifest",
    "DuplicateTrial",
    "WindowChanged",
    "coverage_label",
    "manifest_for",
    "pin_window",
    "record_trial",
]
