# Local development PostgreSQL (no system install)

`npm install` in this folder downloads the official PostgreSQL 17 binaries packaged by
`@embedded-postgres/windows-x64` (swap the package for `darwin-arm64`, `linux-x64`, ... on
other platforms). `python scripts/devdb.py start` initialises a cluster in `tools/devdb/pgdata`
(git-ignored) and runs it on port 5433 in user space. Nothing is installed as a system service.

Production / deployment uses a managed PostgreSQL (see `docker-compose.yml` and `render.yaml`).
