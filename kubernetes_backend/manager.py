import logging

from django.db.models.manager import BaseManager

from .queryset import KubernetesQuerySet

logger = logging.getLogger(__name__)


class KubernetesManager(BaseManager.from_queryset(KubernetesQuerySet)):
    pass
