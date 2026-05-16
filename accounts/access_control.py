from dataclasses import dataclass
from typing import Iterable

from django.urls import reverse
from urllib.parse import urlencode

from payments.permissions import user_is_finance_admin


GROUP_ROLE_MAP = {
    "Finance Admin": "finance_admin",
    "System Admin": "system_admin",
    "Legal Officer": "legal_officer",
    "Buyer Advocate": "buyer_advocate",
    "Seller Advocate": "seller_advocate",
    "Registry Officer": "registry_officer",
    "Operations Officer": "operations_officer",
}


ROLE_PERMISSIONS = {
    "super_admin": {
        "dashboard.staff",
        "tasks.view_all",
        "tasks.view_assigned",
        "tasks.assign",
        "verification.review",
        "verification.manage",
        "extension.view_assigned",
        "survey.view_assigned",
        "plots.view_all",
        "documents.review_legal",
        "documents.review_assigned",
        "finance.view_escrow",
        "finance.release_payout",
        "finance.manage",
        "wallet.manage",
        "audit.view_all",
        "users.manage",
        "transactions.manage",
    },
    "system_admin": {
        "dashboard.staff",
        "tasks.view_all",
        "tasks.assign",
        "verification.review",
        "verification.manage",
        "extension.view_assigned",
        "survey.view_assigned",
        "plots.view_all",
        "audit.view_all",
        "users.manage",
        "wallet.manage",
    },
    "finance_admin": {
        "dashboard.staff",
        "tasks.view_all",
        "finance.view_escrow",
        "finance.release_payout",
        "finance.manage",
        "wallet.manage",
        "audit.view_all",
    },
    "legal_officer": {
        "dashboard.staff",
        "tasks.view_assigned",
        "documents.review_legal",
        "documents.review_assigned",
    },
    "buyer_advocate": {
        "dashboard.staff",
        "tasks.view_assigned",
        "documents.review_assigned",
    },
    "seller_advocate": {
        "dashboard.staff",
        "tasks.view_assigned",
        "documents.review_assigned",
    },
    "operations_officer": {
        "dashboard.staff",
        "tasks.view_all",
        "tasks.assign",
        "verification.review",
        "plots.view_all",
    },
    "registry_officer": {
        "dashboard.staff",
        "tasks.view_assigned",
        "verification.review",
        "plots.view_assigned",
    },
    "extension_officer": {
        "dashboard.staff",
        "tasks.view_assigned",
        "extension.view_assigned",
    },
    "land_surveyor": {
        "dashboard.staff",
        "tasks.view_assigned",
        "survey.view_assigned",
    },
    "agent": {
        "dashboard.client",
        "plots.view_own",
        "messages.view_own",
        "wallet.view_own",
        "transactions.view_own",
    },
    "landowner": {
        "dashboard.client",
        "plots.view_own",
        "messages.view_own",
        "wallet.view_own",
        "transactions.view_own",
    },
    "buyer": {
        "dashboard.client",
        "saved_plots.view_own",
        "payments.view_own",
        "wallet.view_own",
        "transactions.view_own",
    },
}


@dataclass(frozen=True)
class AccessProfile:
    workspace: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    primary_role: str

    @property
    def is_staff_workspace(self):
        return self.workspace == "operations"

    def can(self, permission: str):
        return permission in self.permissions


@dataclass(frozen=True)
class DashboardModule:
    key: str
    title: str
    description: str
    icon: str
    section_key: str
    permission: str
    section: str
    badge_key: str = ""
    url_name: str = ""


