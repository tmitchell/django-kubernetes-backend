import logging
import logging.handlers
import unittest
from unittest.mock import Mock, patch

# Configure Django settings before importing anything that uses settings
from django.conf import settings

if not settings.configured:
    settings.configure(
        KUBERNETES_CONFIG={},  # Default value, will be overridden in tests
        DEBUG=True,
    )

from kubernetes.client.rest import ApiException

from kubernetes_backend.client import get_kubernetes_client, get_openapi_schema


class TestKubernetesClient(unittest.TestCase):
    def setUp(self):
        # Clear the lru_cache for get_openapi_schema between tests
        get_openapi_schema.cache_clear()
        # Set up a logger with MemoryHandler to capture log output
        self.logger = logging.getLogger("kubernetes_backend.client")
        self.log_handler = logging.handlers.MemoryHandler(
            capacity=100, flushLevel=logging.ERROR
        )

        self.logger.addHandler(self.log_handler)
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        # Clean up logger handler after each test
        self.logger.removeHandler(self.log_handler)
        self.log_handler.flush()
        self.log_handler.close()
        # Reset settings to avoid interference between tests
        if hasattr(settings, "KUBERNETES_CONFIG"):
            delattr(settings, "KUBERNETES_CONFIG")

    @patch("kubernetes_backend.client.config")
    def test_get_kubernetes_client_with_specific_kubeconfig(self, mock_config):
        # Arrange: Mock Django settings with a specific kubeconfig
        settings.KUBERNETES_CONFIG = {
            "kubeconfig": "/path/to/kubeconfig",
            "context": "test-context",
        }
        mock_config.load_kube_config.return_value = None

        # Act
        result = get_kubernetes_client()

        # Assert
        mock_config.load_kube_config.assert_called_once_with(
            config_file="/path/to/kubeconfig", context="test-context"
        )
        mock_config.load_incluster_config.assert_not_called()
        self.assertIsNotNone(result)

    @patch("kubernetes_backend.client.config")
    def test_get_kubernetes_client_in_cluster(self, mock_config):
        # Arrange: No specific kubeconfig, in-cluster succeeds
        if hasattr(settings, "KUBERNETES_CONFIG"):
            delattr(settings, "KUBERNETES_CONFIG")
        mock_config.load_incluster_config.return_value = None

        # Act
        result = get_kubernetes_client()

        # Assert
        mock_config.load_incluster_config.assert_called_once()
        mock_config.load_kube_config.assert_not_called()
        self.assertIsNotNone(result)

    @patch("kubernetes_backend.client.config")
    def test_get_kubernetes_client_fallback_to_default(self, mock_config):
        # Arrange: No specific kubeconfig, in-cluster fails, falls back to default
        if hasattr(settings, "KUBERNETES_CONFIG"):
            delattr(settings, "KUBERNETES_CONFIG")

        # Define a mock ConfigException class that inherits from Exception
        class MockConfigException(Exception):
            pass

        mock_config.ConfigException = MockConfigException
        mock_config.load_incluster_config.side_effect = MockConfigException(
            "In-cluster failed"
        )

        mock_config.load_kube_config.return_value = None

        # Act
        result = get_kubernetes_client()

        # Assert
        mock_config.load_incluster_config.assert_called_once()
        mock_config.load_kube_config.assert_called_once()
        self.assertIsNotNone(result)

    @patch("kubernetes_backend.client.get_kubernetes_client")
    def test_get_openapi_schema_success(self, mock_get_client):
        # Arrange: Mock the Kubernetes client and API response
        mock_api_client = Mock()
        mock_response = Mock()
        mock_response.data.decode.return_value = '{"definitions": {"test": {}}}'
        mock_api_client.call_api.return_value = mock_response
        mock_get_client.return_value.ApiClient.return_value = mock_api_client

        # Act
        schema = get_openapi_schema()

        # Assert
        mock_api_client.call_api.assert_called_once_with(
            "/openapi/v2",
            "GET",
            auth_settings=["BearerToken"],
            _preload_content=False,
            _return_http_data_only=True,
        )
        self.assertEqual(schema, {"definitions": {"test": {}}})

    @patch("kubernetes_backend.client.get_kubernetes_client")
    def test_get_openapi_schema_cached(self, mock_get_client):
        # Arrange: Mock the Kubernetes client and API response
        mock_api_client = Mock()
        mock_response = Mock()
        mock_response.data.decode.return_value = '{"definitions": {"test": {}}}'
        mock_api_client.call_api.return_value = mock_response
        mock_get_client.return_value.ApiClient.return_value = mock_api_client

        # Act: Call twice to test caching
        schema1 = get_openapi_schema()
        schema2 = get_openapi_schema()

        # Assert: API call should only happen once due to lru_cache
        mock_api_client.call_api.assert_called_once()
        self.assertEqual(schema1, schema2)

    @patch("kubernetes_backend.client.get_kubernetes_client")
    def test_get_openapi_schema_api_error(self, mock_get_client):
        # Arrange: Mock the Kubernetes client to raise an API exception
        mock_api_client = Mock()
        mock_api_client.call_api.side_effect = ApiException("API error")
        mock_get_client.return_value.ApiClient.return_value = mock_api_client

        # Act & Assert
        with self.assertRaises(ApiException):
            get_openapi_schema()


if __name__ == "__main__":
    unittest.main()
