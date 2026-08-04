#!/bin/bash
#
# Start QuickBBS with Granian ASGI server with HTTP/2 support
#
# Granian is a Rust-based HTTP server with native HTTP/2 support (via ALPN)
# and multi-process worker management, similar to Hypercorn but faster.
#
# Usage:
#   ./start_granian_http2.sh
#
# Requirements:
#   - granian (installed)
#   - SSL certificate files in ../certs/ directory
#

# Change to the quickbbs directory (where manage.py is)
cd "$(dirname "$0")"

# Server configuration
HOST="0.0.0.0"
PORT="8888"
WORKERS="3"  # Adjust based on CPU cores (2-4 * num_cores)

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

# Check if Granian is installed
if ! command -v granian &> /dev/null; then
    echo "ERROR: Granian is not installed!"
    echo "Install it with: poetry add granian"
    exit 1
fi

echo "Starting QuickBBS with Granian (HTTP/2 enabled)"
echo "================================================"
echo "Host:     $HOST"
echo "Port:     $PORT"
echo "Workers:  $WORKERS"
echo "HTTP/2:   ENABLED (native support via ALPN)"
echo "SSL Cert: $SSL_CERT"
echo "SSL Key:  $SSL_KEY"
echo ""

# Trap SIGINT so Ctrl+C stops granian (via its graceful shutdown)
# but does NOT kill this script — allowing post-shutdown commands to run.
trap '' INT

# Start Granian with HTTP/2
# --interface asgi tells Granian to use the ASGI protocol (Django's asgi.py)
# --http 2 enables HTTP/2 (auto also negotiates via ALPN, but we pin it here)
# --ssl-certificate / --ssl-keyfile enable HTTPS
# --workers sets number of worker processes
# --access-log logs access to stdout
granian quickbbs.asgi:application \
    --interface asgi \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --http 2 \
    --ssl-certificate "$SSL_CERT" \
    --ssl-keyfile "$SSL_KEY" \
    --log-level info \
    --access-log

echo ""
echo "Granian has exited."
