# from frontend.bonjour import info, Zeroconf, IPVersion
# import sys

#
#   Boot strap by loading the configuration path data
#
__version__ = "3.85"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = ""

# here = os.path.dirname(__file__)
# cfg_path = os.path.abspath(os.path.join(here, r"../../cfg"))
# config.load_data(os.path.join(cfg_path, "paths.ini"))
# config.load_data(os.path.join(cfg_path, "settings.ini"))
# config.load_data(os.path.join(cfg_path, "filetypes.ini"))

# signal.signal(signal.SIGINT, watchdogmon.watchdog.shutdown)
# import signal
# def my_signal_handler(*args):
#    zc.unregister_service(info)
#    zc.close()
#
# zc = Zeroconf(ip_version=IPVersion.All)
# print(sys.argv)
# try:
#     print("**** ZeroConf registration")
#     zc.register_service(info)
# except RuntimeError:
#     pass
#
# signal.signal(signal.SIGINT, my_signal_handler)
