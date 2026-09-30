"""
Departmental Admin Service for DPIG.
Manages automatic provisioning of one Departmental Admin for every department,
department-scoped staff management, and time-based Alerts & Welfare Schemes.
"""
import logging
from typing import List, Dict, Any, Optional
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User
from core.models import Cluster, Department, UserProfile, GovernmentBroadcast, Complaint

logger = logging.getLogger(__name__)


def get_default_dept_admin_username(dept_code: str) -> str:
    """Generates standard username for a Department Admin."""
    clean_code = str(dept_code).strip().lower().replace('-', '_').replace(' ', '_')
    return f"deptadmin.{clean_code}"


def ensure_department_admins(cluster: Optional[Cluster] = None) -> List[Dict[str, Any]]:
    """
    Guarantees that for every Department in the cluster/system,
    exactly one designated Departmental Administrator user account exists.
    Returns list of provisioned admin info dictionaries.
    """
    if not cluster:
        cluster = Cluster.objects.filter(is_active=True).first()

    departments = Department.objects.filter(cluster=cluster) if cluster else Department.objects.all()
    results = []

    with transaction.atomic():
        for dept in departments:
            username = get_default_dept_admin_username(dept.code)
            clean_code = dept.code.lower().replace('-', '_').replace(' ', '_')
            domain = "chennaicorporation.gov.in"
            if cluster and cluster.contact_email and '@' in cluster.contact_email:
                domain = cluster.contact_email.split('@')[1].strip()
            email = f"admin.{clean_code}@{domain}"
            full_name = f"{dept.name} Admin"

            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': full_name,
                    'is_staff': True,
                    'is_active': True,
                }
            )

            # Ensure staff flags & password
            user.is_staff = True
            user.is_active = True
            if user_created:
                user.set_password('Admin@Dpig2026')
            user.save()

            profile, profile_created = UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'role': 'DEPT_ADMIN',
                    'cluster': cluster,
                    'department': dept,
                    'hierarchy_level': 4,  # Citywide Department Head Tier (CL1)
                    'designation': f"Departmental Administrator - {dept.name}",
                    'phone': dept.phone or '044-25384520'
                }
            )

            results.append({
                'username': username,
                'department_code': dept.code,
                'department_name': dept.name,
                'created': user_created or profile_created,
                'user_id': user.id,
            })
            logger.info("Ensured Department Admin for %s: %s", dept.name, username)

    return results
