import sys
import os
import os.path
import frontend.config


#
#   Boot strap by loading the configuration path data
#
here = os.path.dirname(__file__)
cfg_path = os.path.abspath(os.path.join(here, r"../../cfg"))
config.load_data(os.path.join(cfg_path, "paths.ini"))
config.load_data(os.path.join(cfg_path, "settings.ini"))
config.load_data(os.path.join(cfg_path, "filetypes.ini"))
