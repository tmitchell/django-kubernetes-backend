import logging
from datetime import datetime

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models.base import ModelBase

from .client import k8s_api
from .manager import KubernetesManager

logger = logging.getLogger(__name__)


K8S_DEFAULT_GROUPS = {
    "",  # core, modern
    "admission.k8s.io",
    "admissionregistration.k8s.io",
    "apiextensions.k8s.io",
    "apiregistration.k8s.io",
    "apps",
    "authentication.k8s.io",
    "authorization.k8s.io",
    "autoscaling",
    "batch",
    "certificates.k8s.io",
    "coordination.k8s.io",
    "core",  # legacy
    "discovery.k8s.io",
    "events.k8s.io",
    "extensions",
    "flowcontrol.apiserver.k8s.io",
    "imagepolicy.k8s.io",
    "internal.apiserver.k8s.io",
    "metrics.k8s.io",
    "networking.k8s.io",
    "node.k8s.io",
    "policy",
    "rbac.authorization.k8s.io",
    "resource.k8s.io",
    "scheduling.k8s.io",
    "storage.k8s.io",
    "storagemigration.k8s.io",
}


class KubernetesModelMeta(ModelBase):
    """Metaclass to initialize _meta attributes early."""

    def __new__(cls, name, bases, attrs):
        # Create the class as usual
        new_class = super().__new__(cls, name, bases, attrs)

        # Skip processing for the base class itself
        if name == "KubernetesModel":
            return new_class

        # Extract KubernetesMeta class configuration
        meta = attrs.get("KubernetesMeta") or getattr(new_class, "KubernetesMeta", None)
        if meta is None:
            raise ValueError(
                "KubernetesModel subclasses must define a KubernetesMeta class"
            )

        # Check required attributes on meta class
        missing_attrs = [attr for attr in ("kind",) if not hasattr(meta, attr)]
        if missing_attrs:
            raise ValueError(f"KubernetesMeta must define {', '.join(missing_attrs)}")

        # Custom _k8s_meta namespace to hold configuration from KubernetesMeta
        _k8s_meta = type("K8sMeta", (), {})()
        _k8s_meta.group = getattr(meta, "group", "core")
        _k8s_meta.version = getattr(meta, "version", "v1")
        _k8s_meta.kind = meta.kind
        _k8s_meta.plural = getattr(meta, "plural", f"{meta.kind.lower()}s")
        _k8s_meta.cluster_scoped = getattr(meta, "cluster_scoped", False)
        _k8s_meta.require_schema = getattr(meta, "require_schema", True)

        # TODO: is there a better spot to put this?
        # copy all the k8s_meta fields to new_class
        for attr_name, value in _k8s_meta.__dict__.items():
            setattr(new_class._meta, f"kubernetes_{attr_name}", value)

        # Fetch and generate fields from schema
        schema = k8s_api.get_resource_schema(
            _k8s_meta.group,
            _k8s_meta.version,
            _k8s_meta.kind,
        )
        logger.debug(f"Schema for {_k8s_meta.kind}: {schema}")
        if schema:
            generated_fields = cls.generate_fields_from_schema(schema)
            logger.debug(f"Generated fields: {generated_fields}")
            for field_name, field in generated_fields.items():
                if field_name not in attrs:
                    new_class.add_to_class(field_name, field)
        elif _k8s_meta.require_schema:
            raise ValueError(f"Schema required but not found for {_k8s_meta.kind}")
        return new_class

    @staticmethod
    def generate_fields_from_schema(schema):
        """
        Generate Django model fields from a Kubernetes OpenAPI schema.
        """
        fields = {}
        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            # Skip metadata fields, as they are already defined in the base model
            if field_name in ("metadata", "apiVersion", "kind"):
                continue
            django_field = KubernetesModelMeta.map_schema_to_django_field(
                field_schema, field_name
            )
            fields[field_name] = django_field
        return fields

    @staticmethod
    def map_schema_to_django_field(schema, field_name):
        """
        Map a Kubernetes OpenAPI schema field to a Django model field.
        """
        field_type = schema.get("type")
        format_type = schema.get("format")
        if field_type == "string":
            if format_type == "date-time":
                return models.DateTimeField(null=True, blank=True)
            return models.CharField(max_length=255, default="", blank=True, null=True)
        elif field_type == "integer":
            return models.IntegerField(default=0, blank=True, null=True)
        elif field_type == "number":
            return models.FloatField(default=0.0, blank=True, null=True)
        elif field_type == "boolean":
            return models.BooleanField(default=False, blank=True, null=True)
        elif field_type == "array":
            return models.JSONField(
                default=list, blank=True, null=True, encoder=DjangoJSONEncoder
            )
        else:  # object, $ref, or unknown
            return models.JSONField(
                default=dict, blank=True, null=True, encoder=DjangoJSONEncoder
            )


