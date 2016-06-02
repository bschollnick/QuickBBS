import os
import os.path
import config


#
#   Boot strap by loading the configuration path data
#
cfg_path = os.path.abspath(r"../cfg")
config.load_data(os.path.join(cfg_path, "paths.ini"))
config.load_data(os.path.join(cfg_path, "settings.ini"))
