from django.contrib import admin
from django.urls import include, path, re_path

from core.views import spa
from payments.views import premium_return

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("thuma.api_urls")),
    path("paypal/premium-return/", premium_return),  # PayPal sends subscribers back here
    # Everything else is the React app (client-side routes included).
    re_path(r"^(?!api/|admin/|static/|paypal/).*$", spa),
]
