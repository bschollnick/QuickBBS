import signal

from zeroconf import ServiceBrowser, Zeroconf


class MyListener:

    def remove_service(self, zeroconf, type, name):
        print(f"Service {name} removed")

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        print(f"Service {name} added, service info: {info}")


zeroconf = Zeroconf()
listener = MyListener()
browser = ServiceBrowser(zeroconf, "_http._tcp.local.", listener)
#    zeroconf.close()


#
#     def shutdown(self, *args):
#         if os.environ.get('RUN_MAIN') == 'true':
#             print("Shutting down")
#             self.my_observer.stop()
#             self.my_observer.join()
#     #    signal.send('system')
#         sys.exit(0)   # So runserver does try to exit

