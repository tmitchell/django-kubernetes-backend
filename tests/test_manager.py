import logging
import unittest
from unittest.mock import MagicMock, Mock, patch

from django.db import models
from kubernetes import client

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.models.manager import KubernetesManager, KubernetesQuerySet
from kubernetes_backend.models.model import KubernetesModel

logging.getLogger("kubernetes_backend").setLevel(logging.ERROR)


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


class TestFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class Pod(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                require_schema = False

            spec = models.JSONField(default=dict, blank=True, null=True)

        cls.Pod = Pod

    def setUp(self):
        # Mock the Kubernetes API client to avoid real API calls
        self.mock_api = Mock(spec=client.CoreV1Api)

        # Define the structure of the mock Kubernetes API response
        pod_items = [
            {
                "metadata": {
                    "name": "pod1",
                    "namespace": "default",
                    "uid": "uid1",
                    "labels": {"app": "myapp", "env": "prod"},
                    "annotations": {"created_by": "admin"},
                }
            },
            {
                "metadata": {
                    "name": "pod2",
                    "namespace": "kube-system",
                    "uid": "uid2",
                    "labels": {"app": "system", "env": "prod"},
                    "annotations": {"created_by": "system"},
                }
            },
            {
                "metadata": {
                    "name": "pod3",
                    "namespace": "default",
                    "uid": "uid3",
                    "labels": {"app": "myapp", "env": "dev"},
                    "annotations": {"created_by": "admin"},
                }
            },
        ]

        # Create a mock response object that mimics the Kubernetes API response
        mock_response = MagicMock()
        mock_response.items = pod_items  # Set items directly as a list of dicts

        # Configure the mock API to return the mock response
        self.mock_api.list_pod_for_all_namespaces.return_value = mock_response

        # Patch the get_api_client method to return our mock API
        self.patcher = patch.object(
            self.Pod, "get_api_client", return_value=self.mock_api
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_filter_by_name(self):
        """Test filtering by exact name."""
        queryset = self.Pod.objects.filter(name="pod1")
        self.assertEqual(len(queryset), 1)
        self.assertEqual(queryset[0].name, "pod1")

    def test_filter_by_name_starts_with(self):
        """Test filtering by name with startswith."""
        queryset = self.Pod.objects.filter(name__startswith="pod")
        self.assertEqual(len(queryset), 3)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod2", "pod3"})

    def test_filter_by_namespace(self):
        """Test filtering by namespace."""
        queryset = self.Pod.objects.filter(namespace="kube-system")
        self.assertEqual(len(queryset), 1)
        self.assertEqual(queryset[0].namespace, "kube-system")

    def test_filter_by_namespace_icontains(self):
        """Test filtering by namespace."""
        queryset = self.Pod.objects.filter(namespace__icontains="KUBE")
        self.assertEqual(len(queryset), 1)
        self.assertEqual(queryset[0].namespace, "kube-system")

    def test_filter_by_labels(self):
        """Test filtering by exact labels (subset match)."""
        queryset = self.Pod.objects.filter(labels={"app": "myapp"})
        self.assertEqual(len(queryset), 2)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod3"})

    def test_filter_by_nested_labels(self):
        """Test filtering by nested label field."""
        queryset = self.Pod.objects.filter(labels__app="myapp")
        self.assertEqual(len(queryset), 2)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod3"})

    def test_filter_with_q_objects_or(self):
        """Test filtering with Q objects using OR."""
        from django.db.models import Q

        queryset = self.Pod.objects.filter(Q(name="pod1") | Q(namespace="kube-system"))
        self.assertEqual(len(queryset), 2)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod2"})

    def test_filter_with_q_objects_and(self):
        """Test filtering with Q objects using AND."""
        from django.db.models import Q

        queryset = self.Pod.objects.filter(
            Q(namespace="default") & Q(labels__app="myapp")
        )
        self.assertEqual(len(queryset), 2)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod3"})

    def test_filter_with_q_objects_not(self):
        """Test filtering with negated Q objects."""
        from django.db.models import Q

        queryset = self.Pod.objects.filter(~Q(namespace="kube-system"))
        self.assertEqual(len(queryset), 2)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod3"})

    def test_filter_empty(self):
        """Test filtering with no matches."""
        queryset = self.Pod.objects.filter(name="nonexistent")
        self.assertEqual(len(queryset), 0)


if __name__ == "__main__":
    unittest.main()
