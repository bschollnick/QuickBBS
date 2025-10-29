#!/bin/bash
#
# Start QuickBBS with Uvicorn ASGI server (HTTP/1.1 only)
#
# WARNING: Despite the filename, Uvicorn does NOT support HTTP/2!
# This script provides HTTPS with HTTP/1.1 only.
# For HTTP/2 support, use start_hypercorn_http2.sh instead.
#
# Uvicorn provides excellent HTTP/1.1 performance but cannot negotiate HTTP/2.
#
# Usage:
#   ./start_uvicorn_http2.sh
#
# Requirements:
#   - uvicorn (installed)
#   - h2 (installed) - HTTP/2 support
#   - httptools (installed) - Fast HTTP/1.1 parsing
#   - SSL certificate files in ../certs/ directory
#

# Change to the quickbbs directory (where manage.py is)
cd "$(dirname "$0")"

# Server configuration
HOST="0.0.0.0"
PORT="8888"
WORKERS="4"  # Adjust based on CPU cores (2-4 * num_cores)

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

echo "Starting QuickBBS with Uvicorn (HTTP/1.1 only)"
echo "=============================================="
echo "Host:     $HOST"
echo "Port:     $PORT"
echo "Workers:  $WORKERS"
echo "Protocol: HTTPS/HTTP/1.1 (Uvicorn does NOT support HTTP/2)"
echo "SSL Cert: $SSL_CERT"
echo "SSL Key:  $SSL_KEY"
echo ""
echo "For HTTP/2 support, use: ./start_hypercorn_http2.sh"
echo ""
echo "httptools: $(python -c 'import httptools; print("INSTALLED (fast HTTP/1.1)")' 2>/dev/null || echo 'NOT INSTALLED')"
echo ""

# Start Uvicorn with HTTPS (HTTP/1.1 only)
# NOTE: Uvicorn does NOT support HTTP/2, despite what online docs may suggest
# --ssl-keyfile and --ssl-certfile enable HTTPS
# --workers sets number of worker processes
# --loop uvloop uses the fast uvloop event loop (if available)
uvicorn quickbbs.asgi:application \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --ssl-keyfile "$SSL_KEY" \
    --ssl-certfile "$SSL_CERT" \
    --loop uvloop \
    --log-level info \
    --access-log
