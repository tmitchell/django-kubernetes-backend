import logging
from functools import lru_cache

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
        meta = getattr(new_class, "KubernetesMeta", None)
        if meta is None:
            raise ValueError(
                "KubernetesModel subclasses must define a KubernetesMeta class"
            )

        # Check required attributes on meta class
        missing_attrs = [attr for attr in ("kind",) if not hasattr(meta, attr)]
        if missing_attrs:
            raise ValueError(f"KubernetesMeta must define {', '.join(missing_attrs)}")

        # Store Kubernetes resource configuration in _meta with some defaults
        new_meta = new_class._meta
        new_meta.kubernetes_group = getattr(meta, "group", "core")
        new_meta.kubernetes_version = getattr(meta, "version", "v1")
        new_meta.kubernetes_kind = meta.kind
        new_meta.kubernetes_plural = getattr(meta, "plural", f"{meta.kind.lower()}s")
        new_meta.cluster_scoped = getattr(meta, "cluster_scoped", False)

        # Fetch and generate fields from schema
        schema = get_resource_schema(
            new_meta.kubernetes_group,
            new_meta.kubernetes_version,
            new_meta.kubernetes_kind,
        )
        logger.debug(f"Schema for {new_class._meta.kubernetes_kind}: {schema}")
        if schema:
            generated_fields = generate_fields_from_schema(schema)
            logger.debug(f"Generated fields: {generated_fields}")
            for field_name, field in generated_fields.items():
                if field_name not in attrs:
                    new_class.add_to_class(field_name, field)
        return new_class


@lru_cache(maxsize=1)
def get_resource_schema(group, version, kind):
    """
    Fetch the OpenAPI schema for a specific Kubernetes resource.
    """
    openapi_schema = get_openapi_schema()

    # Map group/version/kind to schema key
    if group == "core":
        key = f"io.k8s.api.core.{version}.{kind}"
    else:
        key = (
            f"io.k8s.api.{group}.{version}.{kind}"
            if group.startswith("k8s.io")
            else f"io.{group}.{version}.{kind}"
        )
    schema = openapi_schema.get("definitions", {}).get(key, {})
    if not schema:
        logger.warning(f"No schema found for {key}, using default")
    return schema


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
        return models.JSONField(default=list, blank=True, null=True)
    else:  # object, $ref, or unknown
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
