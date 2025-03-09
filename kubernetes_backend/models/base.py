from django.db import models
from django.db.models.base import ModelBase

from ..client import get_openapi_schema


class KubernetesModelBase(ModelBase):
    def __new__(cls, name, bases, attrs):
        # Create the class as usual
        new_class = super().__new__(cls, name, bases, attrs)

        # Skip processing for the base class itself
        if name == "KubernetesModel":
            return new_class
        # Extract KubernetesMeta class configuration
        kubernetes_meta = getattr(new_class, "KubernetesMeta", None)
        if not kubernetes_meta or not hasattr(kubernetes_meta, "resource_type"):
            raise ValueError(
                "KubernetesModel subclasses must define a KubernetesMeta class "
                "that includes 'resource_type'."
            )

        # Store Kubernetes resource configuration in _meta
        new_class._meta.kubernetes_resource_type = kubernetes_meta.resource_type
        new_class._meta.kubernetes_api_version = getattr(
            kubernetes_meta, "api_version", "v1"
        )
        new_class._meta.kubernetes_kind = getattr(kubernetes_meta, "kind", None)
        new_class._meta.kubernetes_namespace = getattr(
            kubernetes_meta, "namespace", "default"
        )
        new_class._meta.cluster_scoped = getattr(
            kubernetes_meta, "cluster_scoped", False
        )

        # Validate configuration
        if (
            new_class._meta.cluster_scoped
            and new_class._meta.kubernetes_namespace != "default"
        ):
            raise ValueError(
                "Cluster-scoped resources cannot specify a namespace in KubernetesMeta."
            )

        # Fetch the OpenAPI schema for the resource and generate fields (as before)
        schema = get_resource_schema(
            new_class._meta.kubernetes_api_version, new_class._meta.kubernetes_kind
        )
        if schema:
            generated_fields = generate_fields_from_schema(schema)
            for field_name, field in generated_fields.items():
                if field_name not in attrs:
                    attrs[field_name] = field
                    setattr(new_class, field_name, field)

        return new_class


def get_resource_schema(api_version, kind):
    """
    Fetch the OpenAPI schema for a specific Kubernetes resource.
    """
    openapi_schema = get_openapi_schema()
    # Kubernetes OpenAPI schema uses a definitions section to describe resources
    resource_key = f"io.k8s.api.{api_version.replace('/', '.')}.{kind}"
    return openapi_schema.get("definitions", {}).get(resource_key, {})


def map_schema_to_django_field(schema, field_name):
    """
    Map a Kubernetes OpenAPI schema field to a Django model field.
    """
    if not schema:  # Empty schema
        return models.JSONField(default=dict, blank=True, null=True)

    field_type = schema.get("type")
    format_type = schema.get("format")
    items = schema.get("items")
    properties = schema.get("properties")

    if field_type == "string":
        if format_type == "date-time":
            return models.DateTimeField(default=None, blank=True, null=True)
        return models.CharField(max_length=255, default="", blank=True, null=True)
    elif field_type == "integer":
        return models.IntegerField(default=0, blank=True, null=True)
    elif field_type == "number":
        return models.FloatField(default=0.0, blank=True, null=True)
    elif field_type == "boolean":
        return models.BooleanField(default=False, blank=True, null=True)
    elif field_type == "array":
        from django.contrib.postgres.fields import ArrayField

        if items:
            item_field = map_schema_to_django_field(items, f"{field_name}_item")
            if isinstance(item_field, models.CharField):
                return ArrayField(
                    models.CharField(max_length=255),
                    default=list,
                    blank=True,
                    null=True,
                )
            # For complex array items, fall back to JSONField
            return models.JSONField(default=list, blank=True, null=True)
        return models.JSONField(default=list, blank=True, null=True)
    elif field_type == "object" or properties:
        return models.JSONField(default=dict, blank=True, null=True)
    else:
        # Fallback for unknown or complex types
        return models.JSONField(default=dict, blank=True, null=True)


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
        django_field = map_schema_to_django_field(field_schema, field_name)
        fields[field_name] = django_field

    return fields
