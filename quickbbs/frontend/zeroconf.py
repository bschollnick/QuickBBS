from zeroconf import ServiceBrowser, Zeroconf
import signal


class MyListener:

    def remove_service(self, zeroconf, type, name):
        print("Service %s removed" % (name,))

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        print("Service %s added, service info: %s" % (name, info))


zeroconf = Zeroconf()
listener = MyListener()
browser = ServiceBrowser(zeroconf, "_http._tcp.local.", listener)
#browser = ServiceBrowser(zeroconf, "_https._tcp.local.", listener)
#try:
#    input("Press enter to exit...\n\n")
#finally:
#    zeroconf.close()


#
#     def shutdown(self, *args):
#         if os.environ.get('RUN_MAIN') == 'true':
#             print("Shutting down")
#             self.my_observer.stop()
#             self.my_observer.join()
#     #    signal.send('system')
#         sys.exit(0)   # So runserver does try to exit
