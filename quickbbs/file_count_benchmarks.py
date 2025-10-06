import os
from timeit import timeit

new = """
def counter(fs_entry):
    files = fs_entry.is_file()

    return (files, not fs_entry.is_file())

mapdata = list(map(counter, fs_entries.values()))
files = sum(files for files, _ in mapdata)
dirs = sum(dirs for _, dirs in mapdata)
#dirs = len(fs_entries)-files
"""
# dirs = sum(dirs for _, dirs in mapdata)

old = """
files = 0
dirs = 0
for fs_item in fs_entries:
   is_file = fs_entries[fs_item].is_file()
   files += is_file
   dirs += not is_file
"""

# moving to values - dropped .03
# eliminating the dirs is_file - dropped .02
# switching to os.Direntry.is_file - added .02
old2 = """
files = 0
# files = sum(map(os.DirEntry.is_file, fs_entries.values()))
for fs_item in fs_entries.values():
#   files += os.DirEntry.is_file(fs_item) #.is_file()
    files += fs_item.is_file()
dirs = len(fs_entries) - files
"""
kelly = """
files = sum(map(os.DirEntry.is_file, fs_entries.values()))
dirs = len(fs_entries) - files
"""

kelly2 = """
def isfile(entry):
    return entry.is_file()
    
files = sum(map(is_file, fs_entries.values()))
dirs = len(fs_entries) - files
"""

new_filter = """
def is_file(entry):
    return entry.is_file()

# def is_dir(entry):
#     return entry.is_dir()

files = len(list(filter(is_file, fs_entries.values())))
dirs = len(fs_entries)-files
"""

new_filter2 = """
files = len(list(filter(os.DirEntry.is_file, fs_entries.values())))
dirs = len(fs_entries)-files
"""

claude = """
files = sum(1 for entry in fs_entries.values() if entry.is_file())
dirs = len(fs_entries) - files
return (files, dirs)
"""

fs_location = "/Volumes/masters/masters/instagram2/d/disharmonica"
fs_location = "/Volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/Hyp-Collective/New/Goning_South/Gonig_South"
fs_data = {}
for item in os.scandir(fs_location):
    fs_data[item.name] = item
print(f"Number of Entries: {len(fs_data)}")
print("New : ", timeit(stmt=new, number=1000, globals={"fs_entries": fs_data}))
print("old : ", timeit(stmt=old, number=1000, globals={"fs_entries": fs_data}))
print(
    "old2 : ",
    timeit(stmt=old2, setup="import os", number=1000, globals={"fs_entries": fs_data}),
)
print(
    "kelly : ",
    timeit(stmt=kelly, setup="import os", number=1000, globals={"fs_entries": fs_data}),
)
print(
    "kelly2 : ",
    timeit(stmt=kelly, setup="import os", number=1000, globals={"fs_entries": fs_data}),
)
print(
    "new w/filter : ",
    timeit(stmt=new_filter, number=1000, globals={"fs_entries": fs_data}),
)
print(
    "new2 w/filter : ",
    timeit(stmt=new_filter, setup="import os", number=1000, globals={"fs_entries": fs_data}),
)
print(
    "claude : ",
    timeit(stmt=new_filter, setup="import os", number=1000, globals={"fs_entries": fs_data}),
)


def is_file(entry):
    return entry.is_file()


files = len(list(filter(is_file, fs_data.values())))
dirs = len(fs_data) - files
print(files, dirs)
