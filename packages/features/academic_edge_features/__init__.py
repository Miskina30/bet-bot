"""Feature building for Academic Edge.

Public surface::

    from academic_edge_features import (
        FeatureBuilder, FeatureVector,
        FormRecord, FormTracker, decay_weight, rest_days,
    )
"""

from __future__ import annotations

from academic_edge_features.form import (
    FormRecord,
    FormTracker,
    congestion,
    days_between,
    decay_weight,
    rest_days,
)
from academic_edge_features.strength import FeatureBuilder, FeatureVector

__all__ = [
    "FeatureBuilder",
    "FeatureVector",
    "FormRecord",
    "FormTracker",
    "congestion",
    "days_between",
    "decay_weight",
    "rest_days",
]