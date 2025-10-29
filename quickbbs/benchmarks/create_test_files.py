# http://stackoverflow.com/questions/14275975/creating-random-binary-files

import os.path
import random
import sys
import time

random.seed(time.time())

filename = sys.argv[1]
file_size = sys.argv[2]

with open(os.path.abspath(filename), "wb") as fout:
    fout.write(os.urandom(int(file_size)*1024*1024))
fout.close()

