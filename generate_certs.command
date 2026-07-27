# Generate certs (locally created self-https certs)
cd "$(dirname "$0")"

# Pull ALLOWED_HOSTS from secrets.py so the cert always covers the current
# hostnames/IPs instead of a hardcoded list going stale.
SAN=$(python3 -c "
import sys
sys.path.insert(0, 'quickbbs')
from quickbbs.secrets import ALLOWED_HOSTS
import ipaddress

entries = []
for host in ALLOWED_HOSTS:
    try:
        ipaddress.ip_address(host)
        entries.append(f'IP:{host}')
    except ValueError:
        entries.append(f'DNS:{host}')
print(','.join(entries))
")
CN=$(python3 -c "
import sys
sys.path.insert(0, 'quickbbs')
from quickbbs.secrets import ALLOWED_HOSTS
print(ALLOWED_HOSTS[0])
")

openssl req -x509 -newkey rsa:4096 \
    -keyout ./certs/quickbbs_key.pem \
    -out ./certs/quickbbs_cert.pem \
    -days 90 \
    -nodes \
    -subj "/CN=${CN}" \
    -addext "subjectAltName=${SAN}"
