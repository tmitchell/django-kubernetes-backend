import unittest

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.manager import KubernetesManager
from kubernetes_backend.models import KubernetesModel
from kubernetes_backend.queryset import KubernetesQuerySet


class KubernetesManagerTest(unittest.TestCase):
    def test_model_uses_manager(self):
        # Arrange
        class ManagerModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "custom"
                version = "example.com/v1"
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
