# taut-pg

Postgres support package for Taut.

This package is intentionally separate from the core `taut-chat`
distribution. It installs `simplebroker-pg` in the same environment as the
`taut` CLI so `.taut.toml` can select the public SimpleBroker Postgres
backend.

## Requirements

- Python 3.11+
- PostgreSQL
- A dedicated schema for Taut and SimpleBroker tables
- Core distribution `taut-chat` and extension `taut-pg` installed in the same
  environment

The Postgres database must already exist. `taut init` initializes the configured
schema and tables inside that database; it does not create the database.

The package also supplies Taut's PostgreSQL search provider. It uses only
PostgreSQL's built-in `tsvector`, `pg_catalog.simple` configuration, GIN, and
advisory locks. It never requires `CREATE EXTENSION` or a separately compiled
server extension.

## Installation

The core distribution is `taut-chat`; it still installs the `taut` command and
import package. `taut-pg` keeps its own distribution name and
`taut_pg/vX.Y.Z` tag stream. Once the first coordinated PyPI release is
published:

```bash
pipx install taut-chat
pipx inject taut-chat taut-pg
```

The tag gate reuses the exact wheel and sdist built by canonical Test. It
stages them in a draft GitHub Release, publishes them through the
`taut-pg` top-level PyPI Trusted Publisher, verifies filenames and SHA-256
digests, and only then publishes the GitHub Release as immutable.

## Configuration

Create `.taut.toml` in the project root:

```toml
version = 1
backend = "postgres"
target = "postgresql://postgres:postgres@127.0.0.1:54329/taut_test"

[backend_options]
schema = "taut_project"
```

The credentials above are for a disposable local test database. A real target
DSN may contain a password and must be treated as a secret. If `.taut.toml`
contains one, add the file to your project's `.gitignore`, do not commit
production credentials, and restrict it to the owner on POSIX systems (for
example, `chmod 600 .taut.toml`). Taut does not interpolate environment
variables in this file.

Then initialize Taut normally:

```bash
taut init
taut join general
```

`taut init` initializes the configured schema and tables; it does not
provision the database. `taut init --json` reports `db` as the resolved
backend display target, and for Postgres `created` is `false` because
Taut has no public backend creation signal.

`TAUT_DB`, `--db`, and `db_path=` remain filesystem path selectors. Use
`.taut.toml` to select Postgres.

## Testing

From the repository root:

```bash
uv run ./bin/pytest-pg
```

That helper starts a temporary Docker Postgres container, runs shared Taut tests
against Postgres, runs `pg_only` extension tests, and removes the container.
