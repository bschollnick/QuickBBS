"""
Quick script to check if a SHA256 exists in the database.
"""

import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")
django.setup()

from quickbbs.models import FileIndex

# pylint: disable=wrong-import-position,wrong-import-order
from thumbnails.models import ThumbnailFiles

# pylint: enable=wrong-import-position,wrong-import-order

SHA = "be4e5fa108e54e43624e2949c07325e5fc2913150591b573190d19c8ef2833f1"

print("=" * 80)
print(f"Searching for SHA: {SHA}")
print("=" * 80)

# Check FileIndex - file_sha256
print("\n1. Checking FileIndex.file_sha256...")
file_by_file_sha = FileIndex.objects.filter(file_sha256=SHA)
print(f"   Found {file_by_file_sha.count()} records")
if file_by_file_sha.exists():
    for f in file_by_file_sha:
        print(f"   - ID: {f.id}, Name: {f.name}, Path: {f.fqpndirectory}")
        print(f"     has new_ftnail: {f.new_ftnail is not None}")
        print(f"     is_generic_icon: {f.is_generic_icon}")
        if f.new_ftnail:
            print(f"     ThumbnailFiles ID: {f.new_ftnail.id}")
            print(f"     small_thumb exists: {bool(f.new_ftnail.small_thumb)}")
            print(f"     medium_thumb exists: {bool(f.new_ftnail.medium_thumb)}")
            print(f"     large_thumb exists: {bool(f.new_ftnail.large_thumb)}")

# Check FileIndex - unique_sha256
print("\n2. Checking FileIndex.unique_sha256...")
file_by_unique_sha = FileIndex.objects.filter(unique_sha256=SHA)
print(f"   Found {file_by_unique_sha.count()} records")
if file_by_unique_sha.exists():
    for f in file_by_unique_sha:
        print(f"   - ID: {f.id}, Name: {f.name}, Path: {f.fqpndirectory}")
        print(f"     has new_ftnail: {f.new_ftnail is not None}")
        print(f"     is_generic_icon: {f.is_generic_icon}")

# Check ThumbnailFiles
print("\n3. Checking ThumbnailFiles.sha256_hash...")
thumb_records = ThumbnailFiles.objects.filter(sha256_hash=SHA)
print(f"   Found {thumb_records.count()} records")
if thumb_records.exists():
    for t in thumb_records:
        print(f"   - ID: {t.id}")
        print(f"     small_thumb exists: {bool(t.small_thumb)}")
        print(f"     medium_thumb exists: {bool(t.medium_thumb)}")
        print(f"     large_thumb exists: {bool(t.large_thumb)}")
        # Check how many FileIndex records reference this thumbnail
        file_refs = FileIndex.objects.filter(file_sha256=SHA)
        print(f"     Referenced by {file_refs.count()} FileIndex records")

print("\n" + "=" * 80)
print("Search complete!")
print("=" * 80)
