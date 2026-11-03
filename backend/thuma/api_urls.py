"""Every /api/ route (BUILD_SPEC §10)."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts import views as accounts
from agent import views as agent
from core.views import health
from mandates import views as mandates
from payments import views as payments

from .api_schema import annotate

urlpatterns = [
    path("health/", health, name="health"),
    path("", include("payments.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),

    path("auth/me/", accounts.me),
    path("auth/login/", accounts.login_view),
    path("auth/logout/", accounts.logout_view),
    path("auth/demo-users/", accounts.demo_users),
    path("auth/demo-login/", accounts.demo_login),

    path("family/", mandates.family),
    path("beneficiaries/", mandates.beneficiaries),
    path("beneficiaries/<uuid:pk>/", mandates.beneficiary_detail),
    path("payees/", mandates.payees),

    path("mandate-types/", mandates.mandate_types),
    path("mandates/", mandates.mandates),
    path("mandates/draft/", mandates.mandate_draft),
    path("mandates/preview-rules/", mandates.rules_preview),
    path("mandates/<uuid:pk>/", mandates.mandate_detail),
    path("mandates/<uuid:pk>/funders/", mandates.mandate_funders),
    path("mandates/<uuid:pk>/coverage/", mandates.mandate_coverage),
    path("mandates/<uuid:pk>/fund/create-order/", payments.fund_create_order),
    path("mandates/<uuid:pk>/fund/capture/", payments.fund_capture),
    path("mandates/<uuid:pk>/fundings/", payments.mandate_fundings),
    path("mandates/<uuid:pk>/contribution-link/", mandates.mandate_contribution_link),
    path("public/pools/<str:token>/", payments.public_pool),
    path("public/pools/<str:token>/contribute/", payments.public_contribute),
    path("public/pools/<str:token>/capture/", payments.public_capture),
    path("config/paypal/", payments.paypal_config),
    path("webhooks/paypal/", payments.paypal_webhook),

    path("requests/", mandates.requests_),
    path("requests/<uuid:pk>/", mandates.request_detail),
    path("requests/<uuid:pk>/approval/", mandates.request_approval),
    path("uploads/", mandates.uploads),
    path("uploads/<uuid:pk>/", mandates.upload_file),
    path("ledger/", mandates.ledger),

    path("chat/conversations/", agent.conversations),
    path("chat/<uuid:pk>/messages/", agent.messages),

    path("dashboard/data/", mandates.dashboard_data),
    path("dashboard/summary/", mandates.dashboard_summary),
    path("dashboard/layout/", mandates.dashboard_layout),
    path("dashboard/ai/turn/", agent.dashboard_turn),

    path("demo/last-mile/<uuid:pk>/collect/", payments.demo_collect),
]

annotate()
