from xattr import xattr
from struct import unpack
import argparse
import sys
import os
import shutil
import scandir

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

def main(args):
    root_src_dir = args.source
    root_target_dir = args.target

    operation= 'copy' # 'copy' or 'move'

    for src_dir, dirs, files in os.walk(root_src_dir):
        dst_dir = src_dir.replace(root_src_dir, root_target_dir)
        dst_dir_files = get_files_recursive(dst_dir)
        for file_ in files:
            src_file = os.path.join(src_dir, file_)
            dst_file = os.path.join(dst_dir, file_)

            if os.path.exists(dst_file):
                #os.remove(dst_file)
                continue
            if get_color(src_file)[0] != 0:
                # the file has a label (any label), copy or move it
                if not os.path.exists(dst_dir):
                    os.makedirs(dst_dir)
                if file_.lower() in dst_dir_files:
                    #print ("%s File already exists" % dst_file)
                    continue
                if operation is 'copy':
#                    print("src", src_file)
#                    print("dst", dst_file)
                    shutil.copy(src_file, dst_file)
                elif operation is 'move':
                    shutil.move(src_file, dst_dir)
#            else:
                # the file doesn't have a label, but exists in destination
#                if os.path.exists(dst_file):
#                    os.remove(dst_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="The source path")
    parser.add_argument("target", help="The target path")
    print()
    args = parser.parse_args()
    main(args)
