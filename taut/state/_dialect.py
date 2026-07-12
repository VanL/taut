"""SQL dialect marker for Taut-owned sidecar state.

The SQL state adapter uses qmark SQL that SimpleBroker translates for supported
backends. This marker selects the few backend capabilities the adapter cannot
express portably, such as PostgreSQL transaction-scoped advisory locking. SQL
stays in ``taut.state._sql``; this module does not own SQL fragments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from simplebroker import BrokerTarget

SqlDialectName = Literal["portable", "sqlite", "postgres"]


@dataclass(frozen=True, slots=True)
class SqlDialect:
    """Identify the SQL shape used by a Taut state adapter."""

    name: SqlDialectName


PORTABLE_SQL_DIALECT = SqlDialect("portable")
SQLITE_SQL_DIALECT = SqlDialect("sqlite")
POSTGRES_SQL_DIALECT = SqlDialect("postgres")


def dialect_for_taut_target(target: BrokerTarget | str) -> SqlDialect:
    """Return the SQL dialect for a target resolved by Taut.

    This is deliberately narrower than arbitrary ``Queue.db_target`` handling:
    in Taut, a plain string target is an explicit SQLite filesystem path. A bare
    string obtained elsewhere may be a backend DSN and must not be passed here.
    """

    if isinstance(target, str):
        return SQLITE_SQL_DIALECT
    if target.backend_name == "sqlite":
        return SQLITE_SQL_DIALECT
    if target.backend_name == "postgres":
        return POSTGRES_SQL_DIALECT
    raise RuntimeError(
        f"unsupported SQL sidecar backend for taut state: {target.backend_name}"
    )
