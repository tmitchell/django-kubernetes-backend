# To prevent running all tests via Django, ensure this file is imported
# test files that needs to use Django's ORM or other components.

from django.conf import settings

# Configure minimal Django settings
if not settings.configured:
    import django

    settings.configure(
        KUBERNETES_CONFIG={},
        INSTALLED_APPS=[
            "kubernetes_backend",
        ],
    )
    django.setup()
