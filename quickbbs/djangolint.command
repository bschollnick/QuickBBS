export DJANGO_SETTINGS_MODULE=quickbbs.settings
echo pylint --load-plugins pylint_django --django-settings-module=quickbbs.settings $1 $2 $3 $4
pylint  $1 $2 $3 $4
