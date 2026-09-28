"""Research module.

Public dataset manifest types and helpers. The module owns the
content-addressed dataset record and the coverage label. It does not own
network IO, the OS keyring, or pack evaluation; those concerns live
elsewhere and are composed by the caller.
"""

from __future__ import annotations

from .datasets import DatasetManifest, coverage_label, manifest_for

__all__ = ["DatasetManifest", "coverage_label", "manifest_for"]
