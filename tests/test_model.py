import json
import logging
import unittest
import uuid
from datetime import datetime
from unittest.mock import Mock, patch

from django.core.serializers import serialize
from django.db import models

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.models import KubernetesModel, KubernetesModelMeta

logging.getLogger("kubernetes_backend.client").setLevel(logging.ERROR)


class TestKubernetesMetaModel(unittest.TestCase):

    def test_base_class_skipped(self):
        result = KubernetesModelMeta.__new__(
            KubernetesModelMeta, "KubernetesModel", (), {}
        )
        self.assertIsInstance(result, type)
        self.assertEqual(result.__name__, "KubernetesModel")

    def test_missing_kubernetes_meta_raises_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class MissingMetaModel(models.Model, metaclass=KubernetesModelMeta):
                class Meta:
                    app_label = "kubernetes_backend"

    def test_missing_kind_raises_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class NoResourceTypeModel(models.Model, metaclass=KubernetesModelMeta):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    version = "v1"
                    group = "core"

    @patch("kubernetes_backend.client.k8s_api.get_openapi_schema")
    def test_valid_kubernetes_meta(self, mock_get_openapi_schema):
        # Arrange
        mock_get_openapi_schema.return_value = {
            "definitions": {
                "io.k8s.api.core.v1.Pod": {
                    "properties": {
                        "spec": {"type": "object"},
                    }
                }
            }
        }

        class ValidModel(models.Model, metaclass=KubernetesModelMeta):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                cluster_scoped = False
                require_schema = False

        # Assert
        self.assertEqual(ValidModel._meta.kubernetes_group, "core")
        self.assertEqual(ValidModel._meta.kubernetes_version, "v1")
        self.assertEqual(ValidModel._meta.kubernetes_kind, "Pod")
        self.assertFalse(ValidModel._meta.kubernetes_cluster_scoped)

    @patch("kubernetes_backend.client.k8s_api.get_resource_schema")
    @patch("kubernetes_backend.client.k8s_api.get_openapi_schema")
    def test_valid_kubernetes_meta_with_schema(
        self, mock_get_openapi_schema, mock_get_resource_schema
    ):
        mock_get_openapi_schema.return_value = {
            "definitions": {
                "io.k8s.api.core.v1.Pod": {
                    "properties": {
                        "spec": {"type": "object"},
                    }
                }
            }
        }
        mock_get_resource_schema.return_value = {
            "properties": {"spec": {"type": "object"}}
        }

        class ValidModelSchema(models.Model, metaclass=KubernetesModelMeta):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                cluster_scoped = False
                require_schema = True

        # Assert
        self.assertEqual(ValidModelSchema._meta.kubernetes_group, "core")
        self.assertEqual(ValidModelSchema._meta.kubernetes_version, "v1")
        self.assertEqual(ValidModelSchema._meta.kubernetes_kind, "Pod")
        self.assertFalse(ValidModelSchema._meta.kubernetes_cluster_scoped)

    @patch("kubernetes_backend.client.k8s_api.get_resource_schema")
    @patch("kubernetes_backend.client.k8s_api.get_openapi_schema")
    def test_field_generation(self, mock_get_openapi_schema, mock_get_resource_schema):
        # Arrange
        mock_get_openapi_schema.return_value = {
            "definitions": {
                "io.k8s.api.core.v1.Test": {
                    "properties": {
                        "spec": {"type": "object"},
                        "metadata": {"type": "object"},
                        "count": {"type": "integer"},
                    }
                }
            }
        }
        mock_get_resource_schema.return_value = {
            "properties": {
                "spec": {"type": "object"},
                "metadata": {"type": "object"},
                "count": {"type": "integer"},
            }
        }

        # Act
        class TestModelWithFields(models.Model, metaclass=KubernetesModelMeta):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Test"

        spec_field = next(
            f for f in TestModelWithFields._meta.fields if f.name == "spec"
        )
        count_field = next(
            f for f in TestModelWithFields._meta.fields if f.name == "count"
        )

        # Assert
        self.assertIsInstance(spec_field, models.JSONField)
        self.assertIsInstance(count_field, models.IntegerField)

    def test_map_schema_to_django_field_no_schema(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field({}, "test")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default(), {})

    def test_map_schema_to_django_field_string(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field(
            {"type": "string"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.CharField)
        self.assertEqual(field.default, "")

    def test_map_schema_to_django_field_datetime(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field(
            {"type": "string", "format": "date-time"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.DateTimeField)
        self.assertTrue(field.null)

    def test_map_schema_to_django_field_integer(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field(
            {"type": "integer"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.IntegerField)
        self.assertEqual(field.default, 0)

    def test_map_schema_to_django_field_array(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field(
            {"type": "array"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default, list)

    def test_map_schema_to_django_field_object(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field(
            {"type": "object"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default(), {})

    def test_map_schema_to_django_field_ref(self):
        # Arrange & Act
        field = KubernetesModelMeta.map_schema_to_django_field(
            {"$ref": "#/definitions/something"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default(), {})

    def test_generate_fields_from_schema(self):
        # Arrange
        schema = {
            "properties": {
                "metadata": {"type": "object"},
                "apiVersion": {"type": "string"},
                "kind": {"type": "string"},
                "count": {"type": "integer"},
                "spec": {"type": "object"},
            }
        }

        # Act
        fields = KubernetesModelMeta.generate_fields_from_schema(schema)

        # Assert
        self.assertIn("count", fields)
        self.assertIn("spec", fields)
        self.assertNotIn("metadata", fields)
        self.assertNotIn("apiVersion", fields)
        self.assertNotIn("kind", fields)
        self.assertIsInstance(fields["count"], models.IntegerField)
        self.assertIsInstance(fields["spec"], models.JSONField)

    @patch("kubernetes_backend.client.k8s_api.get_openapi_schema")
    def test_invalid_group_raises_value_error(self, mock_get_openapi_schema):
        mock_get_openapi_schema.return_value = {"definitions": {}}

        with self.assertRaises(ValueError):

            class BadGroupModel(KubernetesModel):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    group = "invalid"
                    version = "v1"
                    kind = "Thing"

    @patch("kubernetes_backend.client.k8s_api.get_openapi_schema")
    def test_missing_kind_raises_value_error(self, mock_get_openapi_schema):
        mock_get_openapi_schema.return_value = {"definitions": {}}
        with self.assertRaises(ValueError):

            class NoKindModel(KubernetesModel):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    group = "core"
                    version = "v1"


class TestKubernetesModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.get_openapi_schema_patch = patch(
            "kubernetes_backend.client.k8s_api.get_openapi_schema"
        )
        cls.mock_get_openapi_schema = cls.get_openapi_schema_patch.start()
        cls.mock_get_openapi_schema.return_value = {"definitions": {}}
        cls.get_resource_schema_patch = patch(
            "kubernetes_backend.client.k8s_api.get_resource_schema"
        )
        cls.mock_get_resource_schema = cls.get_resource_schema_patch.start()
        cls.mock_get_resource_schema.return_value = {}

        # Define test models once to avoid re-registration warnings
        class CoreModel(KubernetesModel):

            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                require_schema = False

        cls.CoreModel = CoreModel

        class RbacModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "rbac.authorization.k8s.io"
                version = "v1"
                kind = "Role"
                require_schema = False

        cls.RbacModel = RbacModel

        class CustomModel(KubernetesModel):
            etc = models.JSONField()

            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "custom.example.com"
                version = "v1alpha1"
                kind = "Example"
                require_schema = False

        cls.CustomModel = CustomModel

        class NamespaceModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Namespace"
                cluster_scoped = True
                require_schema = False

        cls.NamespaceModel = NamespaceModel

    @classmethod
    def tearDownClass(cls):
        cls.get_resource_schema_patch.stop()
        cls.get_openapi_schema_patch.stop()

        super().tearDownClass()

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

    @patch("kubernetes_backend.client.k8s_api.get_api_client")
    def test_save_cluster_scoped_with_namespace_raises_error(self, mock_get_client):
        # Arrange
        instance = self.NamespaceModel(name="test", namespace="custom")

        # Act & Assert
        with self.assertRaises(ValueError):
            instance.save()

    @patch("kubernetes_backend.client.k8s_api.get_api_client")
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

    @patch("kubernetes_backend.client.k8s_api.get_api_client")
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

    @patch("kubernetes_backend.client.k8s_api.get_api_client")
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

    @patch("kubernetes_backend.client.k8s_api.get_api_client")
    def test_save_custom_namespaced(self, mock_get_client):
        # Arrange
        instance = self.CustomModel(name="test-custom", namespace="default")
        mock_api_client = mock_get_client.return_value
        mock_api_client.create_namespaced_custom_object.return_value = None
        del mock_api_client.create_namespaced_example

        # Act
        instance.save()

        # Assert
        mock_api_client.create_namespaced_custom_object.assert_called_once_with(
            group="custom.example.com",
            version="v1alpha1",
            namespace="default",
            plural="examples",
            body=instance._to_kubernetes_resource(),
        )

    @patch("kubernetes_backend.client.k8s_api.get_resource_schema")
    def test_to_kubernetes_resource_namespaced(self, mock_get_resource_schema):
        # Arrange
        mock_get_resource_schema.return_value = {
            "properties": {"spec": {"type": "object"}}
        }
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

    @patch("kubernetes_backend.client.k8s_api.get_resource_schema")
    def test_json_serialization(self, mock_get_resource_schema):
        """Test JSON serialization handles datetime and UUID types."""
        # Arrange
        mock_get_resource_schema.return_value = {
            "properties": {"etc": {"type": "object"}}
        }
        instance = self.CustomModel(
            name="test-resource",
            uid=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            etc={
                "creationTimestamp": datetime(2020, 1, 2, 3, 4, 5),
            },
        )

        # Act
        serialized = serialize("json", [instance])
        new_instance = json.loads(serialized)[0]

        # Assert
        self.assertEqual(new_instance["pk"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(
            new_instance["fields"]["etc"]["creationTimestamp"], "2020-01-02T03:04:05"
        )


if __name__ == "__main__":
    unittest.main()
