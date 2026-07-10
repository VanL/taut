"""Shared public-client member lookup for Summon entry points."""

from __future__ import annotations

from taut import TautClient
from taut.client import Member


def find_member(client: TautClient, name: str) -> Member | None:
    """Resolve a current member name or alias through the public client API."""

    wanted = name.lower()
    for member in client.who():
        if member.name.lower() == wanted:
            return member
        if any(alias.lower() == wanted for alias in member.aliases):
            return member
    return None
