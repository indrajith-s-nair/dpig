"""
Global context processor for DPIG application templates.
"""
from django.conf import settings
from core.models import Cluster, UserProfile
from core.rbac import (
    get_user_role, can_access_officer_console,
    can_access_policymaker_console, can_access_superadmin_console,
    can_access_dept_admin_console, can_access_auditor_console
)


def app_global_context(request):
    """Provides platform-wide context variables to all templates."""
    active_cluster = None
    user_profile = None

    if request.user.is_authenticated:
        try:
            user_profile = request.user.profile
            active_cluster = user_profile.cluster
        except Exception:
            user_profile = None

    if not active_cluster or not getattr(active_cluster, 'is_active', True):
        active_cluster = Cluster.objects.filter(is_active=True).first()

    role = get_user_role(request.user)
    is_auth = request.user.is_authenticated
    is_citizen = (role == 'CITIZEN')
    is_dept_admin = (role == 'DEPT_ADMIN')
    is_officer = can_access_officer_console(request.user) and (role in ['WARD_OFFICER', 'FIELD_STAFF', 'ZONAL_OFFICER', 'COMMISSIONER'])
    is_policymaker = (role == 'POLICYMAKER')
    is_auditor = (role == 'AUDITOR')
    is_superadmin = (role == 'SUPERADMIN') or (request.user.is_superuser if is_auth else False)

    # Strict Role-Based Menu Isolation:
    # Citizen menus ("File Grievance", "Track Status", "Citizen Services", "+ Report Issue")
    # are ONLY visible if the user is unauthenticated or a logged-in CITIZEN.
    # Officers, Policymakers, Department Admins, Auditors, and SuperAdmins will NOT see citizen menus.
    show_citizen_menus = (not is_auth) or is_citizen

    raw_helpline = getattr(active_cluster, 'emergency_helpline', '1234') if active_cluster else '1234'
    if not raw_helpline or str(raw_helpline).strip() in ('1913', ''):
        helpline = '1234'
    else:
        helpline = str(raw_helpline).strip()

    return {
        'APP_NAME': 'Digital Public Infrastructure Governance',
        'APP_TAGLINE': 'State-Wide Citizen Grievance & Policy Intelligence Platform',
        'ACTIVE_CLUSTER': active_cluster,
        'ALL_CLUSTERS': Cluster.objects.filter(is_active=True),
        'ALL_SYSTEM_CLUSTERS': Cluster.objects.all().order_by('name'),
        'ACTIVE_CLUSTERS_COUNT': Cluster.objects.filter(is_active=True).count(),
        'DISABLED_CLUSTERS_COUNT': Cluster.objects.filter(is_active=False).count(),
        'HAS_ACTIVE_CLUSTER': Cluster.objects.filter(is_active=True).exists(),
        'USER_PROFILE': user_profile,
        'USER_ROLE': role,
        'IS_CITIZEN': is_citizen,
        'IS_DEPT_ADMIN': is_dept_admin,
        'IS_OFFICER': is_officer,
        'IS_POLICYMAKER': is_policymaker,
        'IS_AUDITOR': is_auditor,
        'IS_SUPERADMIN': is_superadmin,
        'SHOW_CITIZEN_MENUS': show_citizen_menus,
        'CAN_ACCESS_OFFICER': can_access_officer_console(request.user) and not is_citizen,
        'CAN_ACCESS_DEPT_ADMIN': can_access_dept_admin_console(request.user) and not is_citizen,
        'CAN_ACCESS_POLICYMAKER': can_access_policymaker_console(request.user) and not is_citizen,
        'CAN_ACCESS_AUDITOR': can_access_auditor_console(request.user) and not is_citizen,
        'CAN_ACCESS_SUPERADMIN': can_access_superadmin_console(request.user),
        'GOOGLE_MAPS_API_KEY': getattr(settings, 'GOOGLE_MAPS_API_KEY', ''),
        'EMERGENCY_HELPLINE': helpline,
    }
