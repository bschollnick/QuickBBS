# from models import *
import hashlib
import os


def normalize_fqpn(fqpn_directory):
    fqpn_directory = fqpn_directory.lower().strip()
    if not fqpn_directory.endswith(os.sep):
        fqpn_directory = fqpn_directory + os.sep
    return fqpn_directory


def convert_text_to_md5_hdigest(text):
    return hashlib.md5(text.title().strip().encode("utf-16")).hexdigest()


testdir = r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/test/anime/"
testdir = r"/volumes/c-8tb/gallery/quickbbs/albums/-These"
# testdir = "/volumes/c-8tb/gallery/quickbbs/albums/-these/three  sexy shiny chicks model [set]/aiden star/"
print("MD5:", convert_text_to_md5_hdigest(testdir))
print(
    "normalized MD5:",
    normalize_fqpn(testdir),
    convert_text_to_md5_hdigest(normalize_fqpn(testdir)),
)
print(
    "abspath normalized MD5:",
    os.path.abspath(normalize_fqpn(testdir)),
    convert_text_to_md5_hdigest(os.path.abspath(normalize_fqpn(testdir))),
)

print("MD5:", convert_text_to_md5_hdigest(testdir))
parent_dir = os.path.abspath(os.path.join(testdir, os.pardir))
print(parent_dir, normalize_fqpn(parent_dir))

md5 = convert_text_to_md5_hdigest(normalize_fqpn(parent_dir))
print(f"{parent_dir}: ", md5)
