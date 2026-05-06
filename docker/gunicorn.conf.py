import os

# 1. Connection & Process
bind = "0.0.0.0:5001"
workers = 4 # number of clients. 4 is Standard for production.
timeout = 60 # seconds for long-running PDF generation
forwarded_allow_ips = '*' # This allows Gunicorn to read the REAL IP from user

# 2. Unified Logging Configuration
# This dictionary gives us total control over the Gunicorn engine's "voice"
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            # Matches your Python format exactly: [Time] | [Level] | [Engine] | [Message]
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        },
    },
    "handlers": {
        "system_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/app/data/logs/system.log",
            "maxBytes": 5*1024*1024,
            "backupCount": 10,
            "formatter": "standard",
        },
    },
    "loggers": {
        "gunicorn.error": {
            "level": "INFO",
            "handlers": ["system_file"],
            "propagate": False,
        },
        "gunicorn.access": {
            "level": "INFO",
            "handlers": ["system_file"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["system_file"],
    }
}

# 3. Access Log Specifics
# We still set this to capture the specific details (IP, Request, Status, User-Agent)
# Gunicorn sends this string as the 'message' to the logger above.
access_log_format = '%(h)s - "%(r)s" %(s)s "%(a)s"'