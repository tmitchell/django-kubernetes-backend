from django.db import models

from ..client import get_kubernetes_client
from .base import KubernetesModelBase
from .manager import KubernetesManager


class KubernetesModel(models.Model, metaclass=KubernetesModelBase):
    """
    Base class for Kubernetes-backed Django models.
    """

    class Meta:
        abstract = True

    # Common Kubernetes metadata fields
    name = models.CharField(max_length=255, primary_key=True)
    namespace = models.CharField(max_length=255, null=True, blank=True)
    labels = models.JSONField(default=dict)
    annotations = models.JSONField(default=dict)

    objects = KubernetesManager()

    @classmethod
    def get_api_client(cls):
        """Return the appropriate Kubernetes API client for this model."""
        k8s_client = get_kubernetes_client()
        if cls._meta.kubernetes_resource_type == "core":
            return k8s_client.CoreV1Api()
        elif cls._meta.kubernetes_resource_type == "rbac":
            return k8s_client.RbacAuthorizationV1Api()
        elif cls._meta.kubernetes_resource_type == "custom":
            return k8s_client.CustomObjectsApi()
        else:
            raise ValueError(
                f"Unsupported resource type: {cls._meta.kubernetes_resource_type}"
            )

    def save(self, *args, **kwargs):
        """Save the model instance to Kubernetes."""
        if self._meta.cluster_scoped and self.namespace:
            raise ValueError("Cluster-scoped resources cannot have a namespace.")
        if not self._meta.cluster_scoped and not self.namespace:
            self.namespace = self._meta.kubernetes_namespace

        api_client = self.get_api_client()
        resource_data = self._to_kubernetes_resource()

        if self._meta.kubernetes_resource_type == "core":
            if self._meta.cluster_scoped:
                # Example for a cluster-wide core resource (e.g. Namespace)
                if self._meta.kubernetes_kind == "Namespace":
                    api_client.create_namespace(body=resource_data)
            else:
                # Namespace-scoped core resource (e.g. Pod)
                api_client.create_namespaced_pod(
                    namespace=self.namespace, body=resource_data
                )
        elif self._meta.kubernetes_resource_type == "rbac":
            if self._meta.cluster_scoped:
                # Cluster-wide RBAC resource (e.g. ClusterRole)
                if self._meta.kubernetes_kind == "ClusterRole":
                    api_client.create_cluster_role(body=resource_data)
                elif self._meta.kubernetes_kind == "ClusterRoleBinding":
                    api_client.create_cluster_role_binding(body=resource_data)
            else:
                # Namespace-scoped RBAC resource (e.g. Role)
                if self._meta.kubernetes_kind == "Role":
                    api_client.create_namespaced_role(
                        namespace=self.namespace, body=resource_data
                    )
                elif self._meta.kubernetes_kind == "RoleBinding":
                    api_client.create_namespaced_role_binding(
                        namespace=self.namespace, body=resource_data
                    )
        elif self._meta.kubernetes_resource_type == "custom":
            if self._meta.cluster_scoped:
                # Cluster-wide custom resource
                group, version = self._meta.kubernetes_api_version.split("/")
                api_client.create_cluster_custom_object(
                    group=group,
                    version=version,
                    plural=f"{self._meta.kubernetes_kind.lower()}s",
                    body=resource_data,
                )
            else:
                # Namespace-scoped custom resource
                group, version = self._meta.kubernetes_api_version.split("/")
                api_client.create_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=self.namespace,
                    plural=f"{self._meta.kubernetes_kind.lower()}s",
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
            "apiVersion": self._meta.kubernetes_api_version,
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
