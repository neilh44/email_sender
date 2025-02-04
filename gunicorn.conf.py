import multiprocessing

# Server socket settings
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"
worker_connections = 1000
timeout = 300  # 5 minutes
keepalive = 2

# Process naming
proc_name = "emailer"

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# SSL
keyfile = None
certfile = None

# Development
reload = True