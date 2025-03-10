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
                resource_type = "core"
                api_version = "v1"
                kind = "Pod"
                namespace = "default"

            spec = models.JSONField(default=dict, blank=True, null=True)

        cls.CorePodModel = CorePodModel

        class CoreNamespaceModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "core"
                api_version = "v1"
                kind = "Namespace"
                cluster_scoped = True

        cls.CoreNamespaceModel = CoreNamespaceModel

        class RbacRoleModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "rbac"
                api_version = "v1"
                kind = "Role"
                namespace = "default"

        cls.RbacRoleModel = RbacRoleModel

        class ManagerCustomModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                resource_type = "custom"
                api_version = "example.com/v1"
                kind = "CustomResource"
                namespace = "default"

        cls.ManagerCustomModel = ManagerCustomModel

    def setUp(self):
        self.qs = KubernetesQuerySet(self.CorePodModel)
        self.qs._result_cache = None

    def test_invalid_resource_type_raises_value_error(self):
        with self.assertRaises(ValueError):

            class InvalidModel(KubernetesModel):
                class Meta:
                    app_label = "kubernetes_backend"

                class KubernetesMeta:
                    resource_type = "invalid"
                    api_version = "v1"
                    kind = "Thing"

    def test_deserialize_resource(self):
        qs = KubernetesQuerySet(self.CorePodModel)
        resource_data = Mock(
            to_dict=lambda: {
                "metadata": {
                    "name": "pod1",
                    "namespace": "default",
                    "labels": {"app": "test"},
                    "annotations": {"key": "value"},
                },
                "spec": {"containers": [{"name": "test"}]},
            }
        )
        instance = qs._deserialize_resource(resource_data)
        self.assertEqual(instance.name, "pod1")
        self.assertEqual(instance.namespace, "default")
        self.assertEqual(instance.labels, {"app": "test"})
        self.assertEqual(instance.annotations, {"key": "value"})
        self.assertEqual(
            instance.spec, {"containers": [{"name": "test"}]}
        )  # Direct access

    def test_iter(self):
        # Arrange
        pod1 = Mock()
        pod1.name = "pod1"
        pod2 = Mock()
        pod2.name = "pod2"
        self.qs._result_cache = [pod1, pod2]

        # Act
        with patch.object(self.qs, "_fetch_all") as mock_fetch:
            result = list(self.qs)

        # Assert
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, "pod1")
        self.assertEqual(result[1].name, "pod2")
        mock_fetch.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_getitem_index(self, mock_fetch_all):
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        pod1 = Mock()
        pod1.name = "pod1"
        pod2 = Mock()
        pod2.name = "pod2"
        qs._result_cache = [pod1, pod2]
        item = qs[1]
        self.assertEqual(item.name, "pod2")
        mock_fetch_all.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_getitem_slice(self, mock_fetch_all):
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        pod1 = Mock()
        pod1.name = "pod1"
        pod2 = Mock()
        pod2.name = "pod2"
        pod3 = Mock()
        pod3.name = "pod3"
        qs._result_cache = [pod1, pod2, pod3]
        items = qs[1:3]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].name, "pod2")
        self.assertEqual(items[1].name, "pod3")
        mock_fetch_all.assert_not_called()

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_getitem_invalid_type(self, mock_fetch_all):
        qs = KubernetesQuerySet(self.CorePodModel)
        with self.assertRaises(TypeError):
            qs["invalid"]

    @patch("kubernetes_backend.models.manager.KubernetesQuerySet._fetch_all")
    def test_len(self, mock_fetch_all):
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        qs._result_cache = [Mock(name="pod1"), Mock(name="pod2")]
        length = len(qs)
        self.assertEqual(length, 2)
        mock_fetch_all.assert_not_called()  # Updated behavior

    def test_filter(self):
        qs = KubernetesQuerySet(self.CorePodModel)
        new_qs = qs.filter(name="test")
        self.assertIsInstance(new_qs, KubernetesQuerySet)
        self.assertEqual(new_qs.model, self.CorePodModel)
        self.assertIsNot(new_qs, qs)

    def test_manager_uses_queryset(self):
        manager = KubernetesManager()
        qs = manager.get_queryset()
        self.assertIsInstance(qs, KubernetesQuerySet)


if __name__ == "__main__":
    unittest.main()
