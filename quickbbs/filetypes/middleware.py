"""Middleware to ensure filetypes are loaded once per worker process."""

from filetypes.models import load_filetypes


class FiletypeLoaderMiddleware:
    """
    Ensure filetypes are loaded once per worker process.

    This middleware loads the filetype data from the database when the worker
    process starts, avoiding the need to check/load on every request.
    """

    def __init__(self, get_response):
        """
        Initialize middleware and load filetypes.

        This executes once when the worker process starts.

        Args:
            get_response: The next middleware or view in the chain
        """
        self.get_response = get_response
        # Load filetypes once when worker starts
        load_filetypes()

    def __call__(self, request):
        """
        Process the request with no per-request overhead.

        Args:
            request: Django request object

        Returns:
            Response from the next middleware or view
        """
        return self.get_response(request)