import directory_caching
import timeit

test = """
cdl = directory_caching.Cache()
cdl.smart_read("/Users/Benjamin" )
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Actresses")
"""

setup = """
import directory_caching
cdl = directory_caching.Cache()
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Hentai idea")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Actresses")
"""

oldsingle_test = """
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums")[1]
"""

newsingle_test = """
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums")[1]
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums/Hentai Idea")[1]
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Actresses")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Hentai Idea")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Hentai Idea")
"""

multiple_test = """
#cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums")[1]
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums/Hentai Idea")[1]
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums")[1]
dirs = cdl.return_sort_name(scan_directory="/Volumes/NewStorage/Gallery/Albums/Hentai Idea")[1]
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Actresses")
dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
"""

newmultiple_test = """
#cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
dirs = cdl.return_sorted(scan_directory="/Volumes/NewStorage/Gallery/Albums")[1]
dirs = cdl.return_sorted(scan_directory="/Volumes/NewStorage/Gallery/Albums/Hentai Idea")[1]
dirs = cdl.return_sorted(scan_directory="/Volumes/NewStorage/Gallery/Albums")[1]
dirs = cdl.return_sorted(scan_directory="/Volumes/NewStorage/Gallery/Albums/Hentai Idea")[1]
#cdl.smart_read("/Volumes/NewStorage/Gallery/Albums")
#cdl.smart_read("/Volumes/NewStorage/Gallery/Albums/Actresses")
#dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
#dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
#dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
"""


print "Single ",timeit.timeit(newsingle_test, setup=setup, number=25)
print "Single ",timeit.timeit(newsingle_test, setup=setup, number=25)
print "Single ",timeit.timeit(newsingle_test, setup=setup, number=25)
print "Single ",timeit.timeit(newsingle_test, setup=setup, number=25)
print "multiple ",timeit.timeit(multiple_test, setup=setup, number=25)
print "multiple ",timeit.timeit(multiple_test, setup=setup, number=25)
print "multiple ",timeit.timeit(multiple_test, setup=setup, number=25)
#print "newmultiple ",timeit.timeit(newmultiple_test, setup=setup, number=25)
#print timeit.timeit(test, setup=setup_no_ordered, number=10)
sys.exit(1)


print "Counts"
filecount, dir_count = cdl._return_file_dir_count("/Users/Benjamin")
print "files :", filecount
print "dirs  :", dir_count
print
print "increment tests"

print "-"*10
#testpath = "/Users/Benjamin/Dropbox/Gallery2/albums/test100"


def test1():
    cdl.smart_read( "/Users/Benjamin" )
    filecount, dir_count = cdl._return_file_dir_count("/Users/Benjamin")
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

print timeit.timeit(test1, number=10000)
print timeit.timeit(test2, number=10000)

# print "Movies +0, should return current directory (e.g. movies)"
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Movies",
#             offset=0)
# print "-"*10
# print "(Movies +2) Should be my games"
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Movies",
#             offset=2)
# print "-"*10
# print "(movies -5) Should return Google drive"
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Movies",
#             offset=-5)
# print "-"*10
# print "Decrement past the boundary, should return none."
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Applications",
#             offset=-442)
# print "-"*10
# print "Increment from beginning by 2, should be Calibre Library"
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Applications",
#             offset=+2)
# print "-"*10
# print "Decrease from end by 2, should be SmithMicrodownloader"
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Wallpaper",
#             offset=-2)
# print "-"*10
# print "Try to increment beyond dir listings. Should Return None"
# print cdl.return_current_directory_offset(\
#             scan_directory = "/Users/Benjamin",
#             current_directory="Wallpaper",
#             offset=+999)

print "Ctime :"
cdl.return_sort_ctime(scan_directory = "/Users/Benjamin")
print "modified time :"
cdl.return_sort_lmod(scan_directory = "/Users/Benjamin")
