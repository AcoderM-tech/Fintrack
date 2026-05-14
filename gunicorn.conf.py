# gunicorn.conf.py — Production Gunicorn configuration
# Place in project root alongside manage.py
# Run: gunicorn fintrack.wsgi:application -c gunicorn.conf.py

import multiprocessing
import os

# ─── Binding ──────────────────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")

# ─── Workers ──────────────────────────────────────────────────────────────────
# 2-4 x CPU cores is a good starting point for sync workers
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
worker_connections = 1000  # used only for async workers

# ─── Timeouts ─────────────────────────────────────────────────────────────────
timeout = 30        # Kill workers that take longer than 30s
keepalive = 2       # Keep alive for 2s after last request
graceful_timeout = 30

# ─── Request limits ───────────────────────────────────────────────────────────
max_requests = 1000             # Restart worker after N requests (prevent memory leaks)
max_requests_jitter = 100       # Randomise restart to avoid thundering herd

# ─── Logging ──────────────────────────────────────────────────────────────────
accesslog = "-"    # stdout
errorlog  = "-"    # stderr
loglevel  = os.getenv("GUNICORN_LOG_LEVEL", "warning")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ─── Process naming ───────────────────────────────────────────────────────────
proc_name = "fintrack"

# ─── Security ─────────────────────────────────────────────────────────────────
limit_request_line   = 4096
limit_request_fields = 100
forwarded_allow_ips  = os.getenv("GUNICORN_FORWARDED_IPS", "127.0.0.1")

# ─── Preload app (faster worker startup, shares memory) ──────────────────────
preload_app = True

# ─── Server hooks ─────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("FinTrack starting up")

def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exiting")
