from timeit import timeit
import os


new = '''
def counter(fs_entry):
    files = fs_entry.is_file()

    return (files, not fs_entry.is_file())

mapdata = list(map(counter, fs_entries.values()))
files = sum(files for files, _ in mapdata)
dirs = sum(dirs for _, dirs in mapdata)
#dirs = len(fs_entries)-files
'''
#dirs = sum(dirs for _, dirs in mapdata)

old = '''
files = 0
dirs = 0
for fs_item in fs_entries:
   is_file = fs_entries[fs_item].is_file()
   files += is_file
   dirs += not is_file
'''

# moving to values - dropped .03
# eliminating the dirs is_file - dropped .02
# switching to os.Direntry.is_file - added .02
old2 = '''
files = 0
# files = sum(map(os.DirEntry.is_file, fs_entries.values()))
for fs_item in fs_entries.values():
#   files += os.DirEntry.is_file(fs_item) #.is_file()
    files += fs_item.is_file()
dirs = len(fs_entries) - files
'''
kelly= '''
files = sum(map(os.DirEntry.is_file, fs_entries.values()))
dirs = len(fs_entries) - files
'''

fs_location = '/Volumes/4TB_Drive/gallery/albums/hentai_idea/Hyp-Collective/New/Goning_South/Gonig_South'
fs_data = {}
for item in os.scandir(fs_location):
    fs_data[item.name] = item

print("New : ", timeit(stmt=new, number=1000, globals={'fs_entries':fs_data}))
print("old : ", timeit(stmt=old, number=1000, globals={'fs_entries':fs_data}))
print("old2 : ", timeit(stmt=old2, setup="import os", number=1000, globals={'fs_entries':fs_data}))
print("kelly : ", timeit(stmt=kelly, setup="import os", number=1000, globals={'fs_entries':fs_data}))
