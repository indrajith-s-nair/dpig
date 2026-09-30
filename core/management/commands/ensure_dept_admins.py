"""
Django management command to provision Departmental Administrators for all departments.
Usage: python manage.py ensure_dept_admins
"""
from django.core.management.base import BaseCommand
from core.dept_admin_service import ensure_department_admins
from core.models import Cluster


class Command(BaseCommand):
    help = 'Ensures one Departmental Administrator user exists for each municipal service department.'

    def handle(self, *args, **options):
        cluster = Cluster.objects.filter(is_active=True).first()
        self.stdout.write(f"Provisioning Departmental Administrators for cluster: {cluster}...")
        results = ensure_department_admins(cluster)
        for r in results:
            action = "Created" if r['created'] else "Verified/Updated"
            self.stdout.write(self.style.SUCCESS(
                f"  [{r['department_code']}] {r['department_name']} -> {r['username']} ({action})"
            ))
        self.stdout.write(self.style.SUCCESS(f"Successfully provisioned {len(results)} Department Admins."))
