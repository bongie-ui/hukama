from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from core.views import spa
from payments.views import payee_login_return, premium_return

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("thuma.api_urls")),
    path("paypal/premium-return/", premium_return),  # PayPal sends subscribers back here
    path("paypal/payee-login/", payee_login_return),  # Log in with PayPal returns payees here
    # Public legal pages (linked from PayPal's Log in with PayPal consent screen).
    path("legal/privacy/", TemplateView.as_view(template_name="legal/privacy.html"), name="privacy"),
    path("legal/terms/", TemplateView.as_view(template_name="legal/terms.html"), name="terms"),
    # Everything else is the React app (client-side routes included).
    re_path(r"^(?!api/|admin/|static/|paypal/|legal/).*$", spa),
]
