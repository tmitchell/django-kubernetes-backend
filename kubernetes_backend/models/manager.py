import logging

from django.db.models.manager import BaseManager
from kubernetes import client

logger = logging.getLogger(__name__)


class KubernetesQuerySet:
    def __init__(self, model, using=None, hints=None):
        self.model = model
        self._result_cache = None

    def _fetch_all(self):
        api = self.model.get_api_client()
        group = self.model._meta.kubernetes_group
        version = self.model._meta.kubernetes_version
        kind = self.model._meta.kubernetes_kind
        plural = self.model._meta.kubernetes_plural

        try:
            if group in (
                "apps",
                "batch",
                "core",
                "autoscaling",
                "networking",
                "rbac.authorization.k8s.io",
            ):
                method = f"list_{kind.lower()}_for_all_namespaces"
                response = getattr(api, method)()
                items = response.items
            else:
                if self.model._meta.cluster_scoped:
                    response = api.list_cluster_custom_object(group, version, plural)
                    items = response["items"]
                else:
                    # Fetch CRDs across all namespaces
                    core_api = client.CoreV1Api()
                    namespaces = [
                        ns.metadata.name for ns in core_api.list_namespace().items
                    ]
                    items = []
                    for ns in namespaces:
                        try:
                            response = api.list_namespaced_custom_object(
                                group, version, ns, plural
                            )
                            items.extend(response["items"])
                        except client.ApiException as e:
                            if (
                                e.status != 404
                            ):  # Ignore if CRD doesn’t exist in this namespace
                                logger.warning(f"Failed to list {kind} in {ns}: {e}")

        except client.ApiException as e:
            logger.error(f"Failed to list {kind}: {e}")
            return []

        self._result_cache = [self._deserialize_resource(item) for item in items]
        return self

    def _deserialize_resource(self, resource):
        """Deserialize a Kubernetes resource into a Django model instance."""
        if isinstance(resource, dict):
            resource_dict = resource
        elif hasattr(resource, "to_dict") and callable(resource.to_dict):
            resource_dict = resource.to_dict()
        else:
            raise ValueError("resource_data must be a dict or have a to_dict() method")
        logger.debug(f"Resource dict: {resource_dict}")

        metadata = resource_dict["metadata"]
        instance = self.model(
            uid=metadata["uid"],
            name=metadata["name"],
            namespace=metadata.get("namespace", None),
            labels=metadata.get("labels", {}),
            annotations=metadata.get("annotations", {}),
        )

        for field in self.model._meta.fields:
            field_name = field.name
            logger.debug(f"Processing field: {field_name}")
            if field_name not in ("uid", "name", "namespace", "labels", "annotations"):
                value = resource_dict.get(field_name, None)
                logger.debug(f"Setting {field_name} to {value}")
                setattr(instance, field_name, value)

        return instance

    def all(self):
        """
        Return a new queryset representing all resources.
        """
        qs = self._clone()
        if qs._result_cache is None:
            qs._fetch_all()
        return qs

    def _clone(self):
        """
        Create a new queryset instance with the same configuration.
        """
        qs = KubernetesQuerySet(self.model)
        if self._result_cache is not None:
            qs._result_cache = self._result_cache.copy()
        return qs

    def __iter__(self):
        """
        Allow iteration over the queryset (e.g. for pod in Pod.objects.all()).
        """
        if self._result_cache is None:
            self._fetch_all()
        return iter(self._result_cache)

    def __getitem__(self, key):
        """
        Allow indexing and slicing (e.g. Pod.objects.all()[1:5]).
        """
        if self._result_cache is None:
            self._fetch_all()
        if isinstance(key, slice):
            return self._result_cache[key]
        elif isinstance(key, int):
            return self._result_cache[key]
        else:
            raise TypeError("Invalid argument type for __getitem__")

    def __len__(self):
        """
        Allow calling len(queryset).
        """
        if self._result_cache is None:
            self._fetch_all()
        return len(self._result_cache)

    def count(self):
        """
        Return the number of records in the queryset
        """
        if self._result_cache is None:
            self._fetch_all()
        return len(self._result_cache)

    def filter(self, **kwargs):
        """
        Implement filtering logic (e.g. using Kubernetes field selectors or labels).
        """
        # TODO: Implement filtering by fetching and filtering results
        return self._clone()


class KubernetesManager(BaseManager.from_queryset(KubernetesQuerySet)):
    pass
