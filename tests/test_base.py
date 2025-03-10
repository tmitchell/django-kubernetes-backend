import unittest
from unittest.mock import patch

from django.db import models

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.models.base import (
    KubernetesModelBase,
    generate_fields_from_schema,
    get_resource_schema,
    map_schema_to_django_field,
)


class TestKubernetesModelBase(unittest.TestCase):
    def test_base_class_skipped(self):
        # Arrange
        class KubernetesModel(metaclass=KubernetesModelBase):
            pass

        # Act
        result = KubernetesModelBase.__new__(
            KubernetesModelBase, "KubernetesModel", (), {}
        )

        # Assert
        self.assertIsInstance(result, type)
        self.assertEqual(result.__name__, "KubernetesModel")

    def test_missing_kubernetes_meta_raises_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class MissingMetaModel(models.Model, metaclass=KubernetesModelBase):
                class Meta:
                    app_label = "kubernetes_backend"

    def test_missing_resource_type_raises_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class NoResourceTypeModel(models.Model, metaclass=KubernetesModelBase):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    api_version = "v1"
                    kind = "Pod"

    def test_valid_kubernetes_meta(self):
        # Arrange
        class TestModel(models.Model, metaclass=KubernetesModelBase):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "core"
                api_version = "v1"
                kind = "Pod"
                namespace = "default"
                cluster_scoped = False

        # Assert
        self.assertEqual(TestModel._meta.kubernetes_resource_type, "core")
        self.assertEqual(TestModel._meta.kubernetes_api_version, "v1")
        self.assertEqual(TestModel._meta.kubernetes_kind, "Pod")
        self.assertEqual(TestModel._meta.kubernetes_namespace, "default")
        self.assertFalse(TestModel._meta.cluster_scoped)

    def test_cluster_scoped_with_namespace_raises_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class ClusterScopedModel(models.Model, metaclass=KubernetesModelBase):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    resource_type = "core"
                    api_version = "v1"
                    kind = "Namespace"
                    namespace = "custom"
                    cluster_scoped = True

    @patch("kubernetes_backend.models.base.get_resource_schema")
    def test_field_generation(self, mock_get_schema):
        # Arrange
        mock_get_schema.return_value = {
            "properties": {
                "spec": {"type": "object"},
                "status": {"type": "object"},
                "metadata": {"type": "object"},  # Should be skipped
            }
        }

        # Act
        class TestModelWithFields(models.Model, metaclass=KubernetesModelBase):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "core"
                api_version = "v1"
                kind = "Pod"

        # Assert
        self.assertTrue(hasattr(TestModelWithFields, "spec"))
        self.assertTrue(hasattr(TestModelWithFields, "status"))
        self.assertIsInstance(TestModelWithFields.spec, models.JSONField)
        self.assertIsInstance(TestModelWithFields.status, models.JSONField)
        self.assertFalse(hasattr(TestModelWithFields, "metadata"))  # Skipped

    def test_get_resource_schema(self):
        # Arrange
        mock_schema = {
            "definitions": {
                "io.k8s.api.v1.Pod": {"properties": {"spec": {"type": "object"}}}
            }
        }
        with patch(
            "kubernetes_backend.models.base.get_openapi_schema",
            return_value=mock_schema,
        ):
            # Act
            result = get_resource_schema("v1", "Pod")

            # Assert
            self.assertEqual(result, {"properties": {"spec": {"type": "object"}}})

    def test_get_resource_schema_missing(self):
        # Arrange
        mock_schema = {"definitions": {}}
        with patch(
            "kubernetes_backend.models.base.get_openapi_schema",
            return_value=mock_schema,
        ):
            # Act
            result = get_resource_schema("v1", "Unknown")

            # Assert
            self.assertEqual(result, {})

    def test_map_schema_to_django_field_string(self):
        # Arrange
        schema = {"type": "string"}

        # Act
        field = map_schema_to_django_field(schema, "test_field")

        # Assert
        self.assertIsInstance(field, models.CharField)
        self.assertEqual(field.max_length, 255)
        self.assertEqual(field.default, "")

    def test_map_schema_to_django_field_datetime(self):
        # Arrange
        schema = {"type": "string", "format": "date-time"}

        # Act
        field = map_schema_to_django_field(schema, "test_field")

        # Assert
        self.assertIsInstance(field, models.DateTimeField)
        self.assertIsNone(field.default)

    def test_map_schema_to_django_field_integer(self):
        # Arrange
        schema = {"type": "integer"}

        # Act
        field = map_schema_to_django_field(schema, "test_field")

        # Assert
        self.assertIsInstance(field, models.IntegerField)
        self.assertEqual(field.default, 0)

    def test_map_schema_to_django_field_array(self):
        schema = {"type": "array", "items": {"type": "string"}}

        # Act
        field = map_schema_to_django_field(schema, "test_field")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default, list)

    def test_map_schema_to_django_field_object(self):
        # Arrange
        schema = {"type": "object"}

        # Act
        field = map_schema_to_django_field(schema, "test_field")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default, dict)

    def test_map_schema_to_django_field_empty(self):
        # Arrange
        schema = {}

        # Act
        field = map_schema_to_django_field(schema, "test_field")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default, dict)

    def test_generate_fields_from_schema(self):
        # Arrange
        schema = {
            "properties": {
                "spec": {"type": "object"},
                "metadata": {"type": "object"},  # Should be skipped
                "count": {"type": "integer"},
            }
        }

        # Act
        fields = generate_fields_from_schema(schema)

        # Assert
        self.assertIn("spec", fields)
        self.assertIn("count", fields)
        self.assertNotIn("metadata", fields)
        self.assertIsInstance(fields["spec"], models.JSONField)
        self.assertIsInstance(fields["count"], models.IntegerField)


if __name__ == "__main__":
    unittest.main()
