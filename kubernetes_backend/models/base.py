import logging

from django.db import models
from django.db.models.base import ModelBase

from ..client import get_openapi_schema

logger = logging.getLogger(__name__)


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

        # Fetch and generate fields from schema
        schema = get_resource_schema(
            new_class._meta.kubernetes_resource_type,
            new_class._meta.kubernetes_api_version,
            new_class._meta.kubernetes_kind,
        )
        logger.debug(f"Schema for {new_class._meta.kubernetes_kind}: {schema}")
        if schema:
            generated_fields = generate_fields_from_schema(schema)
            logger.debug(f"Generated fields: {generated_fields}")
            for field_name, field in generated_fields.items():
                if field_name not in attrs:
                    new_class.add_to_class(field_name, field)
        return new_class


def get_resource_schema(resource_type, api_version, kind):
    """
    Fetch the OpenAPI schema for a specific Kubernetes resource.
    """
    openapi_schema = get_openapi_schema()
    if resource_type == "core":
        resource_key = f"io.k8s.api.core.{api_version}.{kind}"
    elif resource_type in ("custom", "rbac"):
        resource_key = f"io.k8s.api.{api_version.replace('/', '.')}.{kind}"
    else:
        raise ValueError(f"Unsupported resource type: {resource_type}")
    schema = openapi_schema.get("definitions", {}).get(resource_key, {})
    logger.debug(f"Fetching schema for {resource_key}: {schema}")
    return schema


def map_schema_to_django_field(schema, field_name):
    """
    Map a Kubernetes OpenAPI schema field to a Django model field.
    """
    if not schema:
        return models.JSONField(default=dict, blank=True, null=True)
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
        return models.JSONField(default=list, blank=True, null=True)
    elif field_type == "object" or "properties" in schema or "$ref" in schema:
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
