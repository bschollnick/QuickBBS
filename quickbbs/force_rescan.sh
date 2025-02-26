# force a refreshed scan of gallery
python manage.py clear_cache
curl https://nerv.local:8888/albums/ > /dev/null