DASHBOARD_MODULES = (
    DashboardModule(
        key="overview",
        title="Overview",
        description="Queue health, approvals, and operational signals.",
        icon="fas fa-home",
        section_key="overview",
        permission="dashboard.staff",
        section="Operations",
    ),
    DashboardModule(
        key="task_inbox",
        title="Task Inbox",
        description="Assigned work items and follow-up actions.",
        icon="fas fa-inbox",
        section_key="tasks",
        permission="tasks.view_assigned",
        section="Operations",
        badge_key="my_tasks_count",
        url_name="verification:my_tasks",
    ),
    DashboardModule(
        key="verification",
        title="Verification Queue",
        description="Plot onboarding and due diligence review.",
        icon="fas fa-check-circle",
        section_key="verification",
        permission="verification.review",
        section="Operations",
        badge_key="pending_review_count",
        url_name="verification:verification_queue",
    ),
    DashboardModule(
        key="task_assignment",
        title="Task Assignment",
        description="Distribute work to field and legal officers.",
        icon="fas fa-tasks",
        section_key="tasks",
        permission="tasks.assign",
        section="Operations",
        badge_key="unassigned_tasks_count",
        url_name="verification:task_assignment",
    ),
    DashboardModule(
        key="survey",
        title="Survey & Mapping",
        description="Boundary checks, reports, and parcel verification.",
        icon="fas fa-map-marked-alt",
        section_key="tasks",
        permission="survey.view_assigned",
        section="Fieldwork",
        badge_key="surveyor_tasks_count",
        url_name="verification:surveyor_dashboard",
    ),
    DashboardModule(
        key="extension",
        title="Agronomy & Extension",
        description="Soil suitability reviews and field recommendations.",
        icon="fas fa-leaf",
        section_key="tasks",
        permission="extension.view_assigned",
        section="Fieldwork",
        badge_key="extension_tasks_count",
        url_name="verification:extension_dashboard",
    ),
    DashboardModule(
        key="wallet",
        title="Wallet",
        description="Deposits, withdrawals, and direct purchase or lease payments.",
        icon="fas fa-wallet",
        section_key="wallet",
        permission="wallet.view_own",
        section="Finance",
    ),
    DashboardModule(
        key="payments",
        title="Escrow & Payouts",
        description="Controlled finance workflow and disbursement checks.",
        icon="fas fa-money-check-dollar",
        section_key="finance",
        permission="finance.view_escrow",
        section="Finance",
        badge_key="payment_admin_task_count",
    ),
    DashboardModule(
        key="transactions",
        title="Land Transfers",
        description="Legal stages, conveyancing timeline, and registered titles.",
        icon="fas fa-file-contract",
        section_key="transactions",
        permission="transactions.view_own",
        section="Finance",
    ),
    DashboardModule(
        key="wallet_control",
        title="Wallet Control",
        description="Deposit, withdrawal, and wallet funding oversight for finance teams.",
        icon="fas fa-piggy-bank",
        section_key="finance",
        permission="wallet.manage",
        section="Finance",
        badge_key="wallet_pending_count",
    ),
    DashboardModule(
        key="audit",
        title="Audit Trail",
        description="Immutable activity records for sensitive actions.",
        icon="fas fa-shield-alt",
        section_key="audit",
        permission="audit.view_all",
        section="Governance",
        url_name="verification:audit_logs",
    ),
    DashboardModule(
        key="users",
        title="Users & Roles",
        description="Staff role assignment and access management.",
        icon="fas fa-users-cog",
        section_key="governance",
        permission="users.manage",
        section="Governance",
    ),
)


def _has_group(user, group_name: str):
    return user.groups.filter(name=group_name).exists()


def _collect_roles(user) -> list[str]:
    roles: list[str] = []
    if not getattr(user, "is_authenticated", False):
        return roles

    if user.is_superuser:
        roles.append("super_admin")
    if user.is_staff:
        roles.append("system_admin")
    if user_is_finance_admin(user):
        roles.append("finance_admin")

    for group_name, role_name in GROUP_ROLE_MAP.items():
        if _has_group(user, group_name):
            roles.append(role_name)

    if hasattr(user, "extension_officer"):
        roles.append("extension_officer")
    if hasattr(user, "land_surveyor"):
        roles.append("land_surveyor")
    if hasattr(user, "agent"):
        roles.append("agent")
    if hasattr(user, "landownerprofile"):
        roles.append("landowner")

    profile = getattr(user, "profile", None)
    if profile and profile.role:
        roles.append(profile.role)

    seen = set()
    deduped = []
    for role in roles:
        if role and role not in seen:
            seen.add(role)
            deduped.append(role)
    return deduped


def _collect_permissions(roles: Iterable[str]) -> frozenset[str]:
    permissions = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, set()))
    return frozenset(permissions)


def resolve_access_profile(user) -> AccessProfile:
    roles = _collect_roles(user)
    permissions = _collect_permissions(roles)

    if "dashboard.staff" in permissions:
        workspace = "operations"
    elif "dashboard.client" in permissions:
        workspace = "client"
    else:
        workspace = "public"

    primary_role = roles[0] if roles else "guest"
    return AccessProfile(
        workspace=workspace,
        roles=tuple(roles),
        permissions=permissions,
        primary_role=primary_role,
    )


def get_dashboard_landing_url_name(access_profile: AccessProfile):
    if access_profile.is_staff_workspace:
        return "listings:dashboard_router"
    if "agent" in access_profile.roles or "landowner" in access_profile.roles:
        return "listings:dashboard_router"
    if "buyer" in access_profile.roles:
        return "listings:dashboard_router"
    return "listings:home"


def get_default_dashboard_section(access_profile: AccessProfile):
    if access_profile.can("finance.view_escrow"):
        return "finance"
    if access_profile.can("wallet.view_own") and "buyer" in access_profile.roles:
        return "wallet"
    if access_profile.can("tasks.view_assigned"):
        return "tasks"
    if "agent" in access_profile.roles or "landowner" in access_profile.roles:
        return "portfolio"
    return "overview"


def build_dashboard_url(section_key: str):
    return f"{reverse('listings:dashboard_router')}?{urlencode({'section': section_key})}"


def build_dashboard_modules(access_profile: AccessProfile, badge_counts=None):
    badge_counts = badge_counts or {}
    modules = []
    for module in DASHBOARD_MODULES:
        if not access_profile.can(module.permission):
            continue
        modules.append(
            {
                "key": module.key,
                "title": module.title,
                "description": module.description,
                "icon": module.icon,
                "section": module.section,
                "section_key": module.section_key,
                "url": reverse(module.url_name) if module.url_name else build_dashboard_url(module.section_key),
                "badge": badge_counts.get(module.badge_key, 0) if module.badge_key else 0,
            }
        )
    return modules


def humanize_role(role: str):
    return role.replace("_", " ").title()
