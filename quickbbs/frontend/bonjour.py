# from zeroconf import ServiceBrowser, Zeroconf
from zeroconf import IPVersion, ServiceInfo, Zeroconf
from django.conf import settings


desc = {'path': '/'}
info = ServiceInfo(
    "_http._tcp.local.",
    f"{settings.SITE_NAME}._http._tcp.local.",
    addresses=[settings.EXTERNAL_IP,],
    port=settings.SERVER_PORT,
    properties=desc,
    server=f"{settings.HOSTNAME}",
    )


# class MyListener:
#     def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
#         print(f"Service {name} updated")
#
#     def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
#         print(f"Service {name} removed")
#
#     def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
#         info = zc.get_service_info(type_, name)
#         print(f"Service {name} added, service info: {info}")


# zeroconf = Zeroconf()
# listener = MyListener()
# browser = ServiceBrowser(zeroconf, "_http._tcp.local.", listener)
#    zeroconf.close()


#
#     def shutdown(self, *args):
#         if os.environ.get('RUN_MAIN') == 'true':
#             print("Shutting down")
#             self.my_observer.stop()
#             self.my_observer.join()
#     #    signal.send('system')
#         sys.exit(0)   # So runserver does try to exit
