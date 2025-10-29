#!/bin/bash
#
# Start QuickBBS with Django Dev Server (HTTP/1.1 only)
#
# Usage:
#   ./start_django_http1.sh
#
# Requirements:
#   - SSL certificate files in ../certs/ directory
#

# Change to the quickbbs directory (where manage.py is)
cd "$(dirname "$0")"

# Server configuration
BIND_ADDRESS="0.0.0.0:8888"

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

echo "Starting QuickBBS with django development server (HTTP/1.1 only)"
echo "=================================================================="
echo "Bind:         $BIND_ADDRESS"
echo "SSL Cert:     $SSL_CERT"
echo "SSL Key:      $SSL_KEY"
echo ""
echo "For HTTP/2 support, use: ./start_hypercorn_http2.sh"
echo ""

python manage.py runserver_plus $BIND_ADDRESS --cert-file $SSL_CERT --key-file $SSL_KEY
