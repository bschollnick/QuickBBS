import os
import scandir
import timeit


testpath = "/Users/Benjamin/Dropbox/Gallery2/albums/test100"


def test1():
    scan_directory = os.path.realpath(testpath).strip()
    fcount = 0
    dcount = 0
    for x in scandir.scandir(scan_directory):
        fcount += x.is_file()
        dcount += x.is_dir()
    return (fcount, dcount)

def test2():
    scan_directory = os.path.realpath(testpath).strip()
    num_files = len([f for f in scandir.scandir(testpath) if f.is_file()])
    num_dirs = len([f for f in scandir.scandir(testpath) if f.is_dir()])
    return (num_files, num_dirs)

#print timeit.timeit(test1, number=10000)
#print timeit.timeit(test2, number=10000)
setup = """
import common
import urllib2
replacements = {'"':"`", "'":"`",
                    ",":"", "#":"",
                    "*":"", "@":"",
                    ":":"-", "|":""}
"""

replace_all_test="""
common.replace_all(urllib2.unquote("alskdjajnvzxmbv2k4rhk.txt"),replacements)
"""

multiple_replace_test="""
common.multiple_replace(replacements, urllib2.unquote("alskdjajnvzxmbv2k4rhk.txt"))
"""

print "replace_all-",timeit.timeit(replace_all_test, number=1000000, setup=setup)
print "multiple_replace-",timeit.timeit(replace_all_test, number=1000000, setup=setup)

