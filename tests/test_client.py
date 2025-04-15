import unittest
from unittest.mock import Mock, patch

from django.test import override_settings
from kubernetes.client import api as real_api

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.client import k8s_api


class TestKubernetesAPI(unittest.TestCase):
    def setUp(self):
        # Clear the lru_cache for get_openapi_schema between tests
        k8s_api.get_openapi_schema.cache_clear()
        # Patch kubernetes.config to mock config loading
        self.config_patch = patch("kubernetes_backend.client.config")
        self.mock_config = self.config_patch.start()
        self.mock_config.load_kube_config = Mock(return_value=None)
        self.mock_config.load_incluster_config = Mock(return_value=None)
        self.mock_config.ConfigException = Exception
        # Alias for convenience
        self.mock_k8s_api = k8s_api

    def tearDown(self):
        self.config_patch.stop()

    @override_settings(
        KUBERNETES_CONFIG={
            "kubeconfig": "/path/to/kubeconfig",
            "context": "test-context",
        }
    )
    def test_initialize_client_with_specific_kubeconfig(self):
        # Arrange
        self.mock_config.load_kube_config.reset_mock()
        self.mock_config.load_incluster_config.reset_mock()
        # Act
        k8s_api._initialize_client()
        # Assert
        self.mock_config.load_kube_config.assert_called_once_with(
            config_file="/path/to/kubeconfig", context="test-context"
        )
        self.mock_config.load_incluster_config.assert_not_called()

    def test_initialize_client_in_cluster(self):
        # Arrange
        self.mock_config.load_incluster_config.reset_mock()
        self.mock_config.load_kube_config.reset_mock()
        # Act
        k8s_api._initialize_client()
        # Assert
        self.mock_config.load_incluster_config.assert_called_once()
        self.mock_config.load_kube_config.assert_not_called()

    def test_initialize_client_fallback_to_default(self):
        # Arrange
        self.mock_config.load_incluster_config.side_effect = Exception(
            "In-cluster failed"
        )
        self.mock_config.load_kube_config.reset_mock()
        self.mock_config.load_incluster_config.reset_mock()
        # Act
        k8s_api._initialize_client()
        # Assert
        self.mock_config.load_incluster_config.assert_called_once()
        self.mock_config.load_kube_config.assert_called_once()

    @patch.object(k8s_api, "get_openapi_schema")
    def test_get_openapi_schema_success(self, mock_get_openapi):
        # Arrange
        schema = {"definitions": {"io.k8s.api.core.v1.Pod": {"type": "object"}}}
        mock_get_openapi.return_value = schema
        # Act
        result = k8s_api.get_openapi_schema()
        # Assert
        self.assertEqual(result, schema)

    @patch.object(k8s_api._client, "ApiClient")
    def test_get_openapi_schema_real(self, mock_api_client):
        # Arrange
        mock_response = Mock()
        mock_response.data.decode.return_value = '{"definitions": {"test": {}}}'
        mock_api_client.return_value.call_api.return_value = mock_response
        # Act
        result = k8s_api.get_openapi_schema()
        # Assert
        self.assertEqual(result, {"definitions": {"test": {}}})
        mock_api_client.return_value.call_api.assert_called_once_with(
            "/openapi/v2",
            "GET",
            auth_settings=["BearerToken"],
            _preload_content=False,
            _return_http_data_only=True,
        )

    def test_get_api_client_core_v1(self):
        # Act
        api = k8s_api.get_api_client("core", "v1")
        self.assertIsInstance(api, real_api.CoreV1Api)
        self.assertTrue(hasattr(api, "list_pod_for_all_namespaces"))

        api = k8s_api.get_api_client("", "v1")
        self.assertIsInstance(api, real_api.CoreV1Api)
        self.assertTrue(hasattr(api, "list_pod_for_all_namespaces"))

    def test_get_api_client_rbac_v1(self):
        # Act
        api = k8s_api.get_api_client("rbac.authorization.k8s.io", "v1")
        self.assertIsInstance(api, real_api.RbacAuthorizationV1Api)
        self.assertTrue(hasattr(api, "list_role_for_all_namespaces"))

    def test_get_api_client_custom(self):
        # Act
        api = k8s_api.get_api_client("k3s.cattle.io", "v1")
        self.assertIsInstance(api, real_api.CustomObjectsApi)
        self.assertTrue(hasattr(api, "list_cluster_custom_object"))

    @patch("kubernetes.client.CoreV1Api")
    def test_get_api_client_real_core_v1(self, mock_core_v1):
        mock_api_instance = Mock()
        mock_core_v1.return_value = mock_api_instance
        result = k8s_api.get_api_client("core", "v1")
        self.assertEqual(result, mock_api_instance)
        mock_core_v1.assert_called_once()

    @patch("kubernetes.client.AppsV1Api")
    def test_get_api_client_real_apps_v1(self, mock_apps_v1):
        # Arrange
        mock_api_instance = Mock()
        mock_apps_v1.return_value = mock_api_instance
        # Act
        result = k8s_api.get_api_client("apps", "v1")
        # Assert
        self.assertEqual(result, mock_api_instance)
        mock_apps_v1.assert_called_once()

    def test_get_api_client_real_fallback(self):
        result = k8s_api.get_api_client("nonexistent", "v1")
        self.assertIsInstance(result, k8s_api._client.CustomObjectsApi)

    def test_get_resource_schema_core(self):
        with patch.object(
            k8s_api,
            "get_openapi_schema",
            return_value={
                "definitions": {"io.k8s.api.core.v1.Pod": {"type": "object"}}
            },
        ):
            result = k8s_api.get_resource_schema("core", "v1", "Pod")
            self.assertEqual(result, {"type": "object"})
            result = k8s_api.get_resource_schema("", "v1", "Pod")
            self.assertEqual(result, {"type": "object"})

    def test_get_resource_schema_rbac(self):
        with patch.object(
            k8s_api,
            "get_openapi_schema",
            return_value={
                "definitions": {"io.k8s.api.rbac.v1.Role": {"type": "object"}}
            },
        ):
            result = k8s_api.get_resource_schema(
                "rbac.authorization.k8s.io", "v1", "Role"
            )
            self.assertEqual(result, {"type": "object"})

    def test_get_resource_schema_apps(self):
        with patch.object(
            k8s_api,
            "get_openapi_schema",
            return_value={
                "definitions": {"io.k8s.api.apps.v1.Deployment": {"type": "object"}}
            },
        ):
            result = k8s_api.get_resource_schema("apps", "v1", "Deployment")
            self.assertEqual(result, {"type": "object"})

    def test_get_resource_schema_custom(self):
        with patch.object(
            k8s_api,
            "get_openapi_schema",
            return_value={
                "definitions": {"io.cattle.k3s.v1.Addon": {"type": "object"}}
            },
        ):
            result = k8s_api.get_resource_schema("k3s.cattle.io", "v1", "Addon")
            self.assertEqual(result, {"type": "object"})

    def test_get_resource_schema_missing(self):
        with patch.object(
            k8s_api, "get_openapi_schema", return_value={"definitions": {}}
        ):
            result = k8s_api.get_resource_schema("core", "v1", "Unknown")
            self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
