import logging
import re
import uuid

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db.models import Q

logger = logging.getLogger(__name__)


class KubernetesQuerySet:
    """A custom queryset for Kubernetes resources, mimicking Django ORM behavior.

    This class handles filtering, ordering, and iteration over Kubernetes API
    results, allowing seamless integration with Django Admin and application
    code. It avoids direct Kubernetes API calls in favor of in-memory operations
    where possible, with plans to optimize via selectors later.
    """

    def __init__(self, model, using=None, hints=None):
        self.model = model
        self._result_cache = None

    def _fetch_all(self):
        api = self.model.get_api_client()
        group = self.model._meta.kubernetes_group
        version = self.model._meta.kubernetes_version
        kind = self.model._meta.kubernetes_kind
        plural = self.model._meta.kubernetes_plural
        cluster_scoped = self.model._meta.kubernetes_cluster_scoped

        # import pdb; pdb.set_trace()
        if self.model.is_custom_resource():
            if cluster_scoped:
                response = api.list_cluster_custom_object(group, version, plural)
                items = response["items"]
            else:
                response = api.list_custom_object_for_all_namespaces(
                    group, version, plural
                )
                items = response["items"]
        else:
            snake_case = re.sub(r"([a-z])([A-Z])", r"\1_\2", kind).lower()
            if cluster_scoped:
                method = f"list_{snake_case}"
                response = getattr(api, method)()
                items = response.items
            else:
                method = f"list_{snake_case}_for_all_namespaces"
                response = getattr(api, method)()
                items = response.items

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
        qs = self.clone()
        if qs._result_cache is None:
            qs._fetch_all()
        return qs

    def _clone(self):
        """Create a new queryset instance with the same state.

        Core implementation for cloning, preserving the cached result set
        for chaining operations without repeated API calls. Used by Admin’s
        ChangeList and aliased by clone() for public use.
        """
        qs = KubernetesQuerySet(self.model)
        if self._result_cache is not None:
            qs._result_cache = self._result_cache.copy()
        return qs

    def clone(self):
        """Public alias for _clone(), matching Django ORM’s clone() API.

        Provides a familiar interface for queryset chaining and Admin
        compatibility, delegating to _clone() for the actual work.
        """
        return self._clone()

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

    def __eq__(self, other):
        """Compare querysets based on their result sets."""
        if not isinstance(other, KubernetesQuerySet):
            return False
        if self.model != other.model:
            return False
        # Fetch results if not cached
        if self._result_cache is None:
            self._fetch_all()
        if other._result_cache is None:
            other._fetch_all()
        return self._result_cache == other._result_cache

    def count(self):
        """Return the number of items in the queryset.

        Ensures compatibility with Admin pagination by providing a count without
        ORM dependencies. Fetches results if not cached.
        """
        if self._result_cache is None:
            self._fetch_all()
        return len(self._result_cache)

    def exists(self):
        """Return whether or not there are any results in the queryset.

        Fetches results if not cached.
        """
        if self._result_cache is None:
            self._fetch_all()
        return bool(self._result_cache)

    def filter(self, *args, **kwargs):
        """Filter the queryset based on Q objects or keyword arguments.

        Supports Django-style Q objects (e.g., Q(name__icontains='kube')) and
        keyword lookups (e.g., namespace='default'). Filtering happens in-memory
        on cached results, making it testable and extensible outside Admin.
        """
        qs = self.clone()
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
        valid_lookups = {"exact", "icontains", "startswith", "gt", "lt", "in"}
        lookup = (
            field_parts[-1]
            if len(field_parts) > 1 and field_parts[-1] in valid_lookups
            else "exact"
        )
        field_path = field_name if lookup == "exact" else "__".join(field_parts[:-1])

        actual_value = self._get_field_value(item, field_path)
        # Type coercion for UUIDs
        if isinstance(value, uuid.UUID):
            value = str(value)
        if isinstance(actual_value, uuid.UUID):
            actual_value = str(actual_value)

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
        elif lookup == "in":
            if actual_value is None:
                return False
            return actual_value in value
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

    def order_by(self, *field_names):
        """Sort the queryset by one or more field names.

        Supports ascending (e.g., 'name') and descending (e.g., '-namespace') order,
        including nested fields (e.g., 'labels__app'). Sorts in-memory using the
        cached result set, preserving the original order if no fields are provided.
        """
        if not field_names:
            return self

        # Fetch results if not cached
        if self._result_cache is None:
            self._fetch_all()

        # Split field names and directions into a list of (field, reverse) tuples
        fields = []
        for field in field_names:
            if field.startswith("-"):
                fields.append((field[1:], True))  # Descending
            else:
                fields.append((field, False))  # Ascending

        # Sort in-memory, applying each field in sequence from right to left
        sorted_items = self._result_cache[:]
        for field, reverse in reversed(fields):
            sorted_items.sort(
                key=lambda item: self._get_field_value(item, field) or "",
                reverse=reverse,
            )

        # Clone and set sorted results
        qs = self.clone()
        qs._result_cache = sorted_items
        return qs

    def get(self, *args, **kwargs):
        """Retrieve a single object matching the given filters.

        Filters the queryset with args/kwargs and returns exactly one object.
        Raises ObjectDoesNotExist if no matches, MultipleObjectsReturned if more
        than one match. Uses in-memory filtering on cached results.
        """
        # Filter the queryset
        qs = self.filter(*args, **kwargs)
        count = len(qs)

        # Enforce single-result rule
        if count == 0:
            raise ObjectDoesNotExist(
                f"{self.model.__name__} matching query does not exist."
            )
        if count > 1:
            raise MultipleObjectsReturned(
                f"get() returned more than one {self.model.__name__} -- "
                f"it returned {count}!"
            )
        return qs._result_cache[0]
