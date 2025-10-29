## Running Web Servers

QuickBBS supports multiple web server options for both development and production deployment. Starting with version 3.5.0, the application is fully ASGI-compatible.

### Django Development Server (Development Only)

**Basic HTTP:**
```bash
cd quickbbs
python manage.py runserver 0.0.0.0:8888
```

**HTTPS (requires Django Extensions):**
```bash
# Install django-extensions (already in dependencies)
python manage.py runserver_plus --cert-file cert.pem 0.0.0.0:8888
```

**Pros:** Quick setup, auto-reload on code changes
**Cons:** Not for production, single-threaded, limited performance

---

### Gunicorn (WSGI - Production)

Gunicorn is a production-ready WSGI server with excellent stability.

**Basic HTTP:**
```bash
cd quickbbs
gunicorn quickbbs.wsgi:application \
    --bind 0.0.0.0:8888 \
    --workers 4 \
    --threads 2 \
    --timeout 60
```

**With Access Logging:**
```bash
gunicorn quickbbs.wsgi:application \
    --bind 0.0.0.0:8888 \
    --workers 4 \
    --threads 2 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
```

**HTTPS (Direct):**
```bash
gunicorn quickbbs.wsgi:application \
    --bind 0.0.0.0:8888 \
    --workers 4 \
    --threads 2 \
    --keyfile /path/to/private.key \
    --certfile /path/to/certificate.crt
```

**Recommended Workers:**
- Workers: `(2 × CPU cores) + 1`
- Threads: 2-4 per worker
- For 4 cores: `--workers 9 --threads 2`

**Pros:** Battle-tested, stable, excellent for WSGI
**Cons:** WSGI only (no async views), no HTTP/2 support

---

### Gunicorn + Uvicorn Workers (ASGI - Production)

Gunicorn with Uvicorn workers combines Gunicorn's process management with Uvicorn's ASGI performance and HTTP/2 support.

**Quick Start with HTTP/2 (Recommended):**
```bash
cd quickbbs
./start_gunicorn_http2.sh
```

This script automatically configures Gunicorn + Uvicorn workers with HTTP/2, HTTPS, and optimal settings.

**Manual Configuration:**

**HTTPS with HTTP/2:**
```bash
cd quickbbs
gunicorn quickbbs.asgi:application \
    -k uvicorn.workers.UvicornWorker \
    -w 4 \
    -b 0.0.0.0:8888 \
    --keyfile /path/to/private.key \
    --certfile /path/to/certificate.crt \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
```

**Recommended Workers:**
- Workers: `2-4 × CPU cores`
- For 4 cores: `-w 8` to `-w 16`
- Higher timeout for large downloads: `--timeout 120`

**Pros:** Production-grade process management, async support, HTTP/2, graceful restarts
**Cons:** Slightly more complex than standalone Uvicorn

---

### Uvicorn (ASGI - Production) ⭐ RECOMMENDED FOR HTTP/1.1

Uvicorn is a lightning-fast ASGI server with async support. **NOTE: Uvicorn does NOT support HTTP/2.** For HTTP/2 support, use Hypercorn instead.

**Manual Commands:**

**Basic HTTP:**
```bash
cd quickbbs
uvicorn quickbbs.asgi:application \
    --host 0.0.0.0 \
    --port 8888 \
    --workers 4
```

**With Auto-Reload (Development):**
```bash
uvicorn quickbbs.asgi:application \
    --host 0.0.0.0 \
    --port 8888 \
    --reload
```

**HTTPS (HTTP/1.1 only):**
```bash
uvicorn quickbbs.asgi:application \
    --host 0.0.0.0 \
    --port 8888 \
    --ssl-keyfile /path/to/private.key \
    --ssl-certfile /path/to/certificate.crt \
    --workers 4 \
    --loop uvloop
```

**Note:** Uvicorn only supports HTTP/1.1. For HTTP/2, use Hypercorn (see below).

**HTTPS with CA Bundle:**
```bash
uvicorn quickbbs.asgi:application \
    --host 0.0.0.0 \
    --port 8888 \
    --ssl-keyfile /path/to/private.key \
    --ssl-certfile /path/to/certificate.crt \
    --ssl-ca-certs /path/to/ca-bundle.crt
```

**Production Configuration:**
```bash
uvicorn quickbbs.asgi:application \
    --host 0.0.0.0 \
    --port 8888 \
    --workers 4 \
    --log-level info \
    --access-log \
    --loop uvloop
```

**Recommended Workers:**
- Workers: `2 × CPU cores`
- For 4 cores: `--workers 8`

**Performance Dependencies:**
- ✅ `httptools` - Fast HTTP/1.1 parsing (installed)
- ⚪ `uvloop` - Fast event loop (optional, 20-30% boost)

**Pros:** Fast, async support, excellent HTTP/1.1 performance, modern
**Cons:** No HTTP/2 support (use Hypercorn for HTTP/2)

---

### Hypercorn (ASGI - Production) ⭐ RECOMMENDED FOR HTTP/2

Hypercorn is an ASGI server with **native HTTP/2 and HTTP/3 support**. Unlike Uvicorn, Hypercorn supports HTTP/2 via ALPN negotiation.

**Quick Start with HTTP/2 (Recommended):**
```bash
cd quickbbs
./start_hypercorn_http2.sh
```

This script automatically configures Hypercorn with HTTP/2, HTTPS, and optimal settings.

**Manual Commands:**

**Basic HTTP:**
```bash
cd quickbbs
hypercorn quickbbs.asgi:application \
    --bind 0.0.0.0:8888 \
    --workers 4
```

