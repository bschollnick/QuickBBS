import hashlib
import os
import pathlib
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1000)
def get_dir_sha(fqpn_directory: str) -> str:
    """
    Return the SHA256 hash of the normalized directory path.

    :param fqpn_directory: Fully qualified pathname of the directory
    :return: SHA256 hash of the normalized directory path as hexdigest string
    """
    fqpn_directory = normalize_fqpn(fqpn_directory)
    return hashlib.sha256(fqpn_directory.encode("utf-8")).hexdigest()


@lru_cache(maxsize=5000)
def normalize_fqpn(fqpn_directory: str) -> str:
    """
    Normalize the directory structure fully qualified pathname.

    Converts path to lowercase, resolves to absolute path, and ensures
    trailing separator.

    :param fqpn_directory: Directory path to normalize
    :return: Normalized directory path with trailing separator
    """
    # Use cached property of Path object if possible
    fqpn = str(pathlib.Path(fqpn_directory).resolve()).lower().strip()

    # Add trailing separator only if needed
    if not fqpn.endswith(os.sep):
        fqpn += os.sep

    return fqpn


def get_file_sha(fqfn: str) -> tuple[str | None, str | None]:
    """
    Return the SHA256 hashes of the file as hexdigest strings.

    Generates both a file-content hash and a unique hash that includes
    the file path.

    :param fqfn: The fully qualified filename of the file to be hashed
    :return: Tuple of (file_sha256, unique_sha256) where:
        - file_sha256: SHA256 hash of file contents only
        - unique_sha256: SHA256 hash of file contents + title-cased filepath
                        (makes hash unique to both content and location)
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
