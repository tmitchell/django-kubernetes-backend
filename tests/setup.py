from django.conf import settings

# Configure minimal Django settings
if not settings.configured:
    import django

    settings.configure(
        INSTALLED_APPS=[
            "kubernetes_backend",
        ],
    )
    django.setup()
