# coding: utf-8
"""
:Module: Config
:Date: 2015-05-1
:Platforms: Mac, Windows, Unix (Tested under Mac OS X)
:Version: 1
:Authors:
    - Benjamin Schollnick

:Description:
    This module will read in the configuration ini.

**Modules Used (Batteries Included)**:

   * os
   * os.path
   * stat
   * string
   * time

:Concept:

    While not ideal, INI based configuration files, are easy to debug,
    and more important, easy to update.

    The module is passed the location of the configuration files,
    and will read in the necessary ini files (settings.ini by default).
    The different segments of the ini file will be stored in a seperate
    dictionary for ease of use..

code::

    load_data(<fqfn>)
    print config.configdata["USER"]
    print config.configdata["EMAIL"]

"""
#####################################################
#   Batteries Included imports
from __future__ import absolute_import
from __future__ import print_function
#import six.moves.configparser
import configparser
from configparser import ConfigParser
import os
import os.path
import sys
import fastnumbers

#####################################################
#   3rd party imports
#
#   None

configdata = {}

def load_data(filename=None, ini_group=""):
    """
:Description:
    Load data from the ini file

Args:

    filename: (default value = None) To override the filename
        pass a string containing the new filename.

    oname: The option name to read from the ini

 Returns:
    loaded dictionary

code::

    USER = load_user_data(settings_file)
    EMAIL = load_email_data(settings_file)

    """
    if filename is None:
        filename = "settings.ini"

    try:
#        config = six.moves.configparser.SafeConfigParser()
        config = configparser.SafeConfigParser()
        config.read(filename)
        for section in config.sections():
            #print("Section : ",section)
            sname = section.strip()
            configdata[sname]={}
            for option_name in config.options(section.strip()):
                value = config.get(sname, option_name).split(",")
                if len(value) == 1:
                    if (option_name.endswith("_path") or
                        option_name.endswith("_filename")):
#                        print (option_name)
                        value[0] = os.path.abspath(value[0])
                    configdata[sname][option_name] = fastnumbers.fast_int(value[0])
                else:
                    configdata[sname][option_name] = []
                    for cleanvalue in value:
                        if (option_name.endswith("_path") or
                            option_name.endswith("_filename")):
                            cleanvalue = os.path.abspath(cleanvalue)
                        configdata[sname][option_name].append(cleanvalue.strip())
#    except six.moves.configparser.NoSectionError:
    except configparser.NoSectionError:
        print("Error reading %s" % filename)

if __name__ == "__main__":
    load_data()
   #load_config_data()
#    print "User - %s\n" % USER
#    print "Email - %s\n" % EMAIL
#    print "NYSIIS - %s\n" % NYSIIS
#    print "CONFLUENCE - %s\n" % CONFLUENCE

    for x in configdata.keys():
        print(x, configdata[x])
