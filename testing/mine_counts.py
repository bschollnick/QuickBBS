from timeit import timeit
import os
import mimetypes

setupTime = 'from mimetypes import guess_type'

setupNew = "mdict = {'.jpeg':'image/jpg'}"
old = '''
mtype = guess_type("test.jpg")[0]
if mtype is None:
    mtype = 'application/octet-stream'
'''

new = '''mtype = mdict[".jpeg"]'''

print("old : ", timeit(stmt=old, number=500000, setup=setupTime))
print("new : ", timeit(stmt=new, number=500000, setup=setupNew))
