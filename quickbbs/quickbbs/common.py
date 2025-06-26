import hashlib
import os
import pathlib
from functools import lru_cache
from typing import Optional


# Optimized hash function - use a single consistent hashing method
@lru_cache(maxsize=1000)
def get_dir_sha(fqpn_directory) -> str:
    """
    Return the SHA256 hash of the normalized directory path
    """
    fqpn_directory = normalize_fqpn(fqpn_directory)
    return hashlib.sha256(fqpn_directory.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1000)
def normalize_fqpn(fqpn_directory) -> str:
    """
    Normalize the directory structure fully qualified pathname
    """
    # Use cached property of Path object if possible
    fqpn = str(pathlib.Path(fqpn_directory).resolve()).lower().strip()

    # Add trailing separator only if needed
    if not fqpn.endswith(os.sep):
        fqpn += os.sep

    return fqpn


def get_file_sha(fqfn) -> tuple[Optional[str], Optional[str]]:
    """
    Return the SHA256 hash of the file as a hexdigest string

    Args:
        fqfn (str) : The fully qualified filename of the file to be hashed

    :return: The SHA256 hash of the file + fqfn as a hexdigest string
    """
    sha256 = hashlib.sha256()
    unique_sha256 = None
    try:
        with open(fqfn, "rb") as filehandle:
            for chunk in iter(lambda: filehandle.read(4096), b""):
                # Update the hash with each chunk
                sha256.update(chunk)
        file_sha256 = sha256.hexdigest()
        sha256.update(str(fqfn).title().encode("utf-8"))
        unique_sha256 = sha256.hexdigest()
    except (FileNotFoundError, OSError, IOError):
        file_sha256 = None
        unique_sha256 = None
        print(f"Error producing SHA 256 for: {fqfn}")
    return file_sha256, unique_sha256
