"""Research module.

Public dataset manifest types and helpers, plus the scored-window pin.
The module owns the content-addressed dataset record, the coverage
label, and the window-pin store. It does not own network IO, the OS
keyring, or pack evaluation; those concerns live elsewhere and are
composed by the caller.
"""

from __future__ import annotations

from .datasets import DatasetManifest, coverage_label, manifest_for
from .windows import WindowChanged, pin_window

__all__ = [
    "DatasetManifest",
    "WindowChanged",
    "coverage_label",
    "manifest_for",
    "pin_window",
]
