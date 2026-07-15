# taut-pg

Postgres support package for Taut.

This package is intentionally separate from `taut`. It installs
`simplebroker-pg` in the same environment as the Taut CLI so `.taut.toml` can
select the public SimpleBroker Postgres backend.

## Requirements

- Python 3.11+
- PostgreSQL
- A dedicated schema for Taut and SimpleBroker tables
- Core `taut` and `taut-pg` installed in the same environment

The Postgres database must already exist. `taut init` initializes the configured
schema and tables inside that database; it does not create the database.

## Installation

Taut releases are GitHub-only until package-name clearance changes. Install the
core package first, then inject a compatible extension wheel from the extension
GitHub Release into the same environment. `taut-pg` uses its own
`taut_pg/vX.Y.Z` tag stream, so its version can differ from the core package
version:

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.7.0"
pipx inject taut ./taut_pg-0.7.0-py3-none-any.whl
```

Do not use a PyPI install command for `taut-pg` until the project documents
PyPI publication.

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

`TAUT_DB`, `--db`, and `db_path=` remain filesystem path selectors. Use
`.taut.toml` to select Postgres.

## Testing

From the repository root:

```bash
uv run ./bin/pytest-pg
```

That helper starts a temporary Docker Postgres container, runs shared Taut tests
against Postgres, runs `pg_only` extension tests, and removes the container.
