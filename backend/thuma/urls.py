from django.contrib import admin
from django.urls import include, path, re_path

from core.views import spa
from payments.views import payee_login_return, premium_return

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("thuma.api_urls")),
    path("paypal/premium-return/", premium_return),  # PayPal sends subscribers back here
    path("paypal/payee-login/", payee_login_return),  # Log in with PayPal returns payees here
    # Everything else is the React app (client-side routes included).
    re_path(r"^(?!api/|admin/|static/|paypal/).*$", spa),
]
