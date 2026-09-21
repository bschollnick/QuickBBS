"""Middleware to ensure filetypes are loaded once per worker process."""

from asgiref.sync import iscoroutinefunction, sync_to_async

from filetypes.models import load_filetypes


class FiletypeLoaderMiddleware:
    """Ensure filetypes are loaded once per worker process.

    Loading happens on the FIRST REQUEST, not at construction: `__init__`
    can run in an async context even under WSGI, where a DB read is
    unsafe.

    Supports both WSGI (sync) and ASGI (async) modes.
    """

    def __init__(self, get_response):
        """Initialize the middleware. Loads no filetypes; see the class docstring.

        Args:
            get_response: The next middleware or view in the chain
        """
        self.get_response = get_response
        # Detect if we're in async mode
        self.async_mode = iscoroutinefunction(get_response)
        self._loaded = False

        # NEVER load in __init__ - always defer to first request
        # __init__ can run in async context even in WSGI mode during testing
        # Let the first request handler load it safely

    def __call__(self, request):
        """
        Process the request with no per-request overhead (WSGI sync mode).

        Args:
            request: Django request object

        Returns:
            Response from the next middleware or view
        """
        # Load on first request if not already loaded
        if not self._loaded:
            load_filetypes()
            self._loaded = True
        return self.get_response(request)

    async def __acall__(self, request):
        """
        Process the request with no per-request overhead (ASGI async mode).

        Args:
            request: Django request object

        Returns:
            Response from the next middleware or view
        """
        # Load on first request if not already loaded (async-safe)
        if not self._loaded:
            await sync_to_async(load_filetypes)()
            self._loaded = True
        return await self.get_response(request)
