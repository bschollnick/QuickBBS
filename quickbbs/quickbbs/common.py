import hashlib
import os
import pathlib
from functools import lru_cache


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
