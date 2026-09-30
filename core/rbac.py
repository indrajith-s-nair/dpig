"""
Role-Based Access Control (RBAC) Module for DPIG:
Defines role hierarchies, permission checking, jurisdiction scoping,
and view-protection decorators.
"""
from functools import wraps
from django.shortcuts import redirect, render
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import reverse


# Role Hierarchy & Identifiers
ROLE_SUPERADMIN = 'SUPERADMIN'
ROLE_DEPT_ADMIN = 'DEPT_ADMIN'
ROLE_COMMISSIONER = 'COMMISSIONER'
ROLE_CM_OFFICE = 'CM_OFFICE'
ROLE_ZONAL_OFFICER = 'ZONAL_OFFICER'
ROLE_WARD_OFFICER = 'WARD_OFFICER'
ROLE_FIELD_STAFF = 'FIELD_STAFF'
ROLE_POLICYMAKER = 'POLICYMAKER'
ROLE_AUDITOR = 'AUDITOR'
ROLE_CITIZEN = 'CITIZEN'

OFFICER_ROLES = [
    ROLE_WARD_OFFICER,
    ROLE_ZONAL_OFFICER,
    ROLE_COMMISSIONER,
    ROLE_CM_OFFICE,
    ROLE_FIELD_STAFF,
    ROLE_DEPT_ADMIN,
    ROLE_SUPERADMIN,
]

DEPT_ADMIN_ROLES = [
    ROLE_DEPT_ADMIN,
    ROLE_SUPERADMIN,
]

POLICY_ROLES = [
    ROLE_POLICYMAKER,
    ROLE_SUPERADMIN,
]

AUDITOR_ROLES = [
    ROLE_AUDITOR,
    ROLE_SUPERADMIN,
]

ADMIN_ROLES = [
    ROLE_SUPERADMIN,
]


def get_user_role(user) -> str:
    """Returns the standardized role string for a user."""
    if not user or not user.is_authenticated:
        return 'ANONYMOUS'
    if user.is_superuser:
        return ROLE_SUPERADMIN
    profile = getattr(user, 'profile', None)
    if profile and profile.role:
        return profile.role
    return ROLE_CITIZEN


def has_role(user, allowed_roles) -> bool:
    """Checks whether the user matches any of the allowed roles."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    user_role = get_user_role(user)
    return user_role in allowed_roles


def can_access_officer_console(user) -> bool:
    """Check if user has officer console privileges."""
    return has_role(user, OFFICER_ROLES)


def can_access_policymaker_console(user) -> bool:
    """Check if user has policymaker intelligence privileges."""
    return has_role(user, POLICY_ROLES)


def can_access_superadmin_console(user) -> bool:
    """Check if user has platform administration privileges."""
    return has_role(user, ADMIN_ROLES)


def can_access_dept_admin_console(user) -> bool:
    """Check if user has department administration privileges."""
    return has_role(user, DEPT_ADMIN_ROLES)


def can_access_auditor_console(user) -> bool:
    """Check if user has statutory auditor / compliance privileges."""
    return has_role(user, AUDITOR_ROLES)


def is_corporation_or_state_officer(user) -> bool:
    """
    Checks if an officer has corporation-wide or state-wide jurisdiction:
    CL1 (City Level 1 / Dept Head), CL2 (Deputy Commissioner),
    CL3 (Municipal Commissioner), CM_OFFICE (Apex State Level), or SUPERADMIN.
    Department Level officers (DL1, DL2, DL3) are local (per zone/ward) and return False.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    if not profile:
        return False
    if profile.role in [ROLE_SUPERADMIN, ROLE_COMMISSIONER, ROLE_CM_OFFICE]:
        return True
    hierarchy_level = getattr(profile, 'hierarchy_level', 1)
    if hierarchy_level >= 4:
        return True
    return False


def can_access_complaint(user, complaint) -> bool:
    """
    Jurisdiction check: Ensures an officer only accesses complaints
    within their assigned Ward, Zone, or Department, unless they are
    a Commissioner, CM Office, CL1-CL3, or SuperAdmin with city-wide oversight.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    profile = getattr(user, 'profile', None)
    if not profile:
        return False

    role = profile.role
    level = getattr(profile, 'hierarchy_level', 1)

    # Department Admin: oversight across all complaints in their department across all zones
    if role == ROLE_DEPT_ADMIN:
        if profile.department and complaint.department:
            return complaint.department == profile.department
        return True

    # Statutory Auditor: comprehensive statutory oversight across all complaints in all departments and zones
    if role == ROLE_AUDITOR:
        return True

    # SuperAdmin, CM Office, Commissioner, and City/Corporation-Level officers (CL1..CL3) have complete city-wide jurisdiction
    if role in [ROLE_SUPERADMIN, ROLE_COMMISSIONER, ROLE_CM_OFFICE] or (level >= 4 and role != ROLE_DEPT_ADMIN):
        return True

    # Direct assignee always has access to take action
    if complaint.current_assignee == user:
        return True

    # Zonal Officer / Level 3 (DL3): strictly assigned Zone
    if role == ROLE_ZONAL_OFFICER or level == 3:
        if profile.zone and complaint.zone == profile.zone:
            return True
        return False

    # Ward Officer / Field Staff / DL1 / DL2: complaint must be in their Ward/Zone and Department
    if profile.ward and complaint.ward == profile.ward:
        if profile.department and complaint.department:
            return complaint.department == profile.department
        return True
    if profile.zone and complaint.zone == profile.zone and level >= 2:
        if profile.department and complaint.department:
            return complaint.department == profile.department
        return True

    return False


def can_access_capital_project(user, project) -> bool:
    """
    Jurisdiction check: Ensures a policymaker only accesses capital project
    recommendations relevant to their assigned Ward or Zone.
    Citizens, field officers, and anonymous visitors cannot access capital projects.
    E.g. proposal for Ward 142 is only visible to Ward 142 Policymaker (and SuperAdmin / Statewide).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    role = get_user_role(user)
    if role not in POLICY_ROLES:
        return False

    if role == ROLE_SUPERADMIN:
        return True

    profile = getattr(user, 'profile', None)
    if not profile:
        return False

    # Cluster-level restriction: if user belongs to a specific cluster, project must belong to the same cluster
    if profile.cluster and project.cluster and project.cluster != profile.cluster:
        return False

    # Ward-level Policymaker (e.g. Ward 142)
    if profile.ward:
        return project.is_visible_to_ward(profile.ward.number)

    # Zonal-level Policymaker
    if profile.zone:
        return project.is_visible_to_zone(profile.zone.number)

    # Statewide / Citywide Policymaker (no ward, no zone restriction)
    return True


