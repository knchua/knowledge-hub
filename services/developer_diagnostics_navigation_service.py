"""R6.5-E: fail-closed navigation gate for dormant synthetic diagnostics.

No UI is visible unless the explicit environment flag is enabled AND the
actor passes the existing R6.5-C freshly verified admin / developer allowlist.
Do not use navigation visibility as the page's authorization boundary.
"""
from __future__ import annotations

import os


def developer_navigation_allowed(actor: object) -> bool:
    if os.environ.get('KH_PHASE5_DEV_DIAGNOSTICS_ENABLED') != '1':
        return False
    try:
        from services.synthetic_diagnostic_service import _developer
        _developer(actor)
        return True
    except Exception:
        return False
