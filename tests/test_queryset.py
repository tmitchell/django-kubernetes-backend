import logging
import unittest
import uuid
from unittest.mock import MagicMock, Mock, patch

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db import models
from kubernetes import client

import tests.setup  # noqa: F401; Imported for Django setup side-effect
from kubernetes_backend.models import KubernetesModel
from kubernetes_backend.queryset import KubernetesQuerySet

logging.getLogger("kubernetes_backend").setLevel(logging.ERROR)


class TestKubernetesQuerySet(unittest.TestCase):
    """Basic manager methods for compatibility with Django ORM"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.get_openapi_schema_patch = patch(
            "kubernetes_backend.client.k8s_api.get_openapi_schema"
        )
        cls.mock_get_openapi_schema = cls.get_openapi_schema_patch.start()
        cls.mock_get_openapi_schema.return_value = {"definitions": {}}

        cls.get_api_client_patch = patch(
            "kubernetes_backend.client.k8s_api.get_api_client"
        )
        cls.mock_get_api_client = cls.get_api_client_patch.start()

        cls.get_resource_schema_patch = patch(
            "kubernetes_backend.client.k8s_api.get_resource_schema"
        )
        cls.mock_get_resource_schema = cls.get_resource_schema_patch.start()
        cls.mock_get_resource_schema.return_value = {
            "properties": {
                "spec": {"type": "object"},
            }
        }

        class CorePodModel(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"

            spec = models.JSONField(default=dict, blank=True, null=True)

        cls.CorePodModel = CorePodModel

    @classmethod
    def tearDownClass(cls):
        cls.get_resource_schema_patch.stop()
        cls.get_openapi_schema_patch.stop()
        cls.get_api_client_patch.stop()

        super().tearDownClass()

    @patch("kubernetes_backend.client.k8s_api.get_resource_schema")
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

    @patch("kubernetes_backend.queryset.KubernetesQuerySet._fetch_all")
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

    @patch("kubernetes_backend.queryset.KubernetesQuerySet._fetch_all")
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

    @patch("kubernetes_backend.queryset.KubernetesQuerySet._fetch_all")
    def test_getitem_invalid_type(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)

        # Act & Assert
        with self.assertRaises(TypeError):
            qs["invalid"]

    @patch("kubernetes_backend.queryset.KubernetesQuerySet._fetch_all")
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

    @patch("kubernetes_backend.queryset.KubernetesQuerySet._fetch_all")
    def test_exists(self, mock_fetch_all):
        # Arrange
        qs = KubernetesQuerySet(self.CorePodModel)
        mock_fetch_all.return_value = None
        qs._result_cache = [Mock(name="pod1"), Mock(name="pod2")]

        # Act
        result = qs.exists()

        # Assert
        self.assertTrue(result)
        mock_fetch_all.assert_not_called()

    @patch("kubernetes_backend.queryset.KubernetesQuerySet._fetch_all")
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

    @patch("kubernetes_backend.client.k8s_api.get_resource_schema")
    def test_deserialize_resource_invalid(self, mock_get_schema):
        """Test _deserialize_resource with invalid resource data."""
        mock_get_schema.return_value = {"properties": {"metadata": {"type": "object"}}}
        qs = KubernetesQuerySet(self.CorePodModel)
        resource_data = Mock(to_dict=None)  # No to_dict method

        with self.assertRaises(ValueError) as cm:
            qs._deserialize_resource(resource_data)
        self.assertIn("to_dict()", str(cm.exception))

    @patch("kubernetes_backend.client.k8s_api.get_custom_client")
    def test_fetch_all_custom_resource_error(self, mock_get_custom_client):
        """Test _fetch_all with custom resource and API errors."""
        mock_get_custom_client.list_custom_object_for_all_namespaces.side_effect = (
            client.exceptions.ApiException(status=403)
        )

        class CustomModelFoo(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "custom.example.com"
                version = "v1"
                kind = "Custom"
                require_schema = False

        qs = KubernetesQuerySet(CustomModelFoo)
        qs._fetch_all()
        self.assertEqual(qs._result_cache, [])

    def test_queryset_equality(self):
        """Test queryset equality based on contents."""
        qs1 = KubernetesQuerySet(self.CorePodModel)
        qs2 = KubernetesQuerySet(self.CorePodModel)
        pod1 = self.CorePodModel(uid=uuid.uuid4(), name="pod1")
        pod2 = self.CorePodModel(uid=uuid.uuid4(), name="pod2")
        qs1._result_cache = [pod1, pod2]
        qs2._result_cache = [pod1, pod2]
        qs3 = KubernetesQuerySet(self.CorePodModel)
        qs3._result_cache = [pod2, pod1]  # Different order

        self.assertEqual(qs1, qs2)  # Same contents
        self.assertNotEqual(qs1, qs3)  # Different order


class TestKubernetesQuerySetFetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.get_openapi_schema_patch = patch(
            "kubernetes_backend.client.k8s_api.get_openapi_schema"
        )
        cls.mock_get_openapi_schema = cls.get_openapi_schema_patch.start()
        cls.mock_get_openapi_schema.return_value = {"definitions": {}}

        class FetchNamespace(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                version = "v1"
                kind = "Namespace"
                cluster_scoped = True
                require_schema = False

        cls.Namespace = FetchNamespace

        cls.namespace_items = [
            {
                "metadata": {
                    "name": "ns1",
                    "uid": str(uuid.uuid4()),
                    "labels": {"env": "prod"},
                    "annotations": {"owner": "admin"},
                },
            },
            {
                "metadata": {
                    "name": "ns2",
                    "uid": str(uuid.uuid4()),
                    "labels": {"env": "dev"},
                    "annotations": {"owner": "dev"},
                },
            },
        ]

    @classmethod
    def tearDownClass(cls):
        cls.get_openapi_schema_patch.stop()

        super().tearDownClass()

    def test_fetch_all_cluster_scoped(self):
        """Test fetching all cluster-scoped resources (e.g., Namespaces)."""
        # Arrange
        mock_response = MagicMock()
        mock_response.items = self.namespace_items
        mock_api = Mock(spec=client.CoreV1Api)
        mock_api.list_namespace.return_value = mock_response

        with patch(
            "kubernetes_backend.client.k8s_api.get_api_client", return_value=mock_api
        ):
            # Act
            qs = KubernetesQuerySet(self.Namespace)
            results = qs.all()

            # Assert
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].name, "ns1")
            self.assertEqual(results[0].labels, {"env": "prod"})
            self.assertEqual(results[0].annotations, {"owner": "admin"})
            self.assertEqual(results[1].name, "ns2")
            self.assertEqual(results[1].labels, {"env": "dev"})
            self.assertEqual(results[1].annotations, {"owner": "dev"})
            mock_api.list_namespace.assert_called_once()

    def test_fetch_all_namespace_scoped(self):
        """Test fetching all namespace-scoped resources (e.g., Pods)."""

        class FetchPod(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"
                require_schema = False

        # Arrange
        pod_items = [
            {
                "metadata": {
                    "name": "pod1",
                    "uid": str(uuid.uuid4()),
                    "labels": {"env": "prod"},
                    "annotations": {"owner": "admin"},
                },
            },
            {
                "metadata": {
                    "name": "pod2",
                    "uid": str(uuid.uuid4()),
                    "labels": {"env": "dev"},
                    "annotations": {"owner": "dev"},
                },
            },
        ]
        mock_response = MagicMock()
        mock_response.items = pod_items
        mock_api = Mock(spec=client.CoreV1Api)
        mock_api.list_pod_for_all_namespaces.return_value = mock_response

        with patch(
            "kubernetes_backend.client.k8s_api.get_api_client", return_value=mock_api
        ):
            # Act
            qs = KubernetesQuerySet(FetchPod)
            results = qs.all()

            # Assert
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].name, "pod1")
            self.assertEqual(results[0].labels, {"env": "prod"})
            self.assertEqual(results[0].annotations, {"owner": "admin"})
            self.assertEqual(results[1].name, "pod2")
            self.assertEqual(results[1].labels, {"env": "dev"})
            self.assertEqual(results[1].annotations, {"owner": "dev"})
            mock_api.list_pod_for_all_namespaces.assert_called_once()

    def test_fetch_all_custom_namespace_scoped(self):
        """Test fetching all custom namespace-scoped resources"""

        class FetchHerp(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "example.com"
                version = "v1alpha1"
                kind = "Herp"
                require_schema = False

        # Arrange
        herp_items = [
            {
                "metadata": {
                    "name": "herp1",
                    "uid": str(uuid.uuid4()),
                },
            },
            {
                "metadata": {
                    "name": "herp2",
                    "uid": str(uuid.uuid4()),
                },
            },
        ]

        # CustomObjectsApi returns a dict, unlike the CoreV1Api
        mock_response = MagicMock()
        mock_response.__getitem__.side_effect = lambda key: (
            herp_items if key == "items" else None
        )
        mock_api = Mock(spec=client.CustomObjectsApi)
        mock_api.list_custom_object_for_all_namespaces.return_value = mock_response

        with patch(
            "kubernetes_backend.client.k8s_api.get_custom_client", return_value=mock_api
        ):
            # Act
            qs = KubernetesQuerySet(FetchHerp)
            results = qs.all()

            # Assert
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].name, "herp1")
            self.assertEqual(results[1].name, "herp2")
            mock_api.list_custom_object_for_all_namespaces.assert_called_once()

    def test_fetch_all_custom_cluster_scoped(self):
        """Test fetching all custom cluster-scoped resources"""

        class FetchDerp(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "example.com"
                version = "v1alpha1"
                kind = "Derp"
                cluster_scoped = True
                require_schema = False

        # Arrange
        derp_items = [
            {
                "metadata": {
                    "name": "derp1",
                    "uid": str(uuid.uuid4()),
                },
            },
            {
                "metadata": {
                    "name": "derp2",
                    "uid": str(uuid.uuid4()),
                },
            },
        ]

        # CustomObjectsApi returns a dict, unlike the CoreV1Api
        mock_response = MagicMock()
        mock_response.__getitem__.side_effect = lambda key: (
            derp_items if key == "items" else None
        )
        mock_api = Mock(spec=client.CustomObjectsApi)
        mock_api.list_cluster_custom_object.return_value = mock_response

        with patch(
            "kubernetes_backend.client.k8s_api.get_custom_client", return_value=mock_api
        ):
            # Act
            qs = KubernetesQuerySet(FetchDerp)
            results = qs.all()

            # Assert
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].name, "derp1")
            self.assertEqual(results[1].name, "derp2")
            mock_api.list_cluster_custom_object.assert_called_once()


class TestKubernetesQuerySetFilters(unittest.TestCase):
    """More in-depth queryset tests that rely on data to work with"""

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
        cls.mock_get_resource_schema.return_value = {
            "properties": {
                "spec": {"type": "object"},
            }
        }

        class Pod(KubernetesModel):
            class Meta:
                app_label = "kubernetes_backend"

            class KubernetesMeta:
                group = "core"
                version = "v1"
                kind = "Pod"

            spec = models.JSONField(default=dict, blank=True, null=True)

        cls.Pod = Pod

    @classmethod
    def tearDownClass(cls):
        cls.get_resource_schema_patch.stop()
        cls.get_openapi_schema_patch.stop()

        return super().tearDownClass()

    def setUp(self):
        # Mock the Kubernetes API client to avoid real API calls
        self.mock_api = Mock(spec=client.CoreV1Api)

        # Define the structure of the mock Kubernetes API response
        pod_items = [
            {
                "metadata": {
                    "name": "pod1",
                    "namespace": "default",
                    "uid": uuid.UUID("11111111-1111-1111-1111-111111111111"),
                    "labels": {"app": "myapp", "env": "prod"},
                    "annotations": {"created_by": "admin"},
                },
                "spec": {
                    "value": 10,
                },
            },
            {
                "metadata": {
                    "name": "pod2",
                    "namespace": "kube-system",
                    "uid": uuid.UUID("22222222-2222-2222-2222-222222222222"),
                    "labels": {"app": "system", "env": "prod"},
                    "annotations": {"created_by": "system"},
                },
                "spec": {
                    "value": 20,
                },
            },
            {
                "metadata": {
                    "name": "pod3",
                    "namespace": "default",
                    "uid": uuid.UUID("33333333-3333-3333-3333-333333333333"),
                    "labels": {"app": "myapp", "env": "dev"},
                    "annotations": {"created_by": "admin"},
                },
                "spec": {
                    "value": 15,
                },
            },
        ]

        # Create a mock response object that mimics the Kubernetes API response
        mock_response = MagicMock()
        mock_response.items = pod_items  # Set items directly as a list of dicts

        # Configure the mock API to return the mock response
        self.mock_api.list_pod_for_all_namespaces.return_value = mock_response

        # Patch the get_api_client method to return our mock API
        from kubernetes_backend.client import k8s_api

        self.patcher = patch.object(
            k8s_api, "get_api_client", return_value=self.mock_api
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

    def test_filter_by_name_icontains(self):
        """Test filtering by name with icontains."""
        from django.db.models import Q

        queryset = self.Pod.objects.filter(Q(name__icontains="pod"))
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

    def test_filter_pk(self):
        """Test filtering using pk= shorthand"""
        queryset = self.Pod.objects.filter(
            pk=uuid.UUID("11111111-1111-1111-1111-111111111111")
        )
        self.assertEqual(len(queryset), 1)
        self.assertEqual(str(queryset[0].pk), "11111111-1111-1111-1111-111111111111")
        self.assertEqual(queryset[0].name, "pod1")

    def test_filter_by_value_lt(self):
        """Test filtering by less than value."""
        queryset = self.Pod.objects.filter(spec__value__lt=15)
        self.assertEqual(len(queryset), 1)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1"})

    def test_filter_by_value_gt(self):
        """Test filtering by greater than value."""
        queryset = self.Pod.objects.filter(spec__value__gt=12)
        self.assertEqual(len(queryset), 2)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod2", "pod3"})

    def test_filter_by_in_lookup(self):
        """Test filtering with the __in lookup, including None values."""
        # Test basic __in with labels__app
        queryset = self.Pod.objects.filter(labels__app__in=["myapp", "system"])
        self.assertEqual(len(queryset), 3)  # pod1, pod2, pod3 all match
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod2", "pod3"})

        # Add a pod with spec.value = None and test __in
        qs = self.Pod.objects.all()
        list(qs)  # Trigger _fetch_all
        pod_none = self.Pod(uid=uuid.uuid4(), name="pod_none", spec={})
        qs._result_cache.append(pod_none)

        # Test spec__value__in with None present
        queryset = qs.filter(spec__value__in=[10, 15, 20])
        self.assertEqual(len(queryset), 3)  # pod1, pod2, pod3 (None excluded)
        names = {pod.name for pod in queryset}
        self.assertEqual(names, {"pod1", "pod2", "pod3"})

    def test_filter_by_nested_q(self):
        """Test filtering with nested Q objects."""
        from django.db.models import Q

        queryset = self.Pod.objects.filter(
            Q(Q(name="pod1") | Q(namespace="kube-system")) & Q(labels__app="myapp")
        )
        self.assertEqual(len(queryset), 1)
        self.assertEqual(queryset[0].name, "pod1")

    def test_filter_by_raw_simple_q(self):
        """Test filtering with a raw Q object having no connector."""
        from django.db.models import Q

        # Manually construct a Q with connector=None
        q = Q()
        q.connector = None  # Force no connector
        q.children = [("name", "pod1")]
        logging.getLogger("kubernetes_backend").setLevel(logging.DEBUG)
        queryset = self.Pod.objects.filter(q)
        self.assertEqual(len(queryset), 1)
        self.assertEqual(queryset[0].name, "pod1")

    def test_match_field_edge_cases(self):
        """Test _match_field with None values and unsupported lookups."""
        qs = self.Pod.objects.all()
        list(qs)  # force fetch
        # Add a pod with spec.value = None
        pod_none = self.Pod(uid=uuid.uuid4(), name="pod_none", spec={})
        qs._result_cache.append(pod_none)

        # Test None with gt/lt
        filtered = qs.filter(spec__value__gt=5)
        self.assertEqual(len(filtered), 3)  # pod2, pod3 (None excluded)
        filtered = qs.filter(spec__value__lt=15)
        self.assertEqual(len(filtered), 1)  # pod1 (None excluded)

        # Test unsupported lookup
        filtered = qs.filter(spec__value__invalid="foo")
        self.assertEqual(len(filtered), 0)  # Should log warning and return False

    def test_order_by(self):
        """Test ordering by field names, including descending and nested fields."""
        qs = self.Pod.objects.order_by()  # No-op case
        self.assertEqual(len(qs), 3)  # Just checks it doesn’t crash

        qs = self.Pod.objects.order_by("spec__value", "-name")
        # 10 (pod1), 15 (pod3), 20 (pod2)
        self.assertEqual([pod.name for pod in qs], ["pod1", "pod3", "pod2"])
        qs = self.Pod.objects.order_by("namespace")
        # default, default, kube-system
        self.assertEqual([pod.name for pod in qs], ["pod1", "pod3", "pod2"])

        qs = self.Pod.objects.order_by("-namespace")
        # kube-system, default, default
        self.assertEqual([pod.name for pod in qs], ["pod2", "pod1", "pod3"])

        qs = self.Pod.objects.order_by("labels__app", "name")
        # myapp (pod1), myapp (pod3), system (pod2)
        self.assertEqual([pod.name for pod in qs], ["pod1", "pod3", "pod2"])

        # Test with search filter
        qs = self.Pod.objects.filter(namespace__icontains="default").order_by("-name")
        # pod3, pod1 (default only)
        self.assertEqual([pod.name for pod in qs], ["pod3", "pod1"])

    def test_get(self):
        """Test get() retrieves a single object or raises appropriate exceptions."""
        # Single match by name
        pod = self.Pod.objects.get(name="pod2")
        self.assertEqual(pod.name, "pod2")
        self.assertEqual(pod.namespace, "kube-system")

        # Single match by uid
        pod = self.Pod.objects.get(uid="22222222-2222-2222-2222-222222222222")
        self.assertEqual(pod.uid, uuid.UUID("22222222-2222-2222-2222-222222222222"))
        self.assertEqual(pod.name, "pod2")

        # No match
        with self.assertRaises(ObjectDoesNotExist):
            self.Pod.objects.get(name="nonexistent")

        # Multiple matches
        with self.assertRaises(MultipleObjectsReturned):
            self.Pod.objects.get(namespace="default")  # pod1 and pod3 match


if __name__ == "__main__":
    unittest.main()