def filter_capital_projects_for_user(user, projects_qs_or_list):
    """
    Filters a queryset or list of CapitalProjectRecommendation objects
    to strictly enforce policymaker jurisdiction.
    Returns empty list if user is not an authorized policymaker or superadmin.
    """
    if not user or not user.is_authenticated:
        return []
    if not can_access_policymaker_console(user):
        return []

    role = get_user_role(user)
    if user.is_superuser or role == ROLE_SUPERADMIN:
        return list(projects_qs_or_list)

    profile = getattr(user, 'profile', None)
    if not profile:
        return []

    projects_list = list(projects_qs_or_list)

    # Cluster-level scoping
    if profile.cluster:
        projects_list = [p for p in projects_list if getattr(p, 'cluster_id', None) == profile.cluster.id or getattr(p, 'cluster', None) == profile.cluster]

    if profile.ward:
        return [p for p in projects_list if p.is_visible_to_ward(profile.ward.number)]

    if profile.zone:
        return [p for p in projects_list if p.is_visible_to_zone(profile.zone.number)]

    return projects_list


def role_required(allowed_roles, console_name="Administrative Console"):
    """
    Decorator for views that checks if the logged-in user possesses
    one of the allowed roles. If unauthorized, returns an explicit 403 page.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.warning(request, f"Please sign in with authorized credentials to access {console_name}.")
                return redirect(f"/login/?next={request.path}")

            if not has_role(request.user, allowed_roles):
                user_role = get_user_role(request.user)
                context = {
                    'console_name': console_name,
                    'user_role': user_role,
                    'required_roles': allowed_roles,
                    'path': request.path,
                }
                return render(request, 'errors/403_role_denied.html', context, status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


superadmin_required = role_required(ADMIN_ROLES, console_name="SuperAdmin Platform Control")
dept_admin_required = role_required(DEPT_ADMIN_ROLES, console_name="Departmental Administration Console")
officer_required = role_required(OFFICER_ROLES, console_name="Government Officer Console")
policymaker_required = role_required(POLICY_ROLES, console_name="Policymaker Intelligence Hub")
auditor_required = role_required(AUDITOR_ROLES, console_name="Statutory Audit & Compliance Hub")


def is_registered_citizen(user) -> bool:
    """
    Checks if a user is an authenticated, registered citizen.
    Municipal staff, department admins, officers, policymakers, auditors,
    superadmins, and unauthenticated visitors return False.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return False
    role = get_user_role(user)
    return role == ROLE_CITIZEN


def citizen_required(view_func):
    """
    Decorator for views that strictly enforces that ONLY authenticated,
    registered citizens can access the view (e.g. Register Civic Grievance).
    - Unauthenticated users are redirected to citizen login with a warning.
    - Non-citizen authenticated users (officers, admins, auditors, policymakers)
      are redirected to their respective console with an explicit role warning.
    - JSON / AJAX requests receive an explicit HTTP 401 or 403 response.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        is_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest' or
            'application/json' in request.headers.get('Accept', '')
        )

        if not request.user.is_authenticated:
            if is_ajax:
                return JsonResponse({
                    'status': 'UNAUTHORIZED',
                    'error': 'Only registered citizens can register a civic grievance. Please sign in or register.'
                }, status=401)
            messages.warning(
                request,
                "Only registered citizens are permitted to register a civic grievance. "
                "Please sign in with your citizen account or register using your Aadhaar."
            )
            return redirect(f"{reverse('citizen_login')}?next={request.path}")

        role = get_user_role(request.user)
        if role != ROLE_CITIZEN:
            if is_ajax:
                return JsonResponse({
                    'status': 'FORBIDDEN',
                    'error': 'Only registered citizens can register a civic grievance. Administrative and departmental accounts cannot submit civic complaints.'
                }, status=403)

            messages.warning(
                request,
                "Only registered citizens are permitted to register civic grievances. "
                "Administrative, municipal officer, policymaker, auditor, and departmental accounts cannot submit civic complaints."
            )
            if role == ROLE_SUPERADMIN:
                return redirect('feature_permission_matrix')
            elif role == ROLE_DEPT_ADMIN:
                return redirect('dept_admin_dashboard')
            elif role == ROLE_AUDITOR:
                return redirect('auditor_dashboard')
            elif role == ROLE_POLICYMAKER:
                return redirect('policymaker_dashboard')
            elif can_access_officer_console(request.user):
                return redirect('officer_dashboard')
            return redirect('home')

        return view_func(request, *args, **kwargs)

    return _wrapped_view

