import unittest
from unittest.mock import Mock, patch

from django.db import models

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.models.manager import KubernetesManager, KubernetesQuerySet
from kubernetes_backend.models.model import KubernetesModel


class TestKubernetesManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class CorePodModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                require_schema = False

            spec = models.JSONField(default=dict, blank=True, null=True)

        cls.CorePodModel = CorePodModel

        class CoreNamespaceModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Namespace"
                cluster_scoped = True
                require_schema = False

        cls.CoreNamespaceModel = CoreNamespaceModel

        class RbacRoleModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "rbac"
                version = "v1"
                kind = "Role"
                require_schema = False

        cls.RbacRoleModel = RbacRoleModel

        class ManagerCustomModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "custom"
                version = "example.com/v1"
                kind = "CustomResource"
                require_schema = False

        cls.ManagerCustomModel = ManagerCustomModel

    def test_invalid_group_raises_value_error(self):
        # Arrange & Act & Assert
        with self.assertRaises(ValueError):

            class InvalidModel(KubernetesModel):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    group = "invalid"
                    version = "v1"
                    kind = "Thing"

    @patch("kubernetes_backend.models.base.get_resource_schema")
    def test_deserialize_resource(self, mock_get_schema):
        # Mock schema to include spec
        mock_get_schema.return_value = {
            "properties": {"metadata": {"type": "object"}, "spec": {"type": "object"}}
        }

        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        resource_data = Mock(
            to_dict=lambda: {
                "metadata": {
                    "uid": "6ed119d5-65d3-43d6-bc82-cefe4f90516e",
                    "name": "pod1",
                    "labels": {"app": "test"},
                    "annotations": {"key": "value"},
                },
                "spec": {"containers": [{"name": "test"}]},
            }
        )

        # Act
        instance = qs._deserialize_resource(resource_data)
        self.assertEqual(instance.uid, "6ed119d5-65d3-43d6-bc82-cefe4f90516e")
        self.assertEqual(instance.name, "pod1")
        self.assertEqual(instance.labels, {"app": "test"})
        self.assertEqual(instance.annotations, {"key": "value"})
        self.assertEqual(instance.spec, {"containers": [{"name": "test"}]})

    def test_iter(self):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        pod1 = Mock()
        pod1.name = "pod1"
        pod2 = Mock()
        pod2.name = "pod2"
        qs._result_cache = [pod1, pod2]

        # Act
        with patch.object(qs, "_fetch_all") as mock_fetch:
            result = list(qs)

        # Assert
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, "pod1")
        self.assertEqual(result[1].name, "pod2")
        mock_fetch.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_getitem_index(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        pod1 = Mock()
        pod1.name = "pod1"
        pod2 = Mock()
        pod2.name = "pod2"
        qs._result_cache = [pod1, pod2]

        # Act
        item = qs[1]

        # Assert
        self.assertEqual(item.name, "pod2")
        mock_fetch_all.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_getitem_slice(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        pod1 = Mock()
        pod1.name = "pod1"
        pod2 = Mock()
        pod2.name = "pod2"
        pod3 = Mock()
        pod3.name = "pod3"
        qs._result_cache = [pod1, pod2, pod3]

        # Act
        items = qs[1:3]

        # Assert
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].name, "pod2")
        self.assertEqual(items[1].name, "pod3")
        mock_fetch_all.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_getitem_invalid_type(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)

        # Act & Assert
        with self.assertRaises(TypeError):
            qs["invalid"]

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_len(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        qs._result_cache = [Mock(name="pod1"), Mock(name="pod2")]

        # Act
        length = len(qs)

        # Assert
        self.assertEqual(length, 2)
        mock_fetch_all.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_count(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        qs._result_cache = [Mock(name="pod1"), Mock(name="pod2")]

        # Act
        cnt = qs.count()

        # Assert
        self.assertEqual(cnt, 2)
        mock_fetch_all.assert_not_called()

    def test_filter(self):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)

        # Act
        new_qs = qs.filter(name="test")

        # Assert
        self.assertIsInstance(new_qs, KubernetesQuerySet)
        self.assertEqual(new_qs.model, self.CorePodModel)
        self.assertIsNot(new_qs, qs)

    def test_manager_uses_queryset(self):
        # Arrange
        manager = KubernetesManager()

        # Act
        qs = manager.get_queryset()

        # Assert
        self.assertIsInstance(qs, KubernetesQuerySet)


if __name__ == "__main__":
    unittest.main()
