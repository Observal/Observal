# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Generate service configuration files for embedded mode.

Creates minimal, locally-tuned configs for PostgreSQL and Redis that bind to
127.0.0.1 on non-standard ports.  The DuckDB analytics service needs no config
file: its settings travel in the process environment.
"""

from __future__ import annotations

import secrets
from textwrap import dedent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli.server.constants import (
    CONFIG_DIR,
    LOG_DIR,
    POSTGRES_PORT,
    REDIS_PORT,
    RUN_DIR,
    get_data_paths,
)


def generate_secret(length: int = 32) -> str:
    """Generate a URL-safe random secret."""
    return secrets.token_urlsafe(length)


def ensure_dirs() -> None:
    """Create all required directories."""
    data_paths = get_data_paths()
    for d in [CONFIG_DIR, LOG_DIR, RUN_DIR, *data_paths.values()]:
        d.mkdir(parents=True, exist_ok=True)


def generate_postgres_conf() -> Path:
    """Generate postgresql.conf for embedded mode.

    Returns path to the generated config file.
    """
    conf_path = CONFIG_DIR / "postgresql.conf"

    content = dedent(f"""\
        # Observal embedded PostgreSQL configuration
        # Auto-generated - do not edit manually

        listen_addresses = '127.0.0.1'
        port = {POSTGRES_PORT}
        max_connections = 30
        shared_buffers = 128MB
        work_mem = 4MB
        maintenance_work_mem = 64MB
        effective_cache_size = 256MB

        # WAL
        wal_level = minimal
        max_wal_senders = 0
        fsync = on
        synchronous_commit = off

        # Logging
        log_destination = 'stderr'
        logging_collector = off
        log_min_messages = warning

        # Connection
        unix_socket_directories = '{RUN_DIR}'

        # Data
        dynamic_shared_memory_type = posix
    """)

    conf_path.write_text(content)
    return conf_path


def generate_pg_hba_conf() -> Path:
    """Generate pg_hba.conf allowing local TCP connections with password."""
    hba_path = get_data_paths()["postgres"] / "pg_hba.conf"

    content = dedent("""\
        # Observal embedded PostgreSQL HBA
        # Auto-generated - do not edit manually
        # Trust-based auth is safe here: server binds to 127.0.0.1 only.

        # TYPE  DATABASE  USER       ADDRESS        METHOD
        local   all       all                       trust
        host    all       all        127.0.0.1/32   trust
        host    all       all        ::1/128        trust
    """)

    hba_path.write_text(content)
    return hba_path


def generate_redis_conf() -> Path:
    """Generate Redis config for embedded mode.

    Returns path to the generated config file.
    """
    conf_path = CONFIG_DIR / "redis.conf"
    data_path = get_data_paths()["redis"]
    log_path = LOG_DIR / "redis.log"
    pid_path = RUN_DIR / "redis.pid"

    content = dedent(f"""\
        # Observal embedded Redis configuration
        # Auto-generated - do not edit manually

        bind 127.0.0.1
        port {REDIS_PORT}
        daemonize no
        pidfile {pid_path}

        # Persistence
        dir {data_path}
        save 900 1
        save 300 10
        save 60 10000
        dbfilename dump.rdb

        # Memory
        maxmemory 128mb
        maxmemory-policy allkeys-lru

        # Logging
        logfile {log_path}
        loglevel warning

        # Performance
        tcp-backlog 128
        timeout 300
        tcp-keepalive 60
    """)

    conf_path.write_text(content)
    return conf_path


def generate_all_configs() -> dict[str, Path]:
    """Generate all service configurations.

    Returns dict mapping service name to config file path.
    """
    ensure_dirs()
    return {
        "postgres": generate_postgres_conf(),
        "redis": generate_redis_conf(),
    }
