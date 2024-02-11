from django.conf import settings
from django.http import HttpResponseForbidden


class FilterHostMiddleware:

    def process_request(self, request):

        host = request.META.get("HTTP_HOST")
        host = host[0 : host.find(":")]
        if host.endswith(".local"):
            if host not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(host)
        elif (
            host[:7] == "192.168"
        ):  # if the host starts with 192.168 then add to the allowed hosts
            if host not in settings.ALLOWED_HOSTS:
                settings.ALLOWED_HOSTS.append(host)
        else:
            if host not in settings.ALLOWED_HOSTS:
                raise HttpResponseForbidden
        # print "hosts: %s\n" % settings.ALLOWED_HOSTS
        return None
