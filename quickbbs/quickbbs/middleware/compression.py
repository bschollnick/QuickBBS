"""
Async-safe wrapper around django-compression-middleware's CompressionMiddleware.
"""

from compression_middleware.middleware import CompressionMiddleware
from django.http import HttpRequest, HttpResponseBase


class AsyncSafeCompressionMiddleware(CompressionMiddleware):  # pylint: disable=too-few-public-methods
    """
    CompressionMiddleware that leaves async streaming responses untouched.

    django-compression-middleware 0.5.0's stream compressors
    (zstd_compress_stream / brotli / gzip) are synchronous generators that
    iterate ``for item in sequence``. Wrapping an async iterator — e.g. the
    aiofiles-backed file downloads built by
    frontend.serve_up.build_async_ranged_response — raises
    ``TypeError: 'async_generator' object is not iterable`` when the ASGI
    handler consumes the response.

    Skipping these responses is correct, not just safe: they are media file
    downloads (images/video/archives) that gain nothing from recompression,
    and compressing a 206 Partial Content body would corrupt Range semantics
    (Content-Range offsets refer to the unencoded file bytes).
    """

    def process_response(self, request: HttpRequest, response: HttpResponseBase) -> HttpResponseBase:
        """
        Compress the response unless it streams from an async iterator.

        Args:
            request: The incoming Django request.
            response: The outgoing response, possibly streaming.

        Returns:
            The response untouched when it is an async streaming response,
            otherwise whatever CompressionMiddleware.process_response returns
            (the response, compressed when the client and content allow it).
        """
        if getattr(response, "streaming", False) and getattr(response, "is_async", False):
            return response
        return super().process_response(request, response)
