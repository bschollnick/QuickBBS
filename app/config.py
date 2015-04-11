import common
import ConfigParser
import os
import os.path

def join_path(path_components, prepend=False, postpend=False):
    path = os.path.abspath(os.path.join(*path_components))
    if prepend:
        path = common.pre_slash(path)

    if postpend:
        path = common.post_slash(path)
    return path

def load_location_data(server_root):
    locations = {}
    locations["server_root"] = server_root
    locations["config_root"] = join_path([locations["server_root"],
                                          "..", "cfg"], False, True)
    Config = ConfigParser.SafeConfigParser()
    Config.read( os.path.join(locations["config_root"], "paths.ini"))
    for option_name in Config.options("locations"):
        locations[option_name] = join_path([Config.get("locations",
                                                       option_name)])
    return locations

def load_filetypes(locations):
    filetypes = {}
    Config = ConfigParser.SafeConfigParser()
    Config.read( os.path.join(locations["config_root"], "filetypes.ini"))
    for option_name in Config.options("filetypes"):
        filetypes[option_name] = []
        tempvalue = Config.get("filetypes", option_name).split(",")
        for temp_item in tempvalue:
            filetypes[option_name].append(temp_item.strip())
    return filetypes

def load_settings(locations):
    settings = {}
    Config = ConfigParser.SafeConfigParser()
    Config.read( os.path.join(locations["config_root"], "settings.ini"))
    for option_name in Config.options("configuration"):
        settings[option_name] = common.return_int(Config.get("configuration",
            option_name).strip())
    return settings


def load_config_data():
    global settings
    global filetypes
    global locations
    locations = load_location_data(os.path.abspath(""))
    filetypes = load_filetypes(locations)
    settings = load_settings(locations)


if __name__ == "__main__":
    server_root = os.path.abspath ("")
    load_config_data()
    print settings
    print filetypes
    print locations
