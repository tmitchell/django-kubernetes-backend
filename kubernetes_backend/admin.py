from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.db.models import Q


class KubernetesChangeList(ChangeList):
    """Custom ChangeList for Kubernetes querysets, avoiding ORM assumptions.

    Overrides minimal methods to integrate KubernetesQuerySet with Admin,
    applying search filters directly in get_queryset to keep logic in the
    queryset class where it's testable and maintainable.
    """

    def get_queryset(self, request):
        """Fetch and filter the queryset based on search terms.

        Applies search filters using KubernetesQuerySet.filter() when a 'q'
        parameter is present, leveraging the queryset’s robust filtering logic.
        Avoids ORM-specific features like .query or select_related.
        """
        qs = self.model_admin.get_queryset(request)
        # Apply search filters
        if self.model_admin.search_fields and request.GET.get("q"):
            search_query = None
            for field in self.model_admin.search_fields:
                q = Q(**{f"{field}__icontains": request.GET["q"]})
                search_query = q if search_query is None else search_query | q
            qs = qs.filter(search_query)
        # Apply ordering
        ordering = self.get_ordering(request, qs)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def get_ordering(self, request, queryset):
        """Determine the ordering fields from request or default to 'name'.

        Parses 'o' parameter from request (e.g., ?o=1 for namespace) to support
        clickable column headers, avoiding ORM’s .query.order_by dependency.
        """
        # Map list_display indices to field names
        order_param = request.GET.get("o")
        if order_param:
            try:
                # Convert 'o' value (e.g., '1' or '-2') to field name
                index = int(order_param.lstrip("-"))
                field = self.list_display[abs(index)]
                return [f"-{field}" if order_param.startswith("-") else field]
            except (ValueError, IndexError):
                pass  # Fallback to default if invalid
        return self.model_admin.ordering or ["name"]


class KubernetesAdmin(admin.ModelAdmin):
    """Base admin class for Kubernetes models, minimizing customization.

    Uses KubernetesChangeList to delegate filtering to the queryset, keeping
    the Admin layer thin and focused on display configuration.
    """

    list_display = ("name", "namespace", "uid")
    # list_filter = ("namespace", )
    search_fields = ("name", "namespace")
    ordering = ["name"]
    readonly_fields = ["uid", "status"]

    def get_changelist(self, request, **kwargs):
        return KubernetesChangeList

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            # Editing an object
            return self.readonly_fields + [
                "namespace",
            ]
        else:
            # Creating a new object
            return self.readonly_fields
