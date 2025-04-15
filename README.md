# Django Kubernetes Backend

A Django model backend that overlays Kubernetes (K8s) resources and Custom Resource Definitions (CRDs), providing an ORM-like interface for interacting with Kubernetes resources. This project aims to integrate Django's model patterns with Kubernetes' API, allowing developers to manage Kubernetes resources using familiar Django model syntax.

## Features

- **Kubernetes Integration**:
  - Supports both namespace-scoped and cluster-wide Kubernetes resources.
  - Configurable authentication using kubeconfig (from environment, specific file, or in-cluster service account token).

- **Model Design**:
  - Uses a meta-class (`KubernetesModelBase`) to define models for Kubernetes resources, mimicking Django's model patterns.
  - Adds a `KubernetesMeta` inner class for specifying resource configuration (e.g. `resource_type`, `api_version`, `kind`, `namespace`, `cluster_scoped`).

- **Dynamic Field Generation**:
  - Automatically discovers and generates Django model fields based on the Kubernetes OpenAPI schema.
  - Maps Kubernetes schema types (e.g. `string`, `integer`, `array`) to Django field types (e.g. `CharField`, `IntegerField`, `JSONField`
