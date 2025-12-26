"""
DEPRECATED: This module is deprecated and scheduled for removal in v4.0.

All functions in this module are deprecated:
- verify_login_status() - Use django-allauth instead
- respond_as_attachment() - Use serve_up.send_file_response() instead
- stream_video() - No longer supported (feature removed)
- file_iterator() - No longer supported
- g_option() - Removed, use request.GET.get() directly

Future web utilities should be added to frontend.utilities instead.
"""

from __future__ import annotations

import logging
import warnings

logger = logging.getLogger(__name__)


def verify_login_status(request, force_login=False) -> bool:
    """
    DEPRECATED: This function is deprecated and will be removed in v4.0.

    Use django-allauth for authentication instead.
    Authentication is now handled by:
    - @login_required decorator for views
    - request.user.is_authenticated for checks

    This function had critical security issues:
    - No KeyError handling for POST parameters
    - No return statement (returned None instead of bool)
    - No CSRF protection
    - No HTTP method validation

    :Args:
        request: Django request object
        force_login: Unused parameter

    :Returns:
        Never returns (raises NotImplementedError)
    """
    warnings.warn(
        (
            "verify_login_status() is deprecated and will be removed in v4.0. "
            "Use django-allauth and @login_required instead."
        ),
        DeprecationWarning,
        stacklevel=2,
    )
    raise NotImplementedError("This function is no longer supported. Use django-allauth for authentication.")


def respond_as_attachment(request, file_path, original_filename):
    """
    DEPRECATED: This function is deprecated and will be removed in v4.0.

    Use frontend.serve_up.send_file_response() instead.

    This function had a file handle leak vulnerability.

    :Args:
        request: Django request object
        file_path: Path to file directory
        original_filename: Name of file to send

    :Returns:
        Never returns (raises NotImplementedError)
    """
    warnings.warn(
        (
            "respond_as_attachment() is deprecated and will be removed in v4.0. "
            "Use serve_up.send_file_response() instead."
        ),
        DeprecationWarning,
        stacklevel=2,
    )
    raise NotImplementedError("This function is no longer supported. Use serve_up.send_file_response() instead.")


def stream_video(request, fqpn, content_type="video/mp4"):
    """
    DEPRECATED: This function is deprecated and will be removed in v4.0.

    This function was orphaned after video.js feature reversal.

    :Args:
        request: Django request object
        fqpn: Fully qualified path name to video file
        content_type: MIME type of video

    :Returns:
        Never returns (raises NotImplementedError)
    """
    warnings.warn(
        "stream_video() is deprecated and will be removed in v4.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise NotImplementedError("This function is no longer supported.")


def file_iterator(file_path, chunk_size=8192, offset=0, length=None):
    """
    DEPRECATED: This function is deprecated and will be removed in v4.0.

    This function was only used by stream_video() which is also deprecated.

    :Args:
        file_path: Path to file for iteration
        chunk_size: Size of chunks to read
        offset: Starting offset in file
        length: Total length to read

    :Returns:
        Never returns (raises NotImplementedError)
    """
    warnings.warn(
        "file_iterator() is deprecated and will be removed in v4.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise NotImplementedError("This function is no longer supported.")


# TODO: This module is scheduled for complete removal in v4.0
# All functions are deprecated. Future web utilities should go in
# frontend.utilities instead.
