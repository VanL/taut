"""Internal search projection and provider primitives.

Spec references:
- docs/specs/06-search.md [SRCH-3.1], [SRCH-6.1], [SRCH-7], [SRCH-11.1]
"""

from taut.search._projection import projection_segments, query_chunks, segment_text

__all__ = ["projection_segments", "query_chunks", "segment_text"]
