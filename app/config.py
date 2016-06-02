"""
:Module: Config
:Date: 2015-05-1
:Platforms: Mac, Windows, Unix (Tested under Mac OS X)
:Version: 1
:Authors:
    - Benjamin Schollnick


:Description:
    This module will read in the configuration ini for the Gallery project.


**Modules Used (Batteries Included)**:

   * os
   * os.path
   * stat
   * string
   * time


:Concept:
    With the gallery / quickbbs project, I am trying to prevent the
    need of a large database, or GUI.  If there is a need for a GUI
    I intend to make it in the Gallery / Quickbbs web gui.

    This means that the system needs to be bootstrap ready.

    While not ideal, INI based configuration files, are easy to debug,
    and more important, easy to update.

    The module is passed the location of the configuration files,
    and will read in the filetypes.ini, paths.ini, and settings.ini files.
    Each of these will be stored in their own dictionary (filestypes,
    locations, settings).

code::

"""
#####################################################
#   Batteries Included imports
import common
#import fastnumbers
import ConfigParser
import os
import os.path

#####################################################
#   3rd party imports
#
#   None

LOCATIONS = {}
SETTINGS = {}
FILETYPES = {}

def join_path(path_components, prepend=False, postpend=False):
    """
    Join os path lists (e.g. os.path.join), but with the option
    to force a prepended, or postpended os.sep

    inputs -
        path_components - list of path elements
        prepend - if true, force a prepended os.sep, if one does not exist
        postpend - if true, force a postpended os.sep, if one does not exist

    returns - newly created pathstring
    """
    path = os.path.abspath(os.path.join(*path_components))
    if prepend:
        path = common.pre_slash(path)

    if postpend:
        path = common.post_slash(path)
    return path

def load_location_data(root):
    """
    Load the location paths

    inputs - server root

    returns - location dictionary
    """
    locations_data = {}
    locations_data["server_root"] = root
    locations_data["config_root"] = join_path([locations_data["server_root"],
                                               "..", "cfg"], False, True)
    config = ConfigParser.SafeConfigParser()
    config.read(os.path.join(locations_data["config_root"], "paths.ini"))
    for option_name in config.options("locations"):
        locations_data[option_name] = join_path([config.get("locations",
                                                            option_name)])
    return locations_data

def load_filetypes(locations_data):
    """
    Load the filetype data from the filetypes.ini configuration file

    inputs - location_data dictionary
    output - the filetype dictionary
    """
    local_filetypes = {}
    config = ConfigParser.SafeConfigParser()
    config.read(os.path.join(locations_data["config_root"], "filetypes.ini"))
    for option_name in config.options("filetypes"):
        local_filetypes[option_name] = []
        tempvalue = config.get("filetypes", option_name).split(",")
        for temp_item in tempvalue:
            local_filetypes[option_name].append(temp_item.strip())
    return local_filetypes

def load_settings(locations_data):
    """
    Load the general settings data from the settings.ini configuration file

    inputs - location_data dictionary
    output - the general settings dictionary
    """
    local_settings = {}
    config = ConfigParser.SafeConfigParser()
    config.read(os.path.join(locations_data["config_root"], "settings.ini"))
    for option_name in config.options("configuration"):
        local_settings[option_name] = config.get("configuration",\
            option_name).strip()
        try:
            local_settings[option_name] = int(local_settings[option_name])
        except:
            print "failed - ", local_settings[option_name]
            pass
    return local_settings


def load_config_data():
    """
    Wrapper for loading all three configuration files
    """
    global LOCATIONS
    global FILETYPES
    global SETTINGS
    LOCATIONS = load_location_data(os.path.abspath(""))
    FILETYPES = load_filetypes(LOCATIONS)
    SETTINGS = load_settings(LOCATIONS)


if __name__ == "__main__":
    load_config_data()
    print SETTINGS
    print FILETYPES
    print LOCATIONS
