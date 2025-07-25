import argparse
import os
import re
import shutil
import sys
from struct import unpack

import django
import imagehash
import xattr

sys.path.append("/volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs_settings")
django.setup()

from django_thread import ThreadPoolExecutor

from quickbbs.frontend.depreciated.cached_exists import *

MAX_THREADS = 60

executor = ThreadPoolExecutor(max_workers=MAX_THREADS)

app_dir = os.path.split(sys.argv[0])[0]
print(app_dir)
sys.path.append(os.path.join(app_dir, ".."))

colornames = {
    0: "none",
    1: "gray",
    2: "green",
    3: "purple",
    4: "blue",
    5: "yellow",
    6: "red",
    7: "orange",
}


def get_color(filename):
    attrs = xattr.xattr(filename)
    try:
        finder_attrs = attrs["com.apple.FinderInfo"]
        flags = unpack(32 * "B", finder_attrs)
        color = flags[9] >> 1 & 7
    except KeyError:
        color = 0

    return (color, colornames[color])


# used in Utilities
replacements = {"?": "", "/": "", ":": "", "#": "_"}
regex = re.compile("(%s)" % "|".join(map(re.escape, replacements.keys())))


def multiple_replace(dictdata, text):  # , compiled):
    # Create a regular expression  from the dictionary keys

    # For each match, look-up corresponding value in dictionary
    return regex.sub(lambda mo: dictdata[mo.string[mo.start() : mo.end()]], text)


def process_folder(src_dir, dst_dir, files, use_shas, use_imagehash):
    filedb = cached_exist(
        use_shas=use_shas,
        use_image_hash=use_imagehash,
        FilesOnly=True,
        image_hasher=imagehash.phash,
    )
    filedb.MAX_SHA_SIZE = 1024 * 1024 * 2
    operation = "copy"  # 'copy' or 'move'
    filedb.read_path(dst_dir, recursive=True)
    for file_ in files:
        fext = os.path.splitext(file_)[1].lower()
        if fext in filedb._archives:  # filedb._graphics and fext not in filedb._movies:
            continue

        src_sha = None
        src_hash = None
        src_file = os.path.join(src_dir, file_)
        dst_file = os.path.join(dst_dir, multiple_replace(replacements, file_)).replace(
            " ", "_"
        )

        if get_color(src_file)[0] != 0:
            # the file has a label (any label), copy or move it
            if filedb.search_file_exist(os.path.split(dst_file)[1])[0]:
                # Please remember that search_file_exists works on the filename, and not the FQPN.
                # print("Skipping (already exists) - ", dst_file)
                continue
            #
            if use_shas:
                src_sha = filedb.generate_sha224(src_file, hexdigest=True)
                if filedb.search_sha224_exist(shaHD=src_sha)[0]:
                    # print("Skipping (Sha already exists) - ", dst_file)
                    # If the file already exists, then skip
                    # os.remove(dst_file)
                    continue

            if use_imagehash:
                if os.path.splitext(src_file)[1].lower() in filedb._graphics:
                    src_hash = filedb.generate_imagehash(src_file)
                    if filedb.search_imagehash_exist(img_hash=src_hash)[0]:
                        # check to see if the image exists via image hashing
                        # if exists, skip
                        continue

            if not os.path.exists(dst_dir):
                try:
                    os.makedirs(dst_dir)
                except FileExistsError:
                    pass

            # We know the file doesn't exist, since it wasn't found via
            # search_file_exists
            if operation == "copy":
                shutil.copy2(src_file, dst_file)
            elif operation == "move":
                shutil.move(src_file, dst_dir)
            filedb.addFile(
                dirpath=dst_dir,
                filename=file_,
                sha_hd=src_sha,
                filesize=None,
                mtime=None,
                img_hash=src_hash,
            )
    # filedb.clear_path(path_to_clear=dst_dir)
    # filedb.clear_path(path_to_clear=src_dir)


def main(args):
    use_imagehash = False
    use_shas = False
    root_src_dir = args.source
    root_target_dir = args.target

    print("Starting with ", root_src_dir)
    print("Target path", root_target_dir)
    if not os.path.exists(root_src_dir):
        print(f"{root_src_dir} can not be found.")
        sys.exit()

    futures = []
    for src_dir, dirs, files in os.walk(root_src_dir, topdown=True):
        dst_dir = (
            src_dir.replace(root_src_dir, root_target_dir).title().replace(" ", "_")
        )
        futures.append(
            executor.submit(
                process_folder, src_dir, dst_dir, files, use_shas, use_imagehash
            )
        )
    _ = [f.result() for f in futures]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="The source path")
    parser.add_argument("target", help="The target path")
    print()
    print("Starting up...")
    args = parser.parse_args()
    main(args)
