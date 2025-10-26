#!/bin/bash
#
# Start QuickBBS with Hypercorn ASGI server with HTTP/2 support
#
# Hypercorn is the ASGI server with NATIVE HTTP/2 support.
# Unlike Uvicorn, Hypercorn supports HTTP/2 via ALPN negotiation.
#
# Usage:
#   ./start_hypercorn_http2.sh
#
# Requirements:
#   - hypercorn (installed)
#   - h2 (installed) - HTTP/2 support
#   - SSL certificate files in ../certs/ directory
#

# Change to the quickbbs directory (where manage.py is)
cd "$(dirname "$0")"

# Server configuration
BIND_ADDRESS="0.0.0.0:8888"
WORKERS="6"  # Adjust based on CPU cores (2-4 * num_cores)

# SSL certificate paths (adjust to your certificate locations)
SSL_CERT="../certs/cert.pem"
SSL_KEY="../certs/key.pem"

# Check if SSL certificates exist
if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
    echo "ERROR: SSL certificate files not found!"
    echo "  Expected: $SSL_CERT and $SSL_KEY"
    echo ""
    echo "To generate self-signed certificates for testing:"
    echo "  mkdir -p ../certs"
    echo "  openssl req -x509 -newkey rsa:4096 -nodes \\"
    echo "    -keyout ../certs/key.pem \\"
    echo "    -out ../certs/cert.pem \\"
    echo "    -days 365 -subj '/CN=localhost'"
    exit 1
fi

echo "Starting QuickBBS with Hypercorn (HTTP/2 enabled)"
echo "================================================"
echo "Bind:     $BIND_ADDRESS"
echo "Workers:  $WORKERS"
echo "HTTP/2:   ENABLED (native support)"
echo "SSL Cert: $SSL_CERT"
echo "SSL Key:  $SSL_KEY"
echo ""
echo "h2: $(python -c 'import h2; print("INSTALLED (HTTP/2)")' 2>/dev/null || echo 'NOT INSTALLED')"
echo ""

# Start Hypercorn with HTTP/2
# -b sets bind address
# --certfile and --keyfile enable HTTPS with HTTP/2 via ALPN
# -w sets number of worker processes
# --read-timeout increased for large file downloads (default is too low)
# --graceful-timeout for graceful shutdown
# --access-logfile - logs access to stdout
# --error-logfile - logs errors to stdout
hypercorn quickbbs.asgi:application \
    -b "$BIND_ADDRESS" \
    --certfile "$SSL_CERT" \
    --keyfile "$SSL_KEY" \
    -w "$WORKERS" \
    --read-timeout 60 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
