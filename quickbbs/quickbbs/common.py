import hashlib
import os
import pathlib
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1000)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def get_dir_sha(fqpn_directory: str) -> str:
    """
    Return the SHA256 hash of the normalized directory path.

        fqpn_directory: Fully qualified pathname of the directory
    Returns: SHA256 hash of the normalized directory path as hexdigest string
    """
    fqpn_directory = normalize_fqpn(fqpn_directory)
    return hashlib.sha256(fqpn_directory.encode("utf-8")).hexdigest()


@lru_cache(maxsize=5000)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def normalize_fqpn(fqpn_directory: str) -> str:
    """
    Normalize the directory structure fully qualified pathname.

    Converts path to lowercase, resolves to absolute path, and ensures
    trailing separator.

        fqpn_directory: Directory path to normalize
    Returns: Normalized directory path with trailing separator
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

        fqfn: The fully qualified filename of the file to be hashed
    Returns: Tuple of (file_sha256, unique_sha256) where:
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


async def async_get_file_sha(fqfn: str) -> tuple[str | None, str | None]:
    """
    Async version: Return the SHA256 hashes of the file as hexdigest strings.

    Non-blocking file I/O for use in async contexts. Uses aiofiles for
    async file operations to prevent blocking the event loop.

    Generates both a file-content hash and a unique hash that includes
    the file path.

        fqfn: The fully qualified filename of the file to be hashed
    Returns: Tuple of (file_sha256, unique_sha256) where:
        - file_sha256: SHA256 hash of file contents only
        - unique_sha256: SHA256 hash of file contents + title-cased filepath
                        (makes hash unique to both content and location)
    """
    import aiofiles

    sha256 = hashlib.sha256()
    try:
        async with aiofiles.open(fqfn, "rb") as filehandle:
            while chunk := await filehandle.read(4096):
                sha256.update(chunk)
        file_sha256 = sha256.hexdigest()
        sha256.update(str(fqfn).title().encode("utf-8"))
        unique_sha256 = sha256.hexdigest()
    except (FileNotFoundError, OSError, IOError):
        file_sha256 = None
        unique_sha256 = None
        print(f"Error producing SHA 256 for: {fqfn}")
    return file_sha256, unique_sha256