**HTTPS with HTTP/2 (Automatic):**
```bash
hypercorn quickbbs.asgi:application \
    --bind 0.0.0.0:8888 \
    --keyfile /path/to/private.key \
    --certfile /path/to/certificate.crt \
    --workers 4
```

**Note:** HTTP/2 is automatically enabled via ALPN negotiation when HTTPS is configured (--keyfile and --certfile). Clients that support HTTP/2 will negotiate it automatically.

**HTTPS with Advanced Options:**
```bash
hypercorn quickbbs.asgi:application \
    --bind 0.0.0.0:8888 \
    --keyfile /path/to/private.key \
    --certfile /path/to/certificate.crt \
    --ca-certs /path/to/ca-bundle.crt \
    --workers 4 \
    --worker-class asyncio
```

**HTTP/2 Benefits:**
- 10-30% faster concurrent downloads
- Request multiplexing (multiple requests over single connection)
- Header compression (HPACK reduces bandwidth)
- Better performance under load

**Pros:** Native HTTP/2 support, HTTP/3 support, excellent SSL/TLS, modern
**Cons:** Slightly slower than Uvicorn for HTTP/1.1 (but faster with HTTP/2)

---

### HTTPS Configuration

#### Generate Self-Signed Certificate (Development)

```bash
# Generate certificate (valid 365 days)
openssl req -x509 -newkey rsa:4096 \
    -keyout key.pem \
    -out cert.pem \
    -days 365 \
    -nodes \
    -subj "/CN=nerv.local"

# Use with any server
uvicorn quickbbs.asgi:application \
    --host 0.0.0.0 \
    --port 8888 \
    --ssl-keyfile key.pem \
    --ssl-certfile cert.pem
```

**Note:** Browsers will show security warnings for self-signed certificates.

#### Using Existing Certificates

If you have certificates from a CA or Let's Encrypt:

```bash
# Standard format
uvicorn quickbbs.asgi:application \
    --ssl-keyfile /etc/letsencrypt/live/yourdomain.com/privkey.pem \
    --ssl-certfile /etc/letsencrypt/live/yourdomain.com/fullchain.pem
```

#### macOS Keychain Certificates

Export from Keychain Access and convert:

```bash
# Export from Keychain Access as .p12
# Then convert to PEM format
openssl pkcs12 -in certificate.p12 -out certificate.pem -nodes
openssl pkcs12 -in certificate.p12 -out key.pem -nocerts -nodes

# Use with server
uvicorn quickbbs.asgi:application \
    --ssl-keyfile key.pem \
    --ssl-certfile certificate.pem
```

---

### Reverse Proxy (Recommended for Production)

For production deployments, use a reverse proxy (nginx/caddy) in front of the application server.

#### Nginx Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name nerv.local;

    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    location /static/ {
        alias /path/to/quickbbs/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Run application server without SSL (nginx handles it):
```bash
uvicorn quickbbs.asgi:application --host 127.0.0.1 --port 8888 --workers 4
```

#### Caddy Configuration (Auto SSL)

```caddy
nerv.local {
    reverse_proxy localhost:8888

    # Caddy automatically handles SSL via Let's Encrypt!

    encode gzip

    handle /static/* {
        root * /path/to/quickbbs
        file_server
    }
}
```

**Pros:** Automatic SSL, HTTP/2, load balancing, static file serving
**Cons:** Additional component to manage

---

### Django Settings for HTTPS

When using HTTPS, ensure these settings in `settings.py`:

```python
# Already configured in QuickBBS
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Add this if using reverse proxy
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

---

### Performance Comparison

| Server              | Protocol | Async | HTTP/2 | httptools | Best For                    |
|---------------------|----------|-------|--------|-----------|----------------------------|
| Django Dev          | WSGI     | No    | No     | No        | Development only            |
| Gunicorn (WSGI)     | WSGI     | No    | No     | No        | Legacy/stable production    |
| Gunicorn + Uvicorn  | ASGI     | Yes   | No     | Yes       | Fast HTTP/1.1 production    |
| Uvicorn Standalone  | ASGI     | Yes   | No     | Yes       | Fast HTTP/1.1, simple setup |
| Hypercorn           | ASGI     | Yes   | Yes    | No        | HTTP/2 production ⭐        |

**HTTP/2 Performance Impact:** 10-30% faster concurrent downloads (Hypercorn only)

---

### Choosing the Right Server

**Development:**
- Django dev server: Quick testing, auto-reload
- Uvicorn with `--reload`: Async development with hot-reload

**Production (Recommended Order):**

**For HTTP/2 Support:**
1. **Best: Hypercorn with HTTP/2** (`./start_hypercorn_http2.sh`) ⭐
   - Native HTTP/2 support via ALPN
   - 10-30% faster for concurrent downloads
   - Also supports HTTP/3
   - Best for modern production deployments

**For HTTP/1.1 Only:**
1. **Best: Uvicorn Standalone**
   - Simplest setup
   - Fastest HTTP/1.1 performance
   - Good for small-to-large sites
   - Use when HTTP/2 is not required

2. **Alternative: Gunicorn + Uvicorn Workers** (`./start_gunicorn_http2.sh`)
   - Better process management
   - Graceful restarts without downtime
   - HTTP/1.1 only (despite filename)
   - Best for mission-critical production

3. **Legacy: Gunicorn WSGI Mode**
   - No async support
   - No HTTP/2
   - Use only if you need WSGI compatibility

**Current Recommendation:** Use `./start_hypercorn_http2.sh` for best performance with HTTP/2 support.

