import sys
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from core.models import (
    Cluster, Zone, Ward, Department, GrievanceCategory,
    Complaint, ComplaintAuditLog, AuditFinding, AIDecisionLog,
    SLAEscalationLog, GovernmentBroadcast, CapitalProjectRecommendation,
    YearlyTicketSequence, AadhaarVerificationRecord, UserProfile
)


class Command(BaseCommand):
    help = "Resets DPIG to a fresh deployment state by deleting all clusters, complaints, and demo accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            '--admin-username',
            type=str,
            default='superadmin',
            help='SuperAdmin username (default: superadmin)'
        )
        parser.add_argument(
            '--admin-email',
            type=str,
            default='admin@dpig.gov.in',
            help='SuperAdmin email (default: admin@dpig.gov.in)'
        )
        parser.add_argument(
            '--admin-password',
            type=str,
            default='Admin@Dpig2026',
            help='SuperAdmin password (default: Admin@Dpig2026)'
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Skip confirmation prompts'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("=== Resetting DPIG to Fresh Production Deployment State ==="))

        admin_username = options['admin_username']
        admin_email = options['admin_email']
        admin_password = options['admin_password']

        # 1. Clear active sessions
        sessions_count = Session.objects.count()
        Session.objects.all().delete()
        self.stdout.write(f"Cleared {sessions_count} active user sessions.")

        # 2. Clear transactional civic records
        complaints_count = Complaint.objects.count()
        Complaint.objects.all().delete()
        self.stdout.write(f"Deleted {complaints_count} complaints and associated audit records.")

        audit_logs_count = ComplaintAuditLog.objects.count()
        ComplaintAuditLog.objects.all().delete()
        
        findings_count = AuditFinding.objects.count()
        AuditFinding.objects.all().delete()

        ai_logs_count = AIDecisionLog.objects.count()
        AIDecisionLog.objects.all().delete()

        sla_logs_count = SLAEscalationLog.objects.count()
        SLAEscalationLog.objects.all().delete()

        broadcasts_count = GovernmentBroadcast.objects.count()
        GovernmentBroadcast.objects.all().delete()
        self.stdout.write(f"Deleted {broadcasts_count} government broadcasts.")

        recs_count = CapitalProjectRecommendation.objects.count()
        CapitalProjectRecommendation.objects.all().delete()
        self.stdout.write(f"Deleted {recs_count} capital project recommendations.")

        seq_count = YearlyTicketSequence.objects.count()
        YearlyTicketSequence.objects.all().delete()

        aadhaar_records_count = AadhaarVerificationRecord.objects.count()
        AadhaarVerificationRecord.objects.all().delete()

        # 3. Clear all clusters (cascades to Zone, Ward, Department, GrievanceCategory)
        clusters_count = Cluster.objects.count()
        zones_count = Zone.objects.count()
        wards_count = Ward.objects.count()
        depts_count = Department.objects.count()
        cats_count = GrievanceCategory.objects.count()

        Cluster.objects.all().delete()
        self.stdout.write(
            f"Deleted {clusters_count} clusters (including {zones_count} zones, "
            f"{wards_count} wards, {depts_count} departments, {cats_count} SLA categories)."
        )

        # 4. Delete all demo users except designated superadmin
        demo_users = User.objects.exclude(username=admin_username)
        demo_count = demo_users.count()
        demo_users.delete()
        self.stdout.write(f"Deleted {demo_count} demo and staff user accounts.")

        # 5. Provision / Ensure pristine SuperAdmin account
        superadmin, created = User.objects.get_or_create(
            username=admin_username,
            defaults={
                'email': admin_email,
                'first_name': 'Platform',
                'last_name': 'SuperAdmin',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            }
        )
        superadmin.email = admin_email
        superadmin.first_name = 'Platform'
        superadmin.last_name = 'SuperAdmin'
        superadmin.is_staff = True
        superadmin.is_superuser = True
        superadmin.is_active = True
        superadmin.set_password(admin_password)
        superadmin.save()

        profile, p_created = UserProfile.objects.get_or_create(
            user=superadmin,
            defaults={
                'role': 'SUPERADMIN',
                'hierarchy_level': 7,
                'designation': 'State SuperAdmin',
                'cluster': None,
                'zone': None,
                'ward': None,
                'department': None,
                'is_aadhaar_verified': True,
            }
        )
        profile.role = 'SUPERADMIN'
        profile.hierarchy_level = 7
        profile.designation = 'State SuperAdmin'
        profile.cluster = None
        profile.zone = None
        profile.ward = None
        profile.department = None
        profile.phone = ''
        profile.aadhaar_hash = ''
        profile.aadhaar_last4 = ''
        profile.is_aadhaar_verified = True
        profile.save()

        # Reclaim sqlite space if applicable and not inside an open test transaction
        from django.db import connection
        if connection.vendor == 'sqlite' and not connection.in_atomic_block:
            try:
                with connection.cursor() as cursor:
                    cursor.execute('VACUUM')
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(
            f"\n[OK] Fresh deployment setup complete!\n"
            f"  - Sole administrative user: {admin_username}\n"
            f"  - Email: {admin_email}\n"
            f"  - Password: {admin_password}\n"
            f"  - Role: State SuperAdmin (Level 7 CM_OFFICE / Apex)\n"
            f"  - Clusters: 0 (Ready for cluster onboarding via /superadmin/clusters/)\n"
            f"  - Complaints: 0\n"
        ))
