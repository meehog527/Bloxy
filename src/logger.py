#logger.py

import logging
import logging.config
import os
import platform
import http.server
import socketserver
import threading
#from flask import Flask, Response
import time

#Log Config
#LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
#LOG_FILE = os.getenv("LOG_FILE", "/home/pi/logs/bloxy.log")  # Customize path as needed
LOG_LEVEL = "DEBUG"
LOG_FILE = "bloxy.log"

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "format": "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        },
    },
    "handlers": {
        "console": {
            "level": LOG_LEVEL,
            "class": "logging.StreamHandler",
            "formatter": "detailed"
        },
        "file": {
            "level": LOG_LEVEL,
            "class": "logging.FileHandler",
            "filename": LOG_FILE,
            "formatter": "detailed",
        },
    },
    "root": {
        "level": LOG_LEVEL,
        "handlers": ["console", "file"]
    },
}

#Log Server Config#
PORT = 8080

#LOG_DIR = "/home/pi/logs"
LOG_DIR = "."

logging.config.dictConfig(LOGGING_CONFIG)

def get_logger(scope_name: str = __name__) -> logging.Logger:
    """Returns a scoped logger for the given module/class/function."""
    return logging.getLogger(scope_name)

def start_log_server():
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"Serving logs at http://{platform.node()}:{PORT}")
        #os.chdir(LOG_DIR)
        
        # Run server in a separate thread
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True  # Allows program to exit even if thread is running
        server_thread.start()

#app = Flask(__name__)

#@app.route("/")
#def stream_log():
#    def generate():
#        with open(LOG_FILE, "r") as f:
#            f.seek(0, 2)  # Go to end of file
#            while True:
#                line = f.readline()
#                if line:
#                    yield line
#                else:
#                    time.sleep(1)
#    return Response(generate(), mimetype="text/plain")



