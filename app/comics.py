#		Gallery Comic Support
#
#
import exceptions
import os
import os.path
import rarfile
import zipfile

rarfile.PATH_SEP = '/'

def verify_is_zipfile(fqfn):
    return zipfile.is_zipfile(fqfn)


def return_zipfile_filelist(fqfn):
    zfile = zipfile.ZipFile(fqfn, 'r')
    data = []
    for x in zfile.namelist():
        if x.startswith("__MACOSX") or os.path.split(x)[1] == "":
            pass
        else:
            data.append(x)
    return data

def return_zipfile_filecontents(fqfn, filename):
    try:
        zfile = zipfile.ZipFile(fqfn, 'r')
        return zfile.read(filename)
    except:
        return None

def return_rarfile_filelist(fqfn):
    try:
        rfile = rarfile.RarFile(fqfn, 'r')
        data = []
        for x in rfile.namelist():
            if x.startswith("__MACOSX") or os.path.split(x)[1] == "":
                pass
            else:
                data.append(x)
        return data
    except rarfile.BadRarFile:
        return None

def return_rarfile_filecontents(fqfn, filename):
    print fqfn, filename
    try:
        rfile = rarfile.RarFile(fqfn, 'r')
        return rfile.read(filename)
    except exceptions.TypeError:
        print "Type Error reading - %s - %s" % (fqfn, filename)
        return None
    except rarfile.BadRarFile:
        print "Corrupt Rar File - %s - %s" % (fqfn, filename)
        return None
