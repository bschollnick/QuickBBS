#!/bin/bash
#
# Start QuickBBS with Gunicorn + Uvicorn Workers (HTTP/1.1 only)
#
# WARNING: Despite the filename, this does NOT support HTTP/2!
# Uvicorn workers only support HTTP/1.1.
# For HTTP/2 support, use start_hypercorn_http2.sh instead.
#
# This script runs Gunicorn with Uvicorn ASGI workers for HTTP/1.1.
# Gunicorn provides robust process management, Uvicorn provides ASGI performance.
#
# Advantages over plain Uvicorn:
# - Better worker lifecycle management
# - Graceful restarts without downtime
# - Better handling of worker crashes
# - Production-grade stability
#
# Usage:
#   ./start_gunicorn_http2.sh
#
# Requirements:
#   - gunicorn (needs to be installed via poetry)
#   - uvicorn[standard] (installed)
#   - h2 (installed) - HTTP/2 support
#   - httptools (installed) - Fast HTTP/1.1 parsing
#   - SSL certificate files in ../certs/ directory
#

# Change to the quickbbs directory (where manage.py is)
cd "$(dirname "$0")"

# Server configuration
BIND_ADDRESS="0.0.0.0:8888"
WORKERS="4"  # Adjust based on CPU cores (2-4 * num_cores)
WORKER_CLASS="uvicorn.workers.UvicornWorker"
TIMEOUT="120"  # Worker timeout in seconds (important for long downloads)

# SSL certificate paths (adjust to your certificate locations)
SSL_CERT="../certs/quickbbs_cert.pem"
SSL_KEY="../certs/quickbbs_key.pem"

# Check if SSL certificates exist
if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
    echo "ERROR: SSL certificate files not found!"
    echo "  Expected: $SSL_CERT and $SSL_KEY"
    echo ""
    echo "To generate self-signed certificates for testing:"
    echo "  mkdir -p ../certs"
    echo "  openssl req -x509 -newkey rsa:4096 -nodes \\"
    echo "    -keyout ../certs/quickbbs_key.pem \\"
    echo "    -out ../certs/quickbbs_cert.pem \\"
    echo "    -days 365 -subj '/CN=localhost'"
    exit 1
fi

# Check if Gunicorn is installed
if ! command -v gunicorn &> /dev/null; then
    echo "ERROR: Gunicorn is not installed!"
    echo "Install it with: poetry add gunicorn"
    exit 1
fi

echo "Starting QuickBBS with Gunicorn + Uvicorn Workers (HTTP/1.1 only)"
echo "=================================================================="
echo "Bind:         $BIND_ADDRESS"
echo "Workers:      $WORKERS"
echo "Worker Class: $WORKER_CLASS"
echo "Timeout:      ${TIMEOUT}s"
echo "Protocol:     HTTPS/HTTP/1.1 (Uvicorn workers do NOT support HTTP/2)"
echo "SSL Cert:     $SSL_CERT"
echo "SSL Key:      $SSL_KEY"
echo ""
echo "For HTTP/2 support, use: ./start_hypercorn_http2.sh"
echo ""
echo "httptools: $(python -c 'import httptools; print("INSTALLED (fast HTTP/1.1)")' 2>/dev/null || echo 'NOT INSTALLED')"
echo ""

# Start Gunicorn with Uvicorn workers
# -k uvicorn.workers.UvicornWorker uses Uvicorn ASGI workers
# -w sets number of worker processes
# -b sets bind address
# --keyfile and --certfile enable HTTPS
# --timeout sets worker timeout (important for large downloads)
# --access-logfile - logs access to stdout
# --error-logfile - logs errors to stdout
gunicorn quickbbs.asgi:application \
    -k "$WORKER_CLASS" \
    -w "$WORKERS" \
    -b "$BIND_ADDRESS" \
    --keyfile "$SSL_KEY" \
    --certfile "$SSL_CERT" \
    --timeout "$TIMEOUT" \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --enable-stdio-inheritance
