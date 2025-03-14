import json
import logging

import cachetools.func
from django.conf import settings
from kubernetes import client, config

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


class KubernetesAPI:
    def __init__(self):
        self._client = None
        self._initialize_client()

    def _initialize_client(self):
        if hasattr(settings, "KUBERNETES_CONFIG"):
            kubeconfig_path = settings.KUBERNETES_CONFIG.get("kubeconfig", None)
            context = settings.KUBERNETES_CONFIG.get("context", "default")
            if kubeconfig_path:
                logger.info(f"Loading Kubernetes configuration from {kubeconfig_path}")
            config.load_kube_config(config_file=kubeconfig_path, context=context)
        else:
            try:
                logger.info("Attempting to load in-cluster Kubernetes configuration...")
                config.load_incluster_config()
            except config.ConfigException as e:
                logger.info(
                    f"In-cluster configuration not available: {e}."
                    "Falling back to default kubeconfig."
                )
                config.load_kube_config()
        self._client = client
        logger.debug("Kubernetes client initialized successfully.")

    @cachetools.func.ttl_cache(maxsize=1, ttl=60)
    def get_openapi_schema(self):
        """
        Fetch and cache the Kubernetes OpenAPI schema.
        """
        api_client = self._client.ApiClient()
        response = api_client.call_api(
            "/openapi/v2",
            "GET",
            auth_settings=["BearerToken"],
            _preload_content=False,  # Return raw response instead of deserializing
            _return_http_data_only=True,  # Return only the response data
        )

        # The response is a raw HTTP response object; read and decode the body
        response_body = response.data.decode("utf-8")

        # Deserialize the JSON response
        return json.loads(response_body)

    def get_api_client(self, group, version):
        # Core API special case
        if group in ("core", "", None):
            return self._client.CoreV1Api()

        # Attempt to load the API class dynamically based on group and version
        group = group.removesuffix("k8s.io")
        normalized_group = "".join(word.capitalize() for word in group.split("."))
        api_class_name = f"{normalized_group}{version.capitalize()}Api"

        logger.debug(f"Looking for {api_class_name} on K8s client")
        has_attr = hasattr(self._client, api_class_name)
        if has_attr:
            logger.debug(f"Using {api_class_name} on K8s client")
            api_class = getattr(self._client, api_class_name)
            return api_class()
        logger.debug("Falling back to CustomObjectsApi")
        return self._client.CustomObjectsApi()

    def get_resource_schema(self, group, version, kind):
        """
        Fetch the OpenAPI schema for a specific Kubernetes resource.
        """
        openapi_schema = self.get_openapi_schema()

        if group in ("core", "", None):
            key = f"io.k8s.api.core.{version}.{kind}"
        else:
            if group in K8S_DEFAULT_GROUPS:
                normalized_group = group.rstrip(".k8s.io")
                # if dotted, just grab the left-most (e.g. rbac.authorization -> rbac)
                prefix = normalized_group.split(".")[0]
                group = f"{prefix}.api.k8s.io"
            # All paths should be normalized and we can reverse the name to find it
            reversed_group = ".".join(group.split(".")[::-1])
            key = f"{reversed_group}.{version}.{kind}"

        schema = openapi_schema.get("definitions", {}).get(key, {})
        if not schema:
            logger.warning(f"No schema found for {key}, using default: {schema}")
        return schema


k8s_api = KubernetesAPI()
