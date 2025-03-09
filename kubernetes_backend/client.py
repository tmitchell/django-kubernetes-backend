import json
import logging
from functools import lru_cache

from django.conf import settings
from kubernetes import client, config

logger = logging.getLogger(__name__)


def get_kubernetes_client():
    """
    Initialize and return a Kubernetes API client based on Django settings.

    The function attempts to load the Kubernetes configuration in the following order:
    1. A specific kubeconfig file specified by `KUBERNETES_CONFIG` in Django settings.
    2. In-cluster configuration using `load_incluster_config()`.
    3. Default kubeconfig from the environment using `load_kube_config()`.

    If no valid configuration is found, an exception will be raised.

    Returns:
        client: The Kubernetes API client initialized with the correct configuration.
    """
    if hasattr(settings, "KUBERNETES_CONFIG"):
        kubeconfig_path = settings.KUBERNETES_CONFIG.get("kubeconfig")
        context = settings.KUBERNETES_CONFIG.get("context", "default")
        if kubeconfig_path:
            logger.warning(f"Loading Kubernetes configuration from {kubeconfig_path}")
        config.load_kube_config(config_file=kubeconfig_path, context=context)
    else:
        try:
            logger.warning("Attempting to load in-cluster Kubernetes configuration...")
            config.load_incluster_config()
        except config.ConfigException as e:
            logger.warning(
                f"In-cluster configuration not available: {e}. "
                "Falling back to default kubeconfig."
            )
            config.load_kube_config()

    logger.debug("Kubernetes client initialized successfully.")
    return client


@lru_cache(maxsize=1)
def get_openapi_schema():
    """
    Fetch and cache the Kubernetes OpenAPI schema.
    """
    k8s_client = get_kubernetes_client()
    api_client = k8s_client.ApiClient()
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
