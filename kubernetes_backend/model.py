import logging

from django.db import models

from .client import get_kubernetes_client
from .manager import KubernetesManager
from .models.base import KubernetesModelBase

logger = logging.getLogger(__name__)


class KubernetesModel(models.Model, metaclass=KubernetesModelBase):
    """
    Base class for Kubernetes-backed Django models.
    """

    class Meta:
        abstract = True

    # Common Kubernetes metadata fields
    uid = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=255)
    namespace = models.CharField(max_length=255, null=True, blank=True)
    labels = models.JSONField(default=dict)
    annotations = models.JSONField(default=dict)

    objects = KubernetesManager()

    @classmethod
    def get_api_client(cls):
        """Return the appropriate Kubernetes API client for this model."""
        group = cls._meta.kubernetes_group
        version = cls._meta.kubernetes_version
        k8s_client = get_kubernetes_client()

        # Core API special case
        if group == "core":
            return k8s_client.CoreV1Api()

        # Attempt to load the API class dynamically based on group and version
        group = group.rstrip("k8s.io")
        normalized_group = "".join(word.capitalize() for word in group.split("."))
        api_class_name = f"{normalized_group}{version.capitalize()}Api"

        logger.debug(f"Looking for {api_class_name} on K8s client")
        if hasattr(k8s_client, api_class_name):
            logger.debug(f"Using {api_class_name} on K8s client")
            return getattr(k8s_client, api_class_name)()

        # Fallback to CustomObjectsApi for custom resources
        return k8s_client.CustomObjectsApi()

    def save(self, *args, **kwargs):
        """Save the model instance to Kubernetes."""
        if self._meta.cluster_scoped and self.namespace:
            raise ValueError("Cluster-scoped resources cannot have a namespace.")

        # Determine whether the resource is namespaced, set default if not specified
        namespaced = not self._meta.cluster_scoped
        if namespaced and not self.namespace:
            self.namespace = "default"

        api_client = self.get_api_client()
        resource_data = self._to_kubernetes_resource()
        kind = self._meta.kubernetes_kind
        plural = self._meta.kubernetes_plural

        # Normalize method name to match API method naming conventions
        method_name = (
            f"create_namespaced_{kind.lower()}"
            if namespaced
            else f"create_{kind.lower()}"
        )
        if hasattr(api_client, method_name):
            method = getattr(api_client, method_name)
            return (
                method(namespace=self.namespace, body=resource_data)
                if namespaced
                else method(body=resource_data)
            )

        # Fall back to CustomObjects API (CRDs)
        method_name = (
            "create_namespaced_custom_object"
            if namespaced
            else "create_cluster_custom_object"
        )
        if hasattr(api_client, method_name):
            method = getattr(api_client, method_name)
            return method(
                group=self._meta.kubernetes_group,
                version=self._meta.kubernetes_version,
                namespace=self.namespace if namespaced else None,
                plural=plural,
                body=resource_data,
            )

    def _to_kubernetes_resource(self):
        """Convert the model instance to a Kubernetes resource dictionary."""
        metadata = {
            "name": self.name,
            "labels": self.labels,
            "annotations": self.annotations,
        }
        if not self._meta.cluster_scoped:
            metadata["namespace"] = self.namespace

        resource_data = {
            "apiVersion": (
                f"{self._meta.kubernetes_version}"
                if self._meta.kubernetes_group == "core"
                else f"{self._meta.kubernetes_group}/{self._meta.kubernetes_version}"
            ),
            "kind": self._meta.kubernetes_kind,
            "metadata": metadata,
        }

        # Add dynamically generated fields (e.g. spec, status) to the resource data
        for field in self._meta.fields:
            if field.name not in ("name", "namespace", "labels", "annotations", "id"):
                value = getattr(self, field.name, None)
                if value is not None:
                    # Handle nested fields (e.g. spec, status) appropriately
                    if field.name in ("spec", "status"):
                        resource_data[field.name] = value
                    else:
                        resource_data.setdefault("spec", {})[field.name] = value

        return resource_data

    def __str__(self):
        if self._meta.cluster_scoped:
            return f"{self.name} (cluster-wide)"
        return f"{self.name} ({self.namespace})"
