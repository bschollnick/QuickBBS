"""
Plugin Meta manager
"""
import os

##############################################################################
from yapsy.PluginManager import PluginManager
#from yapsy.IPlugin import IPlugin

FILE_TYPES_MAP = {}
#        #0 - Uppercase, stripped, File Extension
#        #1 - The pointer to the plugin class
#        #2 - The description of the plugin

IMAGE_FILES = []

def return_plugin(sourcefile):
    """
    If the plugin is registered, return the plugin for said sourcefile.

    If the plugin is not registered, return None

    Note: Cached Plugin Extension switching is barely faster than
          this method, it is not worth the complexity to implement.
    """
    extension = os.path.splitext(sourcefile.upper().strip())[1]
    if plugin_registered(sourcefile):
        return FILE_TYPES_MAP[extension][1]
    else:
        return None

def plugin_registered(sourcefile):
    """
    Is there a plugin registered for this source file?

    Input - Filename / FQN, converted
            to upper case file extension

    returns:

            - True, if the file extension is in the FILE_TYPES_MAP
            - False, if the file extension is not found
    """
    extension = os.path.splitext(sourcefile.upper().strip())[1]
    return FILE_TYPES_MAP.has_key(extension)

def load_plugins():
    """
        The file types map is structured as follows:

        #0 - Uppercase, stripped, File Extension
        #1 - The pointer to the plugin class
        #2 - The description of the plugin

    """
    plugin_manager = PluginManager()
    plugin_manager.setPluginPlaces([os.path.expanduser(\
        os.path.abspath('.' + os.sep + "plugins"))])
    plugin_manager.collectPlugins()
    # Loop round the plugins and print their names.
    for plug in plugin_manager.getAllPlugins():
        for ftype in plug.plugin_object.ACCEPTABLE_FILE_EXTENSIONS:
            if plug.plugin_object.IMG_TAG:
                IMAGE_FILES.append(ftype.upper().strip())
            FILE_TYPES_MAP[ftype.upper().strip()] = [ftype.upper().strip(),
                                                     plug.plugin_object,
                                                     plug.description]

#    for x in sorted(FILE_TYPES_MAP):
#        print "Loading FileType Plugin for %5s - %s" %\
#             (x, FILE_TYPES_MAP[x][2])

