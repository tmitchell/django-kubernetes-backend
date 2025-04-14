# To prevent running all tests via Django, ensure this file is imported
# test files that needs to use Django's ORM or other components.

from django.conf import settings

# Configure minimal Django settings
if not settings.configured:
    import django

    settings.configure(
        INSTALLED_APPS=[
            "tests",
        ],
    )
    django.setup()
