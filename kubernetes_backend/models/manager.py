import logging

from django.db.models import Q
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

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return self.uid == other.uid

    def __hash__(self):
        return hash(self.uid)

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

    def filter(self, *args, **kwargs):
        qs = self._clone()
        if qs._result_cache is None:
            qs._fetch_all()
        filtered_results = qs._result_cache
        # logger.debug(f"Initial items: {[item.name for item in filtered_results]}")

        if args:
            for q in args:
                if isinstance(q, Q):
                    filtered_results = self._apply_q_filter(filtered_results, q)
                    # logger.debug(f"After applying Q filter: {[item.name for item in filtered_results]}")  # noqa: E501,W505
                else:
                    logger.warning(f"Unsupported filter argument: {q}")

        for key, value in kwargs.items():
            filtered_results = [
                item for item in filtered_results if self._match_field(item, key, value)
            ]

        # logger.debug(f"Filtered results: {[item.name for item in filtered_results]}")
        qs._result_cache = filtered_results
        # logger.debug(f"Set _result_cache: {[item.name for item in qs._result_cache]}")
        return qs

    def _apply_q_filter(self, items, q):
        logger.debug(f"Applying Q filter: {q}, negated={q.negated}")
        if q.negated:
            # logger.debug(f"Processing negated Q with children: {q.children}")
            inner_q = Q(*q.children, _connector=q.connector)
            matches = self._apply_q_filter(items, inner_q)
            # logger.debug(f"Matches for negated Q: {[item.name for item in matches]}")
            match_uids = {item.uid for item in matches}
            # logger.debug(f"Match UIDs: {match_uids}")
            result = [item for item in items if item.uid not in match_uids]
            # logger.debug(f"Negated result: {[item.name for item in result]}")
            return result
        elif q.connector == Q.AND:
            result = items
            for child in q.children:
                if isinstance(child, Q):
                    result = self._apply_q_filter(result, child)
                else:
                    key, value = child
                    result = [
                        item for item in result if self._match_field(item, key, value)
                    ]
            # logger.debug(f"AND result: {[item.name for item in result]}")
            return result
        elif q.connector == Q.OR:
            result = set()
            for child in q.children:
                if isinstance(child, Q):
                    matches = self._apply_q_filter(items, child)
                else:
                    key, value = child
                    matches = [
                        item for item in items if self._match_field(item, key, value)
                    ]
                result.update(matches)
            # logger.debug(f"OR result: {[item.name for item in result]}")
            return list(result)
        else:
            key, value = q.children[0]
            result = [item for item in items if self._match_field(item, key, value)]
            # logger.debug(f"Simple Q result: {[item.name for item in result]}")
            return result

    def _match_field(self, item, field_name, value):
        """
        Check if an item matches a field value.
        Supports most lookup types and nested fields (e.g., labels__key).
        """
        field_parts = field_name.split("__")
        valid_lookups = {"exact", "icontains", "startswith", "gt", "lt"}
        lookup = (
            field_parts[-1]
            if len(field_parts) > 1 and field_parts[-1] in valid_lookups
            else "exact"
        )
        field_path = field_name if lookup == "exact" else "__".join(field_parts[:-1])

        actual_value = self._get_field_value(item, field_path)

        if lookup == "exact":
            if isinstance(actual_value, dict) and isinstance(value, dict):
                return value.items() <= actual_value.items()
            return actual_value == value
        elif lookup == "icontains":
            if actual_value is None:
                return False
            if isinstance(actual_value, dict):
                return any(
                    str(v).lower().find(str(value).lower()) != -1
                    for v in actual_value.values()
                )
            return str(actual_value).lower().find(str(value).lower()) != -1
        elif lookup == "startswith":
            if actual_value is None:
                return False
            return str(actual_value).startswith(str(value))
        elif lookup == "gt":
            if actual_value is None:
                return False
            return actual_value > value
        elif lookup == "lt":
            if actual_value is None:
                return False
            return actual_value < value
        else:
            logger.warning(f"Unsupported lookup: {lookup}")
            return False

    def _get_field_value(self, item, field_name):
        field_parts = field_name.split("__")
        current = item
        for part in field_parts:
            if hasattr(current, part):
                current = getattr(current, part)
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current


class KubernetesManager(BaseManager.from_queryset(KubernetesQuerySet)):
    pass
