from xattr import xattr
from struct import unpack
import argparse
import sys
import os
import shutil
import scandir
import re
from cached_exists import *


colornames = {
    0: 'none',
    1: 'gray',
    2: 'green',
    3: 'purple',
    4: 'blue',
    5: 'yellow',
    6: 'red',
    7: 'orange',
}

def get_color(filename):
    attrs = xattr(filename)
    try:
        finder_attrs = attrs[u'com.apple.FinderInfo']
        flags = unpack(32*'B', finder_attrs)
        color = flags[9] >> 1 & 7
    except KeyError:
        color = 0

    return (color, colornames[color])

def get_files_in_onedir(directory):
    filenames = []
    with os.scandir(directory) as i:
        for entry in i:
            if entry.is_file():
                filenames.append(entry.name.lower())
    return filenames

def get_files_recursive(directory):
    filenames = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower() not in filenames:
                filenames.append(file.lower())
    return filenames

# used in Utilities
replacements={'?':'','/':"", ":":"", "#":"_"}
regex = re.compile("(%s)" % "|".join(map(re.escape, replacements.keys())))

def multiple_replace(dict, text):#, compiled):
    # Create a regular expression  from the dictionary keys

    # For each match, look-up corresponding value in dictionary
    return regex.sub(lambda mo: dict[mo.string[mo.start():mo.end()]], text)


def main(args):
    root_src_dir = args.source
    root_target_dir = args.target

    operation= 'copy' # 'copy' or 'move'
    filedb = cached_exist()
    for src_dir, dirs, files in os.walk(root_src_dir, topdown=False):
        dst_dir = src_dir.replace(root_src_dir, root_target_dir)
        #dst_dir_files = get_files_recursive(dst_dir)
        for file_ in files:
            src_file = os.path.join(src_dir, file_)
            dst_file = os.path.join(dst_dir, multiple_replace(replacements,file_))

#            filedb.read_path(dst_dir, sha=True)
            #if os.path.exists(dst_file):
                #continue
            if get_color(src_file)[0] != 0:
                # the file has a label (any label), copy or move it

                if filedb.file_exist(dst_file):
                    #print("Skipping (Filename already exists) - ", dst_file)
                    continue
                src_sha = filedb.generate_sha224(src_file)
                if filedb.file_exist(dst_file, sha_hd=src_sha, sha=True):
                    #print("Skipping (Sha already exists) - ", dst_file)
                    # If the file already exists, then skip
                    #os.remove(dst_file)
                    continue
                if not os.path.exists(dst_dir):
                    os.makedirs(dst_dir)
                #if file_.lower() in dst_dir_files:
                #    continue
                if operation == 'copy':
                    shutil.copy2(src_file, dst_file)
                elif operation == 'move':
                    shutil.move(src_file, dst_dir)
                filedb.clear_path(path_to_clear=dst_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="The source path")
    parser.add_argument("target", help="The target path")
    print()
    args = parser.parse_args()
    main(args)


#  after_filename = multiple_replace(constants.replacements, lower_filename)#, regex)
