"""
Created on Thu May 19 15:09:54 2016

@author: bschollnick
"""
import os


def assure_path_exists(dir_path):
    """
    Assures that a path exists, and create if necessary.

    returns - True if the path was created
    returns - False, if the path already existed.
    """
#    if not dir_path.endswith(os.sep):
#        dir_path += os.sep
# (abspath removes last os.sep, so redundant)
    dir_path = os.path.abspath(dir_path)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        return True
    return False
