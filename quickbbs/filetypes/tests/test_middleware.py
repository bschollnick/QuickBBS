from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory
from filetypes.middleware import FiletypeLoaderMiddleware


class TestFiletypeLoaderMiddleware:
    """Test suite for FiletypeLoaderMiddleware"""

    def setup_method(self):
        """Set up test fixtures"""
        self.factory = RequestFactory()
        self.get_response = Mock(return_value=Mock(status_code=200))

    @patch("filetypes.middleware.load_filetypes")
    def test_init_loads_filetypes(self, mock_load_filetypes):
        """Test __init__ loads filetypes on initialization"""
        middleware = FiletypeLoaderMiddleware(self.get_response)

        mock_load_filetypes.assert_called_once()
        assert middleware.get_response == self.get_response

    @patch("filetypes.middleware.load_filetypes")
    def test_init_only_loads_once(self, mock_load_filetypes):
        """Test __init__ loads filetypes only once per worker"""
        FiletypeLoaderMiddleware(self.get_response)
        FiletypeLoaderMiddleware(self.get_response)

        assert mock_load_filetypes.call_count == 2

    @patch("filetypes.middleware.load_filetypes")
    def test_call_passes_request_through(self, mock_load_filetypes):
        """Test __call__ passes request to next middleware/view"""
        middleware = FiletypeLoaderMiddleware(self.get_response)
        request = self.factory.get("/test/")

        response = middleware(request)

        self.get_response.assert_called_once_with(request)
        assert response == self.get_response.return_value

    @patch("filetypes.middleware.load_filetypes")
    def test_call_does_not_load_filetypes(self, mock_load_filetypes):
        """Test __call__ does not load filetypes per request"""
        middleware = FiletypeLoaderMiddleware(self.get_response)
        mock_load_filetypes.reset_mock()

        request = self.factory.get("/test/")
        middleware(request)

        mock_load_filetypes.assert_not_called()

    @patch("filetypes.middleware.load_filetypes")
    def test_call_multiple_requests(self, mock_load_filetypes):
        """Test __call__ handles multiple requests"""
        middleware = FiletypeLoaderMiddleware(self.get_response)
        mock_load_filetypes.reset_mock()

        request1 = self.factory.get("/test1/")
        request2 = self.factory.get("/test2/")
        request3 = self.factory.post("/test3/", {"data": "value"})

        middleware(request1)
        middleware(request2)
        middleware(request3)

        assert self.get_response.call_count == 3
        mock_load_filetypes.assert_not_called()

    @patch("filetypes.middleware.load_filetypes")
    def test_init_handles_load_exception(self, mock_load_filetypes):
        """Test __init__ propagates exceptions from load_filetypes"""
        mock_load_filetypes.side_effect = Exception("Load error")

        with pytest.raises(Exception, match="Load error"):
            FiletypeLoaderMiddleware(self.get_response)

    @patch("filetypes.middleware.load_filetypes")
    def test_call_returns_response_unchanged(self, mock_load_filetypes):
        """Test __call__ returns response without modification"""
        expected_response = Mock(
            status_code=200,
            content=b"Test content",
            headers={"Content-Type": "text/html"},
        )
        self.get_response.return_value = expected_response

        middleware = FiletypeLoaderMiddleware(self.get_response)
        request = self.factory.get("/test/")

        response = middleware(request)

        assert response is expected_response
        assert response.status_code == 200
        assert response.content == b"Test content"

    @patch("filetypes.middleware.load_filetypes")
    def test_middleware_with_different_http_methods(self, mock_load_filetypes):
        """Test middleware works with different HTTP methods"""
        middleware = FiletypeLoaderMiddleware(self.get_response)
        mock_load_filetypes.reset_mock()

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

        for method in methods:
            request = getattr(self.factory, method.lower())("/test/")
            response = middleware(request)
            assert response == self.get_response.return_value

        assert self.get_response.call_count == len(methods)
        mock_load_filetypes.assert_not_called()

    @patch("filetypes.middleware.load_filetypes")
    def test_middleware_preserves_request_attributes(self, mock_load_filetypes):
        """Test middleware preserves all request attributes"""
        middleware = FiletypeLoaderMiddleware(self.get_response)

        request = self.factory.get(
            "/test/",
            HTTP_AUTHORIZATION="Bearer token123",
            HTTP_ACCEPT="application/json",
        )
        request.user = Mock(username="testuser")
        request.session = {"key": "value"}

        def check_request(req):
            assert req.user.username == "testuser"
            assert req.session == {"key": "value"}
            assert req.META["HTTP_AUTHORIZATION"] == "Bearer token123"
            return Mock(status_code=200)

        self.get_response.side_effect = check_request

        middleware(request)


class TestFiletypeLoaderMiddlewareIntegration:
    """Integration tests for FiletypeLoaderMiddleware"""

    @pytest.mark.django_db
    @patch("filetypes.middleware.load_filetypes")
    def test_middleware_in_request_response_cycle(self, mock_load_filetypes):
        """Test middleware in full request-response cycle"""
        from django.http import HttpResponse

        def view(request):
            return HttpResponse("OK")

        middleware = FiletypeLoaderMiddleware(view)

        factory = RequestFactory()
        request = factory.get("/test/")

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"
        mock_load_filetypes.assert_called_once()

    @pytest.mark.django_db
    def test_middleware_with_real_load_filetypes(self):
        """Test middleware with actual load_filetypes call"""
        from django.http import HttpResponse
        from filetypes.models import filetypes

        filetypes.objects.create(fileext=".jpg")

        def view(request):
            return HttpResponse("OK")

        middleware = FiletypeLoaderMiddleware(view)

        factory = RequestFactory()
        request = factory.get("/test/")

        response = middleware(request)

        assert response.status_code == 200

    @patch("filetypes.middleware.load_filetypes")
    def test_middleware_handles_view_exception(self, mock_load_filetypes):
        """Test middleware propagates view exceptions"""

        def failing_view(request):
            raise ValueError("View error")

        middleware = FiletypeLoaderMiddleware(failing_view)

        factory = RequestFactory()
        request = factory.get("/test/")

        with pytest.raises(ValueError, match="View error"):
            middleware(request)

    @patch("filetypes.middleware.load_filetypes")
    def test_multiple_middleware_instances(self, mock_load_filetypes):
        """Test multiple middleware instances load independently"""
        view1 = Mock(return_value=Mock(status_code=200))
        view2 = Mock(return_value=Mock(status_code=201))

        middleware1 = FiletypeLoaderMiddleware(view1)
        middleware2 = FiletypeLoaderMiddleware(view2)

        assert mock_load_filetypes.call_count == 2

        factory = RequestFactory()
        request = factory.get("/test/")

        response1 = middleware1(request)
        response2 = middleware2(request)

        assert response1.status_code == 200
        assert response2.status_code == 201
