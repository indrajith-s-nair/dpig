"""
Django management command to seed Greater Chennai Corporation (GCC) demo data.
Usage: python manage.py seed_gcc
"""
import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Cluster, UserProfile, Complaint, GrievanceCategory, Ward, Department
from core.cluster_importer import import_cluster_from_excel
from core.digipin import encode as encode_digipin, format_digipin
from core import gemini_service


class Command(BaseCommand):
    help = 'Seeds Greater Chennai Corporation cluster, zones, wards, officers, sample complaints, and AI insights.'

    def handle(self, *args, **options):
        self.stdout.write("Starting GCC Cluster seeding...")
        sample_path = 'templates_data/gcc_government_cluster_template.xlsx'

        if not os.path.exists(sample_path):
            self.stdout.write("Generating template first...")
            import generate_template

        result = import_cluster_from_excel(sample_path)
        self.stdout.write(self.style.SUCCESS(f"Cluster '{result['cluster_name']}' created/updated."))

        cluster = Cluster.objects.get(code='GCC')

        # Create demo SuperAdmin user
        superadmin, _ = User.objects.get_or_create(
            username='superadmin',
            defaults={'email': 'superadmin@tn.gov.in', 'first_name': 'State', 'last_name': 'SuperAdmin'}
        )
        superadmin.is_staff = True
        superadmin.is_superuser = True
        superadmin.set_password('Admin@Dpig2026')
        superadmin.save()
        UserProfile.objects.update_or_create(
            user=superadmin,
            defaults={'role': 'SUPERADMIN', 'cluster': cluster, 'designation': 'State DPI Administrator'}
        )

        # Create demo Citizen user
        citizen_user, _ = User.objects.get_or_create(
            username='citizen.demo',
            defaults={'email': 'indrajith.nair.s@gmail.com', 'first_name': 'Karthik', 'last_name': 'Raman'}
        )
        citizen_user.set_password('Admin@Dpig2026')
        citizen_user.save()
        UserProfile.objects.update_or_create(
            user=citizen_user,
            defaults={'role': 'CITIZEN', 'cluster': cluster, 'phone': '9840123456'}
        )

        # Seed full roster of workflow escalation officers across DL1 -> DL2 -> DL3 -> CL1 -> CL2 -> CL3 -> CM_OFFICE
        from core.officer_bulk_service import generate_officer_template_dataframe, parse_and_provision_officers
        from core.dept_admin_service import ensure_department_admins
        dept_admins = ensure_department_admins(cluster)
        self.stdout.write(self.style.SUCCESS(f"Provisioned {len(dept_admins)} Departmental Administrators for all departments."))
        df_officers = generate_officer_template_dataframe()
        prov_res = parse_and_provision_officers(df_officers, cluster=cluster, update_existing=True)
        self.stdout.write(self.style.SUCCESS(f"Provisioned {prov_res['created_count'] + prov_res['updated_count']} workflow officers across DL1..CM_OFFICE."))
        sample_complaints = [
            {
                "title": "Severe Waterlogging and Flooded Sub-Road",
                "desc": "Kavignar Kannadasan Road in Ward 142 is severely waterlogged with 1.5 ft standing rain water after yesterday evening rains. Vehicle movement completely blocked and water entering residential gates.",
                "lat": 13.0450, "lng": 80.2210,
                "cat_code": "WATERLOGGING", "ward_num": 142, "sev": "HIGH", "status": "ASSIGNED"
            },
            {
                "title": "Overflowing Garbage Dumper Bins and Animal Scattering",
                "desc": "Two municipal green bins near Basin Bridge Junction in Ward 52 have not been cleared for 3 days. Cattle and dogs are scattering waste across the roadway, causing extreme stench.",
                "lat": 13.1090, "lng": 80.2940,
                "cat_code": "GARBAGE_OVERFLOW", "ward_num": 52, "sev": "HIGH", "status": "FIELD_VERIFICATION"
            },
            {
                "title": "Open Manhole Without Warning Barricade on 2nd Avenue",
                "desc": "A heavy stormwater drain manhole cover is broken and left open right opposite the school bus stop. Extreme danger for pedestrians and two-wheelers in low visibility.",
                "lat": 13.0850, "lng": 80.2100,
                "cat_code": "MANHOLE_OPEN", "ward_num": 108, "sev": "CRITICAL", "status": "ESCALATED"
            },
            {
                "title": "Continuous Dark Stretch - 5 Streetlights Not Working",
                "desc": "Entire stretch of 4th Main Road in Ward 172 has had no street lighting for over a week. Resident women and seniors feel unsafe walking in total darkness after 7 PM.",
                "lat": 13.0060, "lng": 80.2570,
                "cat_code": "STREETLIGHT_OUT", "ward_num": 172, "sev": "MEDIUM", "status": "RESOLVED"
            },
            {
                "title": "Deep Pothole Cluster Damaging Two-Wheelers",
                "desc": "Multiple sharp potholes on Arcot Road near Metro station entrance causing skidding and severe traffic bottleneck during morning peak hours.",
                "lat": 13.0520, "lng": 80.2250,
                "cat_code": "POTHOLE", "ward_num": 130, "sev": "MEDIUM", "status": "CITIZEN_CONFIRMED"
            }
        ]

        ae_officer = User.objects.filter(username='ae.ward108').first()

        for sc in sample_complaints:
            ward = Ward.objects.filter(number=sc["ward_num"], zone__cluster=cluster).first()
            zone = ward.zone if ward else cluster.zones.first()
            cat = GrievanceCategory.objects.filter(code=sc["cat_code"], cluster=cluster).first()
            dept = cat.department if cat else Department.objects.filter(cluster=cluster).first()
            digipin = format_digipin(encode_digipin(sc["lat"], sc["lng"], precision=10))

            c = Complaint.objects.filter(cluster=cluster, title=sc["title"]).first()
            if not c:
                from core.models import generate_ticket_number
                ticket_number = generate_ticket_number(cluster=cluster, year=2026)
                c = Complaint.objects.create(
                    ticket_number=ticket_number,
                    cluster=cluster,
                    zone=zone,
                    ward=ward,
                    department=dept,
                    category=cat,
                    citizen=citizen_user,
                    citizen_name=citizen_user.get_full_name(),
                    citizen_email=citizen_user.email,
                    citizen_phone="9840123456",
                    title=sc["title"],
                    description=sc["desc"],
                    latitude=sc["lat"],
                    longitude=sc["lng"],
                    digipin=digipin,
                    status=sc["status"],
                    severity=sc["sev"],
                    current_assignee=ae_officer,
                    citizen_rating=5 if sc["status"] == "CITIZEN_CONFIRMED" else None,
                    citizen_feedback="Prompt and excellent work by the ward engineering team!" if sc["status"] == "CITIZEN_CONFIRMED" else "",
                )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(sample_complaints)} sample grievances."))

        # Synthesize initial Policymaker Capital Project Insights
        from core.tasks import refresh_policymaker_insights_task
        refresh_policymaker_insights_task(cluster.id)
        self.stdout.write(self.style.SUCCESS("Successfully synthesized initial AI Capital Project Recommendations."))
