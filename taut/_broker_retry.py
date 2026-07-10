"""Import-only compatibility boundary for pre-reactor Summon releases.

Taut no longer owns broker retry classification. SimpleBroker 5.2.0 owns
storage retry, while current Taut and Summon own handle lifecycle only. The
previously published Summon package imports this private symbol at module load,
so removing the module would break the paired core-first rollout before its
version guard can run. Any attempt to execute the obsolete classifier fails
closed with an upgrade diagnostic instead of restoring the 5.1-era policy.
"""

from __future__ import annotations


def is_transient_broker_error(exc: Exception) -> bool:
    """Reject execution of the retired Taut-owned retry classifier."""

    del exc
    raise RuntimeError(
        "Taut-owned broker retry was removed; upgrade taut-summon and use "
        "SimpleBroker 5.2.0 or newer"
    )


__all__ = ["is_transient_broker_error"]