class KubernetesModel(models.Model, metaclass=KubernetesModelMeta):
    """
    Base class for Kubernetes-backed Django models.
    """

    class Meta:
        abstract = True
        managed = False

    # Common Kubernetes metadata fields
    uid = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=255)
    namespace = models.CharField(max_length=255, null=True, blank=True)
    labels = models.JSONField(default=dict, null=True, blank=True)
    annotations = models.JSONField(default=dict, null=True, blank=True)

    objects = KubernetesManager()

    @classmethod
    def get_api_client(cls):
        """Return the appropriate Kubernetes API client for this model."""
        return k8s_api.get_api_client(
            cls._meta.kubernetes_group, cls._meta.kubernetes_version
        )

    @classmethod
    def is_custom_resource(cls):
        return cls._meta.kubernetes_group not in K8S_DEFAULT_GROUPS

    def save(self, *args, **kwargs):
        """Save the model instance to Kubernetes."""
        if self._meta.kubernetes_cluster_scoped and self.namespace:
            raise ValueError("Cluster-scoped resources cannot have a namespace.")

        # Determine whether the resource is namespaced, set default if not specified
        namespaced = not self._meta.kubernetes_cluster_scoped
        if namespaced and not self.namespace:
            self.namespace = "default"

        api_client = self.get_api_client()
        kind = self._meta.kubernetes_kind
        plural = self._meta.kubernetes_plural

        kwargs = {"body": self._to_kubernetes_resource()}
        if namespaced:
            kwargs["namespace"] = self.namespace

        # Construct method name based on object type, namespaced status, and whether
        # or not it already exists (has a uid)
        if self.uid is None:
            verb = "create"
        else:
            verb = "replace"
            kwargs["name"] = self.name

        if self.__class__.is_custom_resource():
            method_name = (
                f"{verb}_namespaced_custom_object"
                if namespaced
                else f"{verb}_cluster_custom_object"
            )
            method = getattr(api_client, method_name)
            return method(
                group=self._meta.kubernetes_group,
                version=self._meta.kubernetes_version,
                plural=plural,
                **kwargs,
            )
        else:
            method_name = (
                f"{verb}_namespaced_{kind.lower()}"
                if namespaced
                else f"{verb}_{kind.lower()}"
            )
            method = getattr(api_client, method_name)
            return method(**kwargs)

    def _to_kubernetes_resource(self):
        """Convert the model instance to a Kubernetes resource dictionary."""
        metadata = {
            "name": self.name,
            "labels": self.labels,
            "annotations": self.annotations,
        }
        if not self._meta.kubernetes_cluster_scoped:
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
                    resource_data[field.name] = value

        return resource_data

    def __str__(self):
        if self._meta.kubernetes_cluster_scoped:
            return f"{self.name} (cluster-wide)"
        return f"{self.name} ({self.namespace})"

    @property
    def creation_timestamp(self):
        ts = self.metadata.get("creationTimestamp", None)
        if ts:
            return datetime.fromisoformat(ts)

    @property
    def metadata(self):
        return self._metadata
