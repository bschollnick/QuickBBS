# -*- coding: utf-8 -*-
"""
Created on Wed May 04 07:57:22 2016

@author: bschollnick
"""
from __future__ import unicode_literals

import exceptions
import os
import os.path
import scandir
import unidecode
#import unicodedata


file_whitelist = (' ','.','_','-', '(', ')', '[', ']')

blacklist = ['CON', 'PRN', 'AUX', 'NUL']
for count in range(0, 9):
    blacklist.append("LPT%s" % count)
    blacklist.append("COM%s" % count)

def make_unicode(input):
    if type(input) != unicode:
        input =  unidecode.unidecode(input.decode("utf-8"))
    return input


def clean_filename(filename):
    filename = unidecode.unidecode(filename.decode("utf-8"))
    filename = "".join(c for c in filename if c.isalnum() or
                       c in file_whitelist).strip()
    return filename

path_whitelist = (' ','.','_','-', '(', ')', '[', ']', os.sep)

def clean_path(pathname):
    pathname = unidecode.unidecode(pathname)
    pathname = "".join(c for c in pathname if c.isalnum() or
                       c in path_whitelist).strip()
    return pathname


def check_filename(filename):
    """
    Return True if the filename is clean
    Return False if the filename is not clean
    """
#    return filename.decode("utf-8").lower().strip() == clean_filename(filename).lower()
    return filename.lower().strip() == clean_filename(filename).lower()

def check_pathname(pathname):
    """
    Return True if the filename is clean
    Return False if the filename is not clean
    """
    return pathname.lower().strip() == clean_path(pathname).lower()


def rename_path_to_clean(fqdir):
    cur_dir = os.path.realpath(fqdir)
    if check_pathname(fqdir) is False:
        os.rename(cur_dir, clean_path(cur_dir))
#    except exceptions.OSError:
#        print "os error resolving - %s" % cur_dir
#        print "original - ", cur_dir
#        print "new - ", clean_path(cur_dir)
#        return False
#
#    except exceptions.AttributeError:
#        print "Error with Directory, %s" % (cur_dir)
#        return False
#    finally:
#        return True

def check_files_in_directory(fqdn):
    realpath = os.path.realpath(fqdn)
    files = scandir.walk(realpath).next()[2]
    for filename in files:
        if check_filename(filename) is False:
            print "bad fn - ", filename
            print "good fn - ", clean_filename(filename)
            rename_file_to_clean(os.path.join(realpath,filename))

def rename_file_to_clean(fqfn):
    cur_dir, cur_filename = os.path.split(os.path.realpath(fqfn))
    try:
        print (fqfn, os.path.join(cur_dir, clean_filename(cur_filename)))
        os.rename(fqfn, os.path.join(cur_dir, clean_filename(cur_filename)))
    except exceptions.OSError:
        print "os error resolving - %s" % cur_dir
        print "original - ", fqfn
        print "new - ", os.path.join(cur_dir, clean_filename(cur_filename))
        return False

    except exceptions.AttributeError:
        print "Error with Directory, %s" % (cur_dir)
        return False
    finally:
        return True

