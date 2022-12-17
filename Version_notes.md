# v3 notes






# Other Notes

* [django-compression-middleware](https://pypi.org/project/django-compression-middleware/) - Re-evaluate at a later date.
Currently it works, but there is a significant pause/lag when using it.  I'm not see any CPU spikes, and testing it over
the network shows that pause (Wifi, 5Ghz).  But that maybe that it needs to be optimized more...?


Currently testing quickbbs against:

ab = Apache Bench
* Django development Server
  * python manage.py runserver 0.0.0.0:8888
  * Able to support ab concurrency up to 5 without errors consistently
    * if you go up to concurrency up to 10, but there are errors that start to creep in.
  * Seems to be the fastest performing, and most reliable
* gunicorn
  * gunicorn wsgi -w 2 -b 0.0.0.0:8888 --worker-class gthread
  * Able to support ab concurrency up to 50, with no errors
    * Haven't tested higher
    * worker-class is important, gthread does not appear to have any odd pauses
* uswgi
  * uwsgi --master --module=wsgi:application  --pidfile=project-master.pid --http-socket  0.0.0.0:8888 --processes=3 --vacuum -b 32000
  * Not yet tested with ab
  * There are occasional broken images, but that appears to be a timing issue with the HTML lazy load.
    * I may need to consider reversing that decision, and researching alternatives.
      * Go back to jquery-lazy-load?  uswgi is the only server that is showing intermittent load failures