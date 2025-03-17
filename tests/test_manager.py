import unittest
from unittest.mock import patch

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.manager import KubernetesManager
from kubernetes_backend.models import KubernetesModel
from kubernetes_backend.queryset import KubernetesQuerySet


class TestKubernetesManager(unittest.TestCase):
    @patch("kubernetes_backend.client.k8s_api.get_openapi_schema")
    def test_model_uses_manager(self, mock_get_openapi_schema):
        mock_get_openapi_schema.return_value = {"definitions": {}}

        # Arrange
        class ManagerModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "custom.example.com"
                version = "v1"
                kind = "CustomResource"
                require_schema = False

        # Act
        qs = ManagerModel.objects.all()

        # Assert
        assert isinstance(qs, KubernetesQuerySet)

    def test_manager_uses_queryset(self):
        # Arrange
        manager = KubernetesManager()

        # Act
        qs = manager.get_queryset()

        # Assert
        self.assertIsInstance(qs, KubernetesQuerySet)


if __name__ == "__main__":
    unittest.main()
