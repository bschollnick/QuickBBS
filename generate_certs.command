# Generate certs (locally created self-https certs)
openssl req -x509 -newkey rsa:4096 \
    -keyout ./certs/quickbbs_key.pem \
    -out ./certs/quickbbs_cert.pem \
    -days 90 \
    -nodes \
    -subj "/CN=nerv.local"
