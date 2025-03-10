import unittest
from unittest.mock import Mock, patch

import django

# Configure Django settings and initialize app registry before imports
from django.conf import settings

if not settings.configured:
    settings.configure(
        DEBUG=True,
        INSTALLED_APPS=["kubernetes_backend"],
    )
    django.setup()

from django.db import models

from kubernetes_backend.models.model import KubernetesModel


class TestKubernetesModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Define test models once to avoid re-registration warnings
        class CoreModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "core"
                api_version = "v1"
                kind = "Pod"
                namespace = "default"

        cls.CoreModel = CoreModel

        class RbacModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "rbac"
                api_version = "v1"
                kind = "Role"

        cls.RbacModel = RbacModel

        class CustomModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "custom"
                api_version = "example.com/v1"
                kind = "CustomResource"
                namespace = "default"

        cls.CustomModel = CustomModel

        class NamespaceModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "core"
                api_version = "v1"
                kind = "Namespace"
                cluster_scoped = True

        cls.NamespaceModel = NamespaceModel

        class BadModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "invalid"
                api_version = "v1"
                kind = "Thing"

        cls.BadModel = BadModel

    def test_model_is_abstract(self):
        # Assert
        self.assertTrue(KubernetesModel._meta.abstract)
        self.assertIsInstance(KubernetesModel._meta.get_field("name"), models.CharField)
        self.assertIsInstance(
            KubernetesModel._meta.get_field("namespace"), models.CharField
        )
        self.assertIsInstance(
            KubernetesModel._meta.get_field("labels"), models.JSONField
        )
        self.assertIsInstance(
            KubernetesModel._meta.get_field("annotations"), models.JSONField
        )
        # Check manager via concrete subclass, abstract models may not bind it directly
        self.assertTrue(hasattr(self.CoreModel, "objects"))

    @patch("kubernetes_backend.models.model.get_kubernetes_client")
    def test_get_api_client_core(self, mock_get_client):
        # Arrange
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        # Act
        api_client = self.CoreModel.get_api_client()

        # Assert
        self.assertEqual(api_client, mock_client.CoreV1Api.return_value)
        mock_client.CoreV1Api.assert_called_once()

    @patch("kubernetes_backend.models.model.get_kubernetes_client")
    def test_get_api_client_rbac(self, mock_get_client):
        # Arrange
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        # Act
        api_client = self.RbacModel.get_api_client()

        # Assert
        self.assertEqual(api_client, mock_client.RbacAuthorizationV1Api.return_value)
        mock_client.RbacAuthorizationV1Api.assert_called_once()

    @patch("kubernetes_backend.models.model.get_kubernetes_client")
    def test_get_api_client_custom(self, mock_get_client):
        # Arrange
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        # Act
        api_client = self.CustomModel.get_api_client()

        # Assert
        self.assertEqual(api_client, mock_client.CustomObjectsApi.return_value)
        mock_client.CustomObjectsApi.assert_called_once()

    @patch("kubernetes_backend.models.model.get_kubernetes_client")
    def test_get_api_client_unsupported_type(self, mock_get_client):
        # Act & Assert
        with self.assertRaises(ValueError):  # Check type, not message
            self.BadModel.get_api_client()

    @patch("kubernetes_backend.models.model.KubernetesModel.get_api_client")
    def test_save_cluster_scoped_with_namespace_raises_error(self, mock_get_client):
        # Arrange
        instance = self.NamespaceModel(name="test", namespace="custom")

        # Act & Assert
        with self.assertRaises(ValueError):  # Check type, not message
            instance.save()

    @patch("kubernetes_backend.models.model.KubernetesModel.get_api_client")
    def test_save_sets_default_namespace(self, mock_get_client):
        # Arrange
        instance = self.CoreModel(name="test-pod")
        mock_api_client = mock_get_client.return_value
        mock_api_client.create_namespaced_pod.return_value = None

        # Act
        instance.save()

        # Assert
        self.assertEqual(instance.namespace, "default")
        mock_api_client.create_namespaced_pod.assert_called_once_with(
            namespace="default", body=instance._to_kubernetes_resource()
        )

    @patch("kubernetes_backend.models.model.KubernetesModel.get_api_client")
    def test_save_core_namespaced(self, mock_get_client):
        # Arrange
        instance = self.CoreModel(name="test-pod", namespace="default")
        mock_api_client = mock_get_client.return_value
        mock_api_client.create_namespaced_pod.return_value = None

        # Act
        instance.save()

        # Assert
        mock_api_client.create_namespaced_pod.assert_called_once_with(
            namespace="default", body=instance._to_kubernetes_resource()
        )

    @patch("kubernetes_backend.models.model.KubernetesModel.get_api_client")
    def test_save_core_cluster_scoped(self, mock_get_client):
        # Arrange
        instance = self.NamespaceModel(name="test-namespace")
        mock_api_client = mock_get_client.return_value
        mock_api_client.create_namespace.return_value = None

        # Act
        instance.save()

        # Assert
        mock_api_client.create_namespace.assert_called_once_with(
            body=instance._to_kubernetes_resource()
        )

    @patch("kubernetes_backend.models.model.KubernetesModel.get_api_client")
    def test_save_custom_namespaced(self, mock_get_client):
        # Arrange
        instance = self.CustomModel(name="test-custom", namespace="default")
        mock_api_client = mock_get_client.return_value
        mock_api_client.create_namespaced_custom_object.return_value = None

        # Act
        instance.save()

        # Assert
        mock_api_client.create_namespaced_custom_object.assert_called_once_with(
            group="example.com",
            version="v1",
            namespace="default",
            plural="customresources",
            body=instance._to_kubernetes_resource(),
        )

    @patch("kubernetes_backend.models.base.KubernetesModelBase.__new__")
    def test_to_kubernetes_resource_namespaced(self, mock_new):
        # Arrange
        mock_new.return_value = self.CoreModel
        instance = self.CoreModel(
            name="test-pod",
            namespace="default",
            labels={"app": "test"},
            annotations={"key": "value"},
        )
        # Mock _meta.fields with explicit string names
        field_names = ["name", "namespace", "labels", "annotations", "id", "spec"]
        instance._meta.fields = [Mock() for _ in field_names]
        for mock_field, name in zip(instance._meta.fields, field_names):
            mock_field.name = name  # Explicitly set name as string
        instance.spec = {"containers": [{"name": "test"}]}

        # Act
        resource = instance._to_kubernetes_resource()

        # Assert
        self.assertEqual(resource["apiVersion"], "v1")
        self.assertEqual(resource["kind"], "Pod")
        self.assertEqual(resource["metadata"]["name"], "test-pod")
        self.assertEqual(resource["metadata"]["namespace"], "default")
        self.assertEqual(resource["metadata"]["labels"], {"app": "test"})
        self.assertEqual(resource["metadata"]["annotations"], {"key": "value"})
        self.assertEqual(resource["spec"], {"containers": [{"name": "test"}]})

    def test_to_kubernetes_resource_cluster_scoped(self):
        # Arrange
        instance = self.NamespaceModel(name="test-namespace")
        # Mock _meta.fields with explicit string names
        field_names = ["name", "namespace", "labels", "annotations", "id"]
        instance._meta.fields = [Mock() for _ in field_names]
        for mock_field, name in zip(instance._meta.fields, field_names):
            mock_field.name = name  # Explicitly set name as string

        # Act
        resource = instance._to_kubernetes_resource()

        # Assert
        self.assertEqual(resource["apiVersion"], "v1")
        self.assertEqual(resource["kind"], "Namespace")
        self.assertEqual(resource["metadata"]["name"], "test-namespace")
        self.assertNotIn("namespace", resource["metadata"])
        self.assertEqual(resource["metadata"]["labels"], {})
        self.assertEqual(resource["metadata"]["annotations"], {})

    def test_str_namespaced(self):
        # Arrange
        instance = self.CoreModel(name="test-pod", namespace="default")

        # Act
        result = str(instance)

        # Assert
        self.assertEqual(result, "test-pod (default)")

    def test_str_cluster_scoped(self):
        # Arrange
        instance = self.NamespaceModel(name="test-namespace")

        # Act
        result = str(instance)

        # Assert
        self.assertEqual(result, "test-namespace (cluster-wide)")


if __name__ == "__main__":
    unittest.main()
