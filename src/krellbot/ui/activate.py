"""Legacy dashboard alias for :mod:`krellbot.application.license_activation`.

Activation redeem lives in the application layer. The legacy dashboard
still imports it from here until the dashboard is removed. The alias
replaces this module in ``sys.modules`` so ``krellbot.ui.activate`` and
the application module are the same object: there is one ``redeem`` and
one set of helpers, whichever name the caller uses.
"""

from __future__ import annotations

import sys

from krellbot.application import license_activation

sys.modules[__name__] = license_activation
