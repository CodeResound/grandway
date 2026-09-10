"""Gunicorn configuration for Grandway — reference, adapt to the host.

Usage:
    gunicorn --chdir backend --config deploy/gunicorn.conf.py core.wsgi:application

`--chdir backend` is required: the Django project lives under backend/, and
`core` is only importable from there.
"""

import multiprocessing
import os

# -- Networking ---------------------------------------------------------------
# Loopback only. TLS is terminated by the reverse proxy, which is the only
# thing that should be able to reach this socket. Binding 0.0.0.0 would expose
# an unencrypted origin that bypasses every proxy-enforced guarantee.
bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")

# -- Workers ------------------------------------------------------------------
# Sync workers: this application is database-bound, not IO-concurrent, and uses
# no async views.
#
# *** Worker count is coupled to CACHE_BACKEND. *** DRF throttle counters live
# in the cache; with the per-process LocMemCache every rate limit is multiplied
# by this number. Production settings refuse to start on LocMemCache unless
# THROTTLE_SINGLE_WORKER=true is set. Use a shared cache for workers > 1.
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
threads = 1

# -- Timeouts -----------------------------------------------------------------
# Keep `timeout` above the slowest legitimate request. Bulk document and
# reporting endpoints are the long tail here.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 60))
graceful_timeout = 30
# Slightly above the proxy's own keepalive so gunicorn is never the side that
# closes a connection mid-response.
keepalive = 5

# -- Worker recycling ---------------------------------------------------------
# Bounds the blast radius of any slow leak. The jitter prevents every worker
# from recycling on the same request count and briefly emptying the pool.
max_requests = 1000
max_requests_jitter = 100

# -- Logging ------------------------------------------------------------------
# Access and error logs go to stdout/stderr for the supervisor (systemd,
# Docker) to collect. This is deliberate and is the multi-worker-safe path.
#
# NOTE: Django's own LOGGING additionally writes a RotatingFileHandler under
# LOG_DIR. That handler is NOT multiprocess-safe — with workers > 1, plus the
# nightly cron writing to the same file, rollover races can lose a whole
# segment. Known limitation for 1.0.0 (see deploy.md §10 (Process model)); the stdout stream
# below is the reliable one.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# Log the real client IP forwarded by the proxy, not the proxy's own address.
access_log_format = '%({X-Forwarded-For}i)s %(t)s "%(r)s" %(s)s %(b)s %(D)sus "%(a)s"'

# -- Process ------------------------------------------------------------------
proc_name = "grandway"
# preload_app=True would save memory but breaks worker-level recycling of the
# database connections opened at import; left off deliberately.
preload_app = False
