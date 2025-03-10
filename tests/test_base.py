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

    def test_missing_kind_raises_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class NoResourceTypeModel(models.Model, metaclass=KubernetesModelBase):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    api_version = "v1"
                    group = "core"

    def test_valid_kubernetes_meta(self):
        # Arrange
        class TestModel(models.Model, metaclass=KubernetesModelBase):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                cluster_scoped = False

        # Assert
        self.assertEqual(TestModel._meta.kubernetes_group, "core")
        self.assertEqual(TestModel._meta.kubernetes_version, "v1")
        self.assertEqual(TestModel._meta.kubernetes_kind, "Pod")
        self.assertFalse(TestModel._meta.cluster_scoped)

    @patch("kubernetes_backend.models.base.get_openapi_schema")
    def test_field_generation(self, mock_get_openapi_schema):
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

        # Act
        class TestModelWithFields(models.Model, metaclass=KubernetesModelBase):
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

    @patch("kubernetes_backend.models.base.get_openapi_schema")
    def test_get_resource_schema(self, mock_get_openapi_schema):
        # Arrange
        mock_get_openapi_schema.return_value = {
            "definitions": {"io.k8s.api.core.v1.Pod": {"type": "object"}}
        }

        # Act
        result = get_resource_schema("core", "v1", "Pod")

        # Assert
        self.assertEqual(result, {"type": "object"})

    @patch("kubernetes_backend.models.base.get_openapi_schema")
    def test_get_resource_schema_missing(self, mock_get_openapi_schema):
        # Arrange
        mock_get_openapi_schema.return_value = {"definitions": {}}

        # Act
        result = get_resource_schema("core", "v1", "Unknown")

        # Assert
        self.assertEqual(result, {})

    def test_map_schema_to_django_field_no_schema(self):
        # Arrange & Act
        field = map_schema_to_django_field({}, "test")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default(), {})

    def test_map_schema_to_django_field_string(self):
        # Arrange & Act
        field = map_schema_to_django_field({"type": "string"}, "test")

        # Assert
        self.assertIsInstance(field, models.CharField)
        self.assertEqual(field.default, "")

    def test_map_schema_to_django_field_datetime(self):
        # Arrange & Act
        field = map_schema_to_django_field(
            {"type": "string", "format": "date-time"}, "test"
        )

        # Assert
        self.assertIsInstance(field, models.DateTimeField)
        self.assertTrue(field.null)

    def test_map_schema_to_django_field_integer(self):
        # Arrange & Act
        field = map_schema_to_django_field({"type": "integer"}, "test")

        # Assert
        self.assertIsInstance(field, models.IntegerField)
        self.assertEqual(field.default, 0)

    def test_map_schema_to_django_field_array(self):
        # Arrange & Act
        field = map_schema_to_django_field({"type": "array"}, "test")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default, list)

    def test_map_schema_to_django_field_object(self):
        # Arrange & Act
        field = map_schema_to_django_field({"type": "object"}, "test")

        # Assert
        self.assertIsInstance(field, models.JSONField)
        self.assertEqual(field.default(), {})

    def test_map_schema_to_django_field_ref(self):
        # Arrange & Act
        field = map_schema_to_django_field({"$ref": "#/definitions/something"}, "test")

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
        fields = generate_fields_from_schema(schema)

        # Assert
        self.assertIn("count", fields)
        self.assertIn("spec", fields)
        self.assertNotIn("metadata", fields)
        self.assertNotIn("apiVersion", fields)
        self.assertNotIn("kind", fields)
        self.assertIsInstance(fields["count"], models.IntegerField)
        self.assertIsInstance(fields["spec"], models.JSONField)


if __name__ == "__main__":
    unittest.main()
