#import scandir
import sys

#from xattr import xattr
from old.cached_exists import *

filedb = cached_exist(use_shas=True, FilesOnly=True)
filedb.MAX_SHA_SIZE = 1024*1024*5
for x in sys.argv:
    print("%s - %s" % (os.path.basename(x),
                       bytearray(filedb.generate_sha224(x)).hex()))