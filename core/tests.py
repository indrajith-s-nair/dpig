"""
Comprehensive Automated Test Suite for DPIG:
- DIGIPIN encoding/decoding and bounds check
- SHA-256 cryptographic audit chain verification
- 1-Click Cluster Onboarding Workbook parser (GCC dataset)
- Complaint state machine, SLA countdown and overdue checks
- Email notification dispatch & fallback logging
- Gemini AI triage service
"""
import os
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import io
import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import (
    Cluster, Zone, Ward, Department, GrievanceCategory, UserProfile,
    Complaint, ComplaintAuditLog, AuditFinding, GovernmentBroadcast, CapitalProjectRecommendation,
    YearlyTicketSequence, generate_ticket_number,
    WORKFLOW_LEVEL_CODES, LEVEL_CODE_TO_INT, LEVEL_INT_TO_CODE, LEVEL_LABELS
)
from core.rbac import can_access_auditor_console, can_access_complaint
from core.digipin import encode as encode_digipin, decode as decode_digipin, format_digipin, validate_digipin, haversine_distance_meters
from core.cluster_importer import import_cluster_from_excel
from core.officer_bulk_service import (
    generate_officer_template_dataframe, export_officer_template, parse_and_provision_officers
)
from core.tasks import monitor_sla_deadlines_task
from core import notifications
from core import gemini_service


class DigipinTestCase(TestCase):
    def test_digipin_encode_decode(self):
        # Chennai Ripon Building
        lat, lon = 13.0827, 80.2707
        code = encode_digipin(lat, lon, precision=10)
        self.assertEqual(len(code), 10)
        formatted = format_digipin(code)
        self.assertEqual(len(formatted), 12)  # XXX-XXX-XXXX format
        self.assertTrue(validate_digipin(code))

        # Decode
        decoded = decode_digipin(code)
        self.assertAlmostEqual(decoded['latitude'], lat, delta=0.01)
        self.assertAlmostEqual(decoded['longitude'], lon, delta=0.01)

    def test_haversine_distance(self):
        # Ripon building to Chennai Central (~500m)
        dist = haversine_distance_meters(13.0827, 80.2707, 13.0823, 80.2755)
        self.assertGreater(dist, 400)
        self.assertLess(dist, 700)


class ClusterOnboardTestCase(TestCase):
    def test_gcc_workbook_import(self):
        sample_path = 'templates_data/gcc_government_cluster_template.xlsx'
        self.assertTrue(os.path.exists(sample_path), "GCC template workbook must exist")

        result = import_cluster_from_excel(sample_path)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['cluster_code'], 'GCC')
        self.assertEqual(result['zones_count'], 15)
        self.assertEqual(result['wards_count'], 200)
        self.assertEqual(result['departments_count'], 8)
        self.assertGreaterEqual(result['categories_count'], 15)
        self.assertGreaterEqual(result['staff_count'], 10)

        # Verify cluster in database
        cluster = Cluster.objects.get(code='GCC')
        self.assertEqual(cluster.zones.count(), 15)
        self.assertEqual(Ward.objects.filter(zone__cluster=cluster).count(), 200)


class ComplaintLifecycleAndAuditTestCase(TestCase):
    def setUp(self):
        self.cluster = Cluster.objects.create(
            name="Greater Chennai Corporation",
            code="GCC_TEST",
            headquarters_lat=13.0827,
            headquarters_lng=80.2707
        )
        self.zone = Zone.objects.create(cluster=self.cluster, number=8, name="Anna Nagar")
        self.ward = Ward.objects.create(zone=self.zone, number=108, name="Anna Nagar West")
        self.dept = Department.objects.create(cluster=self.cluster, code="ROADS", name="Roads")
        self.cat = GrievanceCategory.objects.create(
            cluster=self.cluster, department=self.dept, code="POTHOLE",
            name="Road Pothole Repair", sla_hours=24
        )
        self.officer_user = User.objects.create_user(username="ae.test", email="ae.test@example.com", password="pass")
        self.officer_profile = UserProfile.objects.create(
            user=self.officer_user, cluster=self.cluster, role="WARD_OFFICER", ward=self.ward, department=self.dept
        )

    def test_complaint_creation_and_audit_hash_chain(self):
        complaint = Complaint.objects.create(
            cluster=self.cluster,
            zone=self.zone,
            ward=self.ward,
            department=self.dept,
            category=self.cat,
            citizen_name="Citizen Tester",
            citizen_email="indrajith.nair.s@gmail.com",
            title="Broken road pothole near signal",
            description="Deep pothole causing accidents near roundabout.",
            latitude=13.0850,
            longitude=80.2100,
            status="SUBMITTED"
        )

        # Check auto-generated fields
        self.assertTrue(complaint.ticket_number.startswith(f"DPIG-{timezone.now().year}-GCC_TEST-"))
        self.assertTrue(len(complaint.digipin) > 0)
        self.assertIsNotNone(complaint.sla_deadline)

        # Verify Genesis audit log exists
        self.assertEqual(complaint.audit_logs.count(), 1)
        genesis = complaint.audit_logs.first()
        self.assertEqual(genesis.previous_hash, "0" * 64)
        self.assertTrue(genesis.verify_integrity())

        # Transition status to FIELD_VERIFICATION and verify chain
        complaint.status = "FIELD_VERIFICATION"
        complaint.save()
        block2 = complaint.create_audit_block(
            action="FIELD_INSPECTION_STARTED",
            performed_by=self.officer_user,
            actor_role="OFFICER",
            details={"inspection_vehicle": "TN-01-A-1234"}
        )
        self.assertEqual(block2.previous_hash, genesis.current_hash)
        self.assertTrue(block2.verify_integrity())

        # Test verification API
        client = Client()
        response = client.get(f"/api/verify-audit/{complaint.ticket_number}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_chain_intact"])
        self.assertEqual(data["total_blocks"], 2)

    def test_email_notifications_execution(self):
        complaint = Complaint.objects.create(
            cluster=self.cluster,
            zone=self.zone,
            ward=self.ward,
            department=self.dept,
            category=self.cat,
            citizen_name="Citizen Tester",
            citizen_email="indrajith.nair.s@gmail.com",
            title="Test Pothole Notification",
            description="Test notification pipeline",
            latitude=13.0850,
            longitude=80.2100,
            status="SUBMITTED"
        )
        # Verify notification calls execute cleanly without unhandled exceptions
        res1 = notifications.notify_complaint_created(complaint)
        res2 = notifications.notify_complaint_assigned(complaint, self.officer_user)
        res3 = notifications.notify_complaint_status_changed(complaint, "SUBMITTED", "FIELD_VERIFICATION", notes="Team dispatched")
        res4 = notifications.notify_complaint_closed(complaint, closed_by_citizen=True)
        # Each returns bool (True or False depending on live network / test SMTP, but never raises uncaught error)
        self.assertIsInstance(res1, bool)
        self.assertIsInstance(res2, bool)
        self.assertIsInstance(res3, bool)
        self.assertIsInstance(res4, bool)


class AuthAndOfficerAccessTestCase(TestCase):
    def setUp(self):
        self.cluster = Cluster.objects.create(
            name="Greater Chennai Corporation",
            code="GCC_AUTH_TEST",
            headquarters_lat=13.0827,
            headquarters_lng=80.2707
        )
        self.officer_user = User.objects.create_user(
            username="ae.test_auth",
            email="ae.test_auth@example.com",
            password="Admin@Dpig2026"
        )
        self.officer_profile = UserProfile.objects.create(
            user=self.officer_user,
            cluster=self.cluster,
            role="WARD_OFFICER"
        )
        self.client = Client()

    def test_unauthenticated_officer_access_redirects_to_login(self):
        response = self.client.get('/officer/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/?next=/officer/', response.url)

    def test_login_page_renders_successfully(self):
        response = self.client.get('/login/?next=/officer/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unified Portal Authentication")
        self.assertContains(response, "Staff & Officer Sign In")

    def test_credential_login_redirects_to_next(self):
        response = self.client.post('/login/', {
            'username': 'ae.test_auth',
            'password': 'Admin@Dpig2026',
            'next': '/officer/'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/officer/')

        # After login, officer dashboard returns 200
        dashboard_response = self.client.get('/officer/')
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, "Grievance Triage & Resolution Console")

    def test_switch_demo_role_redirects_to_officer(self):
        response = self.client.get('/switch-role/WARD_OFFICER/?next=/officer/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/officer/')

        # Follow redirect and verify officer console renders
        dashboard_response = self.client.get('/officer/')
        self.assertEqual(dashboard_response.status_code, 200)

    def test_logout_redirects_home(self):
        self.client.login(username='ae.test_auth', password='Admin@Dpig2026')
        response = self.client.get('/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_zonal_officer_royapuram_switch_and_console_visibility(self):
        # Create Royapuram (Zone 5) and complaint assigned to zo5
        cluster = Cluster.objects.first() or Cluster.objects.create(name="GCC", code="GCC")
        zone5 = Zone.objects.create(cluster=cluster, number=5, name="Royapuram")
        ward59 = Ward.objects.create(zone=zone5, number=59, name="Ward 59")
        dept = Department.objects.create(cluster=cluster, name="Electrical", code="LIGHTS")

        # 1-click switch to Zonal Officer Royapuram
        switch_resp = self.client.get('/switch-role/ZONAL_OFFICER_ROYAPURAM/?next=/officer/')
        self.assertEqual(switch_resp.status_code, 302)

        # Create ticket DPIG-2026-GCC-000009 assigned to zo5
        zo5_user = User.objects.get(username='zo5')
        complaint = Complaint.objects.create(
            cluster=cluster,
            zone=zone5,
            ward=ward59,
            department=dept,
            ticket_number="DPIG-2026-GCC-000009",
            title="Street Light Fused in Front of Plot / Residence",
            status="ASSIGNED",
            current_assignee=zo5_user,
            latitude=13.0827,
            longitude=80.2707,
        )

        # zo5 accesses dashboard: complaint is immediately visible
        resp = self.client.get('/officer/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['zone_filter'], '5')
        self.assertIn(complaint, resp.context['complaints'])

        # Detail view inspection by zo5
        detail_resp = self.client.get(f'/officer/complaint/{complaint.id}/')
        self.assertEqual(detail_resp.status_code, 200)

    def test_cross_zonal_filter_for_zo1(self):
        cluster = Cluster.objects.first() or Cluster.objects.create(name="GCC", code="GCC")
        zone1 = Zone.objects.create(cluster=cluster, number=1, name="Thiruvottiyur")
        zone5 = Zone.objects.create(cluster=cluster, number=5, name="Royapuram")
        ward1 = Ward.objects.create(zone=zone1, number=1, name="Ward 1")
        ward59 = Ward.objects.create(zone=zone5, number=59, name="Ward 59")
        dept = Department.objects.create(cluster=cluster, name="Electrical", code="LIGHTS")

        # Switch to zo1 (Zonal Officer - Local Level DL3)
        self.client.get('/switch-role/ZONAL_OFFICER/?next=/officer/')
        zo1_user = User.objects.get(username='zo1')

        c_z1 = Complaint.objects.create(
            cluster=cluster, zone=zone1, ward=ward1, department=dept,
            ticket_number="DPIG-2026-GCC-000010", title="Water Pipe Burst",
            status="ASSIGNED", current_assignee=zo1_user,
            latitude=13.1580, longitude=80.3012,
        )
        c_z5 = Complaint.objects.create(
            cluster=cluster, zone=zone5, ward=ward59, department=dept,
            ticket_number="DPIG-2026-GCC-000011", title="Streetlight Issue",
            status="ASSIGNED",
            latitude=13.0827, longitude=80.2707,
        )

        # 1. zo1 is a local Zonal Officer (DL3): strictly locked to Zone 1
        resp = self.client.get('/officer/')
        self.assertFalse(resp.context['is_corp_or_state_officer'])
        self.assertEqual(resp.context['zone_filter'], '1')
        self.assertIn(c_z1, resp.context['complaints'])
        self.assertNotIn(c_z5, resp.context['complaints'])

        # UI verification: Quick ZO switcher module must be removed
        self.assertNotContains(resp, 'Switch ZO:')
        # UI verification: Filter dropdown must not be available to local zonal officers
        self.assertNotContains(resp, '<select name="zone"')

        # Attempting ?zone=5 or ?zone=ALL by local officer is ignored/locked
        resp_z5 = self.client.get('/officer/?zone=5')
        self.assertEqual(resp_z5.context['zone_filter'], '1')
        self.assertNotIn(c_z5, resp_z5.context['complaints'])
        self.assertIn(c_z1, resp_z5.context['complaints'])

        resp_all = self.client.get('/officer/?zone=ALL')
        self.assertEqual(resp_all.context['zone_filter'], '1')
        self.assertNotIn(c_z5, resp_all.context['complaints'])
        self.assertIn(c_z1, resp_all.context['complaints'])

        # zo1 cannot access Zone 5 complaint detail (returns 403 Forbidden)
        forbidden_resp = self.client.get(f'/officer/complaint/{c_z5.id}/')
        self.assertEqual(forbidden_resp.status_code, 403)

        # 2. Corporation Level Officer (Commissioner): has citywide oversight and filter option
        self.client.get('/switch-role/COMMISSIONER/?next=/officer/')
        resp_comm = self.client.get('/officer/')
        self.assertTrue(resp_comm.context['is_corp_or_state_officer'])
        self.assertContains(resp_comm, '<select name="zone"')

        # Commissioner filters to Zone 5
        resp_comm_z5 = self.client.get('/officer/?zone=5')
        self.assertIn(c_z5, resp_comm_z5.context['complaints'])
        self.assertNotIn(c_z1, resp_comm_z5.context['complaints'])

        # Commissioner filters to ALL zones
        resp_comm_all = self.client.get('/officer/?zone=ALL')
        self.assertIn(c_z1, resp_comm_all.context['complaints'])
        self.assertIn(c_z5, resp_comm_all.context['complaints'])

        # Commissioner can access Zone 5 complaint detail
        comm_detail_resp = self.client.get(f'/officer/complaint/{c_z5.id}/')
        self.assertEqual(comm_detail_resp.status_code, 200)


class SequentialWorkflowEscalationTestCase(TestCase):
    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC_WF")
        self.zone = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.ward = Ward.objects.create(zone=self.zone, number=52, name="Basin Bridge")
        self.dept = Department.objects.create(cluster=self.cluster, code="ROADS", name="Roads")
        self.cat = GrievanceCategory.objects.create(
            cluster=self.cluster, department=self.dept, code="POTHOLE", name="Pothole Repair", sla_hours=24
        )

        # Create officers across all 7 levels
        self.dl1_user = User.objects.create_user('dl1_officer', 'dl1@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.dl1_user, cluster=self.cluster, role='WARD_OFFICER',
            hierarchy_level=1, zone=self.zone, department=self.dept
        )

        self.dl2_user = User.objects.create_user('dl2_officer', 'dl2@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.dl2_user, cluster=self.cluster, role='WARD_OFFICER',
            hierarchy_level=2, zone=self.zone, department=self.dept
        )

        self.dl3_user = User.objects.create_user('dl3_officer', 'dl3@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.dl3_user, cluster=self.cluster, role='ZONAL_OFFICER',
            hierarchy_level=3, zone=self.zone
        )

        self.cl1_user = User.objects.create_user('cl1_officer', 'cl1@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.cl1_user, cluster=self.cluster, role='COMMISSIONER',
            hierarchy_level=4, department=self.dept
        )

        self.cl2_user = User.objects.create_user('cl2_officer', 'cl2@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.cl2_user, cluster=self.cluster, role='COMMISSIONER',
            hierarchy_level=5
        )

        self.cl3_user = User.objects.create_user('cl3_officer', 'cl3@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.cl3_user, cluster=self.cluster, role='COMMISSIONER',
            hierarchy_level=6
        )

        self.cm_user = User.objects.create_user('cm_officer', 'cm@test.gov', 'pass')
        UserProfile.objects.create(
            user=self.cm_user, cluster=self.cluster, role='CM_OFFICE',
            hierarchy_level=7
        )

    def test_sequential_escalation_chain_complete(self):
        complaint = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            ticket_number="GCC-WF-TEST-001", title="Test Road Cave-in", description="Road surface caved in",
            latitude=13.0827, longitude=80.2707, status="ASSIGNED",
            current_level="DL1", escalated_to_level=1, current_assignee=self.dl1_user
        )

        expected_levels = ['DL2', 'DL3', 'CL1', 'CL2', 'CL3', 'CM_OFFICE']
        expected_assignees = [
            self.dl2_user, self.dl3_user, self.cl1_user, self.cl2_user, self.cl3_user, self.cm_user
        ]

        for next_lvl, expected_user in zip(expected_levels, expected_assignees):
            escalated = complaint.escalate_to_next_level(reason=f"Escalating to {next_lvl}")
            self.assertTrue(escalated)
            self.assertEqual(complaint.current_level, next_lvl)
            self.assertEqual(complaint.current_assignee, expected_user)
            self.assertFalse(complaint.is_sla_breached)
            self.assertGreater(complaint.sla_deadline, timezone.now())

        # Attempt to escalate past CM_OFFICE (Apex level)
        further_escalated = complaint.escalate_to_next_level(reason="Beyond CM Office")
        self.assertFalse(further_escalated)
        self.assertEqual(complaint.current_level, "CM_OFFICE")

    def test_citizen_reopen_escalates_to_next_level(self):
        complaint = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            ticket_number="GCC-WF-REOPEN", title="Unfixed water leakage", description="Leaking pipe",
            latitude=13.0827, longitude=80.2707, status="RESOLVED",
            current_level="DL1", escalated_to_level=1, current_assignee=self.dl1_user
        )

        resp = self.client.post(
            f'/track/{complaint.ticket_number}/',
            {'action': 'reopen', 'reopen_reason': 'Still leaking water'}
        )
        self.assertEqual(resp.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.current_level, 'DL2')
        self.assertEqual(complaint.status, 'REOPENED')
        self.assertEqual(complaint.current_assignee, self.dl2_user)

    def test_sla_watchdog_auto_escalation(self):
        # Create an overdue ticket at DL1
        past_time = timezone.now() - timedelta(hours=2)
        complaint = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            ticket_number="GCC-WF-OVERDUE", title="Overdue grievance", description="Past SLA",
            latitude=13.0827, longitude=80.2707, status="ASSIGNED",
            current_level="DL1", escalated_to_level=1, current_assignee=self.dl1_user,
            sla_deadline=past_time
        )

        monitor_sla_deadlines_task()
        complaint.refresh_from_db()
        self.assertEqual(complaint.current_level, 'DL2')
        self.assertEqual(complaint.current_assignee, self.dl2_user)
        self.assertEqual(complaint.status, 'ESCALATED')

    def test_citizen_intake_workflow_zone_and_dl1_assignment(self):
        # Authenticate as a verified registered citizen
        citizen = User.objects.create_user('ravi_citizen', 'ravi@citizen.org', 'pass')
        UserProfile.objects.create(
            user=citizen, cluster=self.cluster, role='CITIZEN',
            is_aadhaar_verified=True, aadhaar_last4='2233'
        )
        self.client.force_login(citizen)

        # Citizen files complaint selecting Zone 5 and category POTHOLE (Roads)
        resp = self.client.post('/complaint/new/', {
            'title': 'Dangerous road pothole',
            'description': 'Heavy pothole near junction causing accidents',
            'citizen_name': 'Ravi Citizen',
            'citizen_email': 'ravi@citizen.org',
            'citizen_phone': '9840112233',
            'zone': self.zone.id,
            'ward': self.ward.id,
            'category': self.cat.id,
            'latitude': 13.0827,
            'longitude': 80.2707,
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        complaint = Complaint.objects.get(title='Dangerous road pothole')
        self.assertEqual(complaint.citizen, citizen)
        self.assertEqual(complaint.zone, self.zone)
        self.assertEqual(complaint.department, self.dept)
        self.assertEqual(complaint.current_level, 'DL1')
        self.assertEqual(complaint.escalated_to_level, 1)
        self.assertEqual(complaint.current_assignee, self.dl1_user)
        self.assertEqual(complaint.status, 'ASSIGNED')
        self.assertGreater(complaint.sla_deadline, timezone.now())


class OfficerBulkUploadTestCase(TestCase):
    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC_BULK")
        self.zone5 = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.dept = Department.objects.create(cluster=self.cluster, code="ROADS", name="Roads")

        # Superadmin
        self.superadmin = User.objects.create_superuser('superadmin_bulk', 'admin@bulk.gov', 'pass')
        UserProfile.objects.create(user=self.superadmin, cluster=self.cluster, role='SUPERADMIN')

    def test_template_export_csv_and_xlsx(self):
        csv_bytes, mime_csv, filename_csv = export_officer_template('csv')
        self.assertGreater(len(csv_bytes), 100)
        self.assertIn('text/csv', mime_csv)

        xlsx_bytes, mime_xlsx, filename_xlsx = export_officer_template('xlsx')
        self.assertGreater(len(xlsx_bytes), 100)
        self.assertIn('spreadsheetml', mime_xlsx)

    def test_parse_and_provision_dataframe(self):
        df = generate_officer_template_dataframe()
        result = parse_and_provision_officers(df, cluster=self.cluster, update_existing=True)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertGreaterEqual(result['created_count'], 5)

        # Verify provisioned users exist
        zo5 = User.objects.get(username='dl3_ee_zo5')
        self.assertEqual(zo5.profile.role, 'ZONAL_OFFICER')
        self.assertEqual(zo5.profile.hierarchy_level, 3)

        cm = User.objects.get(username='cm_special_cell')
        self.assertEqual(cm.profile.role, 'CM_OFFICE')
        self.assertEqual(cm.profile.hierarchy_level, 7)

    def test_superadmin_download_template_view(self):
        self.client.force_login(self.superadmin)
        resp_csv = self.client.get('/superadmin/staff/download-template/?format=csv')
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn('text/csv', resp_csv['Content-Type'])

        resp_xlsx = self.client.get('/superadmin/staff/download-template/?format=xlsx')
        self.assertEqual(resp_xlsx.status_code, 200)
        self.assertIn('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', resp_xlsx['Content-Type'])

    def test_superadmin_bulk_upload_post_view(self):
        self.client.force_login(self.superadmin)
        csv_content = (
            "Username,Full_Name,Email,Phone,Role,Workflow_Level,Zone_Number,Ward_Number,Department_Code,Designation,Password\n"
            "bulk_dl1_test,Bulk DL1 Officer,bulk_dl1@test.gov,9840111111,WARD_OFFICER,DL1,5,,ROADS,DL1 Roads Eng,Admin@Dpig2026\n"
        ).encode('utf-8')
        uploaded = SimpleUploadedFile("officers.csv", csv_content, content_type="text/csv")

        resp = self.client.post('/superadmin/staff/bulk-upload/', {'template_file': uploaded}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(username='bulk_dl1_test').exists())
        u = User.objects.get(username='bulk_dl1_test')
        self.assertEqual(u.profile.hierarchy_level, 1)


class DepartmentAdminTestCase(TestCase):
    """Tests for Departmental Admin provisioning, department-scoped user management, and time-based alerts & schemes."""

    def setUp(self):
        from core.dept_admin_service import ensure_department_admins
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC_DEPT")
        self.zone5 = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.ward52 = Ward.objects.create(zone=self.zone5, number=52, name="Harbour")

        self.dept_roads = Department.objects.create(cluster=self.cluster, code="ROADS", name="Roads, Bridges & Footpaths")
        self.dept_swm = Department.objects.create(cluster=self.cluster, code="SWM", name="Solid Waste Management")
        self.dept_health = Department.objects.create(cluster=self.cluster, code="HEALTH", name="Public Health & Vector Control")

        # Provision department admins for all departments
        self.admins_info = ensure_department_admins(self.cluster)
        self.roads_admin_user = User.objects.get(username="deptadmin.roads")
        self.swm_admin_user = User.objects.get(username="deptadmin.swm")

    def test_ensure_department_admins_for_all_departments(self):
        """Verifies that exactly one Department Admin is created for every department."""
        self.assertEqual(len(self.admins_info), 3)

        # Check ROADS Admin
        self.assertEqual(self.roads_admin_user.profile.role, 'DEPT_ADMIN')
        self.assertEqual(self.roads_admin_user.profile.department, self.dept_roads)
        self.assertEqual(self.roads_admin_user.profile.hierarchy_level, 4)
        self.assertTrue(self.roads_admin_user.is_staff)

        # Check SWM Admin
        self.assertEqual(self.swm_admin_user.profile.role, 'DEPT_ADMIN')
        self.assertEqual(self.swm_admin_user.profile.department, self.dept_swm)

        # Check HEALTH Admin
        health_admin = User.objects.get(username="deptadmin.health")
        self.assertEqual(health_admin.profile.role, 'DEPT_ADMIN')
        self.assertEqual(health_admin.profile.department, self.dept_health)

    def test_dept_admin_can_add_user_for_own_department(self):
        """Verifies that Department Admin can add users for their department and department is locked."""
        self.client.force_login(self.roads_admin_user)

        # Access Staff Management page
        resp = self.client.get('/dept-admin/staff/')
        self.assertEqual(resp.status_code, 200)

        # Add an officer to ROADS department
        post_data = {
            'action': 'add_staff',
            'full_name': 'K. Ramanathan AE',
            'username': 'ae_roads_z5_test',
            'email': 'ae.roads@chennaicorp.gov.in',
            'phone': '9840112233',
            'role': 'WARD_OFFICER',
            'hierarchy_level': '1',
            'zone_id': self.zone5.id,
            'ward_id': self.ward52.id,
            'designation': 'Assistant Engineer - Roads',
            'password': 'Admin@Dpig2026',
            # Attempt to forge a different department id
            'department_id': self.dept_swm.id,
        }
        post_resp = self.client.post('/dept-admin/staff/', post_data, follow=True)
        self.assertEqual(post_resp.status_code, 200)

        # Verify officer was created
        self.assertTrue(User.objects.filter(username='ae_roads_z5_test').exists())
        new_officer = User.objects.get(username='ae_roads_z5_test')
        self.assertEqual(new_officer.first_name, 'K. Ramanathan AE')
        # Crucial: department MUST be ROADS, not the forged SWM!
        self.assertEqual(new_officer.profile.department, self.dept_roads)
        self.assertEqual(new_officer.profile.hierarchy_level, 1)
        self.assertEqual(new_officer.profile.zone, self.zone5)

    def test_dept_admin_cannot_modify_staff_from_other_department(self):
        """Verifies that Department Admin cannot edit staff belonging to another department."""
        # Create an officer in SWM
        swm_staff = User.objects.create_user(username="swm_inspector_test", password="pass")
        swm_profile = UserProfile.objects.create(
            user=swm_staff,
            cluster=self.cluster,
            role="FIELD_STAFF",
            department=self.dept_swm,
            hierarchy_level=1
        )

        # Roads admin tries to edit SWM officer
        self.client.force_login(self.roads_admin_user)
        resp = self.client.post('/dept-admin/staff/', {
            'action': 'edit_staff',
            'staff_id': swm_profile.id,
            'designation': 'Hacked Designation',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        swm_profile.refresh_from_db()
        self.assertNotEqual(swm_profile.designation, 'Hacked Designation')

    def test_dept_admin_create_and_update_time_based_alert(self):
        """Verifies Department Admin can create and update time-based alerts with live validity checks."""
        self.client.force_login(self.roads_admin_user)

        now = timezone.now()
        yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')

        # Create active time-based alert
        resp = self.client.post('/dept-admin/alerts/', {
            'action': 'create_alert',
            'title': 'Emergency Bridge Repair on Anna Salai',
            'content': 'Traffic diversion in place due to essential bridge slab repair work.',
            'priority': 'EMERGENCY',
            'target_audience': 'Commuters & Residents',
            'valid_from': yesterday_str,
            'valid_until': tomorrow_str,
            'is_active': 'on',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        alert = GovernmentBroadcast.objects.get(title='Emergency Bridge Repair on Anna Salai')
        self.assertEqual(alert.broadcast_type, 'ALERT')
        self.assertEqual(alert.department, self.dept_roads)
        self.assertEqual(alert.priority, 'EMERGENCY')
        self.assertTrue(alert.is_currently_active)
        self.assertEqual(alert.time_status, 'ACTIVE')
        self.assertIn(alert, GovernmentBroadcast.objects.active())

        # Test Update Alert
        edit_resp = self.client.post('/dept-admin/alerts/', {
            'action': 'edit_alert',
            'alert_id': alert.id,
            'title': 'Updated Emergency Bridge Repair on Anna Salai',
            'content': 'Bridge slab repair 80% complete. Single lane now open.',
            'priority': 'HIGH',
            'target_audience': 'All Commuters',
            'valid_from': yesterday_str,
            'valid_until': tomorrow_str,
            'is_active': 'on',
        }, follow=True)
        self.assertEqual(edit_resp.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.title, 'Updated Emergency Bridge Repair on Anna Salai')
        self.assertEqual(alert.priority, 'HIGH')

        # Test Expired Alert
        past_str = (now - timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        alert.valid_until = now - timedelta(hours=1)
        alert.save()
        self.assertFalse(alert.is_currently_active)
        self.assertEqual(alert.time_status, 'EXPIRED')
        self.assertNotIn(alert, GovernmentBroadcast.objects.active())

        # Test Scheduled Future Alert
        alert.valid_from = now + timedelta(days=2)
        alert.valid_until = now + timedelta(days=5)
        alert.save()
        self.assertFalse(alert.is_currently_active)
        self.assertEqual(alert.time_status, 'SCHEDULED')
        self.assertNotIn(alert, GovernmentBroadcast.objects.active())

    def test_dept_admin_create_and_update_time_based_welfare_scheme(self):
        """Verifies Department Admin can create and update time-based welfare schemes with benefits & eligibility."""
        self.client.force_login(self.roads_admin_user)

        now = timezone.now()
        yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        future_deadline_str = (now + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M')

        # Create scheme
        resp = self.client.post('/dept-admin/schemes/', {
            'action': 'create_scheme',
            'title': 'Green Footpath Adoption & Tree Planting Incentive Scheme 2026',
            'content': 'Citizen and resident welfare association incentive for adopting arterial footpaths.',
            'eligibility_criteria': 'Registered RWAs and commercial establishments along arterial roads.',
            'benefits': 'Municipal certificate of honor and ₹25,000 annual maintenance honorarium.',
            'target_audience': 'Resident Welfare Associations',
            'scheme_url': 'https://chennaicorporation.gov.in/schemes/green-footpath',
            'valid_from': yesterday_str,
            'valid_until': future_deadline_str,
            'is_active': 'on',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        scheme = GovernmentBroadcast.objects.get(title='Green Footpath Adoption & Tree Planting Incentive Scheme 2026')
        self.assertEqual(scheme.broadcast_type, 'WELFARE_SCHEME')
        self.assertEqual(scheme.department, self.dept_roads)
        self.assertTrue(scheme.is_currently_active)
        self.assertEqual(scheme.time_status, 'ACTIVE')
        self.assertIn('₹25,000', scheme.benefits)
        self.assertIn('Registered RWAs', scheme.eligibility_criteria)

        # Test Citizen Hub renders active scheme
        client_anon = Client()
        hub_resp = client_anon.get('/citizen/')
        self.assertEqual(hub_resp.status_code, 200)
        self.assertContains(hub_resp, 'Green Footpath Adoption')
        self.assertContains(hub_resp, 'ROADS')


class PolicymakerPlannedWorkTestCase(TestCase):
    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC_PW")
        self.zone5 = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.ward59 = Ward.objects.create(zone=self.zone5, number=59, name="Ward 59")
        self.ward142 = Ward.objects.create(zone=self.zone5, number=142, name="Ward 142")

        # Policymaker for Ward 142
        self.pm_user = User.objects.create_user(
            username="pm.ward142",
            password="Admin@Dpig2026"
        )
        self.pm_profile = UserProfile.objects.create(
            user=self.pm_user,
            cluster=self.cluster,
            role="POLICYMAKER",
            zone=self.zone5,
            ward=self.ward142,
            designation="Ward 142 Councillor / Strategic Planner"
        )

        # Capital Project in Ward 142
        self.project_w142 = CapitalProjectRecommendation.objects.create(
            cluster=self.cluster,
            title="Ward 142 Arterial Stormwater Trunk Overhaul",
            sector="Drainage",
            affected_zones=[5],
            affected_wards=[142],
            problem_statement="Chronic waterlogging along Ward 142 commercial junctions.",
            proposed_solution="Construct reinforced RCC drain interconnection.",
            estimated_budget_inr=15000000.00,
            priority_score=92.5,
            ai_rationale="High flood risk and high commuter density.",
            status="PROPOSED"
        )

        self.client = Client()

    def test_sanction_work_renamed_to_planned_work(self):
        """Verifies button is renamed from 'Sanction Work' to 'Planned Work'."""
        self.client.force_login(self.pm_user)
        resp = self.client.get('/policymaker/')
        self.assertEqual(resp.status_code, 200)

        # Button should be 'Planned Work'
        self.assertContains(resp, 'Planned Work')
        # 'Sanction Work' should NOT be present anywhere in the template
        self.assertNotContains(resp, 'Sanction Work')
        # Download Planned Work button should be visible
        self.assertContains(resp, 'Download Planned Work')

    def test_click_planned_work_adds_to_planned_list(self):
        """Clicking Planned Work adds proposal to the Planned Work list."""
        self.client.force_login(self.pm_user)
        self.assertFalse(self.project_w142.is_planned)

        # POST to toggle planned work
        resp = self.client.post(f'/policymaker/project/{self.project_w142.id}/plan/', follow=True)
        self.assertEqual(resp.status_code, 200)

        self.project_w142.refresh_from_db()
        self.assertTrue(self.project_w142.is_planned)
        self.assertEqual(self.project_w142.status, 'PLANNED')
        self.assertEqual(self.project_w142.planned_by, self.pm_user)
        self.assertIsNotNone(self.project_w142.planned_at)

        # In Planned Work list tab, project is listed with Planned Work status
        planned_tab_resp = self.client.get('/policymaker/?tab=planned')
        self.assertEqual(planned_tab_resp.status_code, 200)
        self.assertIn(self.project_w142, planned_tab_resp.context['recommendations'])
        self.assertContains(planned_tab_resp, 'Status: Planned Work')

    def test_download_planned_work_csv_and_excel(self):
        """Verifies Planned Work list can be downloaded as CSV and Excel spreadsheet."""
        self.client.force_login(self.pm_user)
        self.project_w142.mark_as_planned(user=self.pm_user)

        # 1. Download CSV
        csv_resp = self.client.get('/policymaker/planned-work/download/?format=csv')
        self.assertEqual(csv_resp.status_code, 200)
        self.assertEqual(csv_resp.headers['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="Planned_Work_List_', csv_resp.headers['Content-Disposition'])

        csv_content = csv_resp.content.decode('utf-8')
        self.assertIn('Ward 142 Arterial Stormwater Trunk Overhaul', csv_content)
        self.assertIn('15000000.00', csv_content)
        self.assertIn('Planned Work', csv_content)

        # 2. Download Excel (.xlsx)
        xlsx_resp = self.client.get('/policymaker/planned-work/download/?format=xlsx')
        self.assertEqual(xlsx_resp.status_code, 200)
        self.assertEqual(xlsx_resp.headers['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', xlsx_resp.headers['Content-Disposition'])
        self.assertGreater(len(xlsx_resp.content), 1000)


class TicketNumberFormatTestCase(TestCase):
    """
    Tests for the standardized ticket ID format: DPIG-YYYY-LLL-NNNNNN
    Verifies:
    1. Correct regex pattern: DPIG-YYYY-LLL-NNNNNN
    2. Sequential numbering (000001, 000002, ...)
    3. Counter resets to 000001 every new year
    4. Handles multiple clusters independently
    5. Automatic ticket number assignment on Complaint creation
    """
    def setUp(self):
        self.cluster_gcc = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC")
        self.cluster_mdu = Cluster.objects.create(name="Madurai Corporation", code="MDU")
        self.zone = Zone.objects.create(cluster=self.cluster_gcc, number=1, name="Zone 1")
        self.ward = Ward.objects.create(zone=self.zone, number=1, name="Ward 1")
        self.dept = Department.objects.create(cluster=self.cluster_gcc, name="Roads", code="ROADS")

    def test_ticket_format_and_sequence(self):
        # 1. First ticket generated for GCC in year 2026 starts at 000001
        t1 = generate_ticket_number(cluster=self.cluster_gcc, year=2026)
        self.assertEqual(t1, "DPIG-2026-GCC-000001")
        self.assertRegex(t1, r"^DPIG-\d{4}-[A-Z0-9]+-\d{6}$")

        # 2. Second ticket generated for GCC in year 2026 is sequential (000002)
        t2 = generate_ticket_number(cluster=self.cluster_gcc, year=2026)
        self.assertEqual(t2, "DPIG-2026-GCC-000002")

        # 3. Independent cluster (MDU) starts from 000001
        t_mdu = generate_ticket_number(cluster=self.cluster_mdu, year=2026)
        self.assertEqual(t_mdu, "DPIG-2026-MDU-000001")

        # 4. New calendar year (2027) resets counter back to 000001
        t_2027 = generate_ticket_number(cluster=self.cluster_gcc, year=2027)
        self.assertEqual(t_2027, "DPIG-2027-GCC-000001")

        # 5. Subsequent ticket in 2027 continues sequentially (000002)
        t_2027_2 = generate_ticket_number(cluster=self.cluster_gcc, year=2027)
        self.assertEqual(t_2027_2, "DPIG-2027-GCC-000002")

    def test_complaint_auto_generates_standard_ticket(self):
        year = timezone.now().year
        complaint = Complaint.objects.create(
            cluster=self.cluster_gcc,
            zone=self.zone,
            ward=self.ward,
            department=self.dept,
            title="Pothole repair needed",
            description="Large pothole on main road",
            latitude=13.0827,
            longitude=80.2707,
        )
        self.assertRegex(complaint.ticket_number, rf"^DPIG-{year}-GCC-\d{{6}}$")
        self.assertTrue(complaint.ticket_number.endswith("000001"))


class AuditorRoleAndComplianceTestCase(TestCase):
    """
    Comprehensive tests for the AUDITOR role:
    1. Role hierarchy, label, and permissions (can_access_auditor_console).
    2. 1-Click Role Switcher (/switch-role/AUDITOR/) and dashboard access (/auditor/).
    3. Unauthorized access denial (e.g. Citizen denied with HTTP 403).
    4. Statewide complaint oversight without zonal restriction.
    5. Auditor grievance inspection view (/auditor/complaint/<id>/) with SHA-256 block ledger.
    6. Recording audit determinations, observations, and structured AuditFindings.
    7. Cryptographic append-only log entry on audit determination.
    8. System-wide cryptographic integrity scan API (/auditor/integrity-scan/).
    9. Statutory audit report export (CSV and Excel).
    10. Bulk officer upload supporting the AUDITOR role.
    """
    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC")
        self.zone1 = Zone.objects.create(cluster=self.cluster, number=1, name="Thiruvottiyur")
        self.zone5 = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.ward1 = Ward.objects.create(zone=self.zone1, number=1, name="Ward 1")
        self.ward52 = Ward.objects.create(zone=self.zone5, number=52, name="Ward 52")
        self.dept = Department.objects.create(cluster=self.cluster, name="Roads & Bridges", code="ROADS")
        self.cat = GrievanceCategory.objects.create(cluster=self.cluster, department=self.dept, name="Pothole", code="POTHOLE", sla_hours=24)

        # Auditor User
        self.auditor_user = User.objects.create_user(username="test_auditor", password="Password@123", first_name="Auditor")
        self.auditor_user.is_staff = True
        self.auditor_user.save()
        self.auditor_profile = UserProfile.objects.create(
            user=self.auditor_user,
            cluster=self.cluster,
            role="AUDITOR",
            designation="Statutory Compliance Auditor",
            hierarchy_level=5
        )

        # Citizen User
        self.citizen_user = User.objects.create_user(username="test_citizen", password="Password@123", first_name="Citizen")
        self.citizen_profile = UserProfile.objects.create(
            user=self.citizen_user,
            cluster=self.cluster,
            role="CITIZEN",
            is_aadhaar_verified=True
        )

        # Sample Grievance in Zone 5
        self.complaint = Complaint.objects.create(
            cluster=self.cluster,
            zone=self.zone5,
            ward=self.ward52,
            department=self.dept,
            category=self.cat,
            citizen_name="Grievant Resident",
            title="Dangerous crater on Kamarajar Salai",
            description="Deep crater posing severe road hazard.",
            latitude=13.0827,
            longitude=80.2707,
            status="RESOLVED",
            resolution_notes="Temporarily patched with gravel mix."
        )

    def test_auditor_role_attributes_and_permissions(self):
        # 1. Hierarchy label
        self.assertEqual(self.auditor_profile.hierarchy_label, "Statutory / Compliance Auditor")

        # 2. Permissions check
        self.assertTrue(can_access_auditor_console(self.auditor_user))
        self.assertFalse(can_access_auditor_console(self.citizen_user))

        # 3. Statewide access across any zone/ward
        self.assertTrue(can_access_complaint(self.auditor_user, self.complaint))

    def test_switch_role_and_dashboard_access(self):
        # Switch to AUDITOR role via 1-click switcher
        resp = self.client.get('/switch-role/AUDITOR/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/auditor/')

        # Access Auditor Dashboard
        dash_resp = self.client.get('/auditor/')
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "Statutory Audit & Policy Compliance Hub")
        self.assertIn(self.complaint, dash_resp.context['complaints'])

        # Citizen denied access (HTTP 403)
        self.client.force_login(self.citizen_user)
        citizen_resp = self.client.get('/auditor/')
        self.assertEqual(citizen_resp.status_code, 403)

    def test_auditor_complaint_inspection_and_recording(self):
        self.client.force_login(self.auditor_user)

        # Inspect complaint detail
        detail_resp = self.client.get(f'/auditor/complaint/{self.complaint.id}/')
        self.assertEqual(detail_resp.status_code, 200)
        self.assertTrue(detail_resp.context['all_blocks_valid'])
        self.assertGreaterEqual(detail_resp.context['total_blocks'], 1)

        # Record non-compliance finding (missing mandatory photo proof)
        post_data = {
            'audit_status': 'FLAGGED_NON_COMPLIANT',
            'audit_notes': 'Violation of Resolution Evidence Policy: Resolved without photographic proof.',
            'create_finding': '1',
            'finding_category': 'MISSING_PROOF',
            'finding_severity': 'HIGH',
            'action_required': 'Ward AE must upload photographic proof of road resurfacing.'
        }
        action_resp = self.client.post(f'/auditor/complaint/{self.complaint.id}/action/', post_data)
        self.assertEqual(action_resp.status_code, 302)

        # Verify Complaint updated
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.audit_status, 'FLAGGED_NON_COMPLIANT')
        self.assertIn("Violation of Resolution Evidence Policy", self.complaint.audit_notes)
        self.assertEqual(self.complaint.audited_by, self.auditor_user)
        self.assertIsNotNone(self.complaint.audited_at)

        # Verify AuditFinding record created
        finding = self.complaint.audit_findings.first()
        self.assertIsNotNone(finding)
        self.assertEqual(finding.category, 'MISSING_PROOF')
        self.assertEqual(finding.severity, 'HIGH')
        self.assertEqual(finding.auditor, self.auditor_user)

        # Verify immutable cryptographic block appended to SHA-256 ledger
        latest_block = self.complaint.audit_logs.order_by('-id').first()
        self.assertEqual(latest_block.action, "AUDIT_INSPECTION_RECORDED")
        self.assertEqual(latest_block.actor_role, "AUDITOR")
        self.assertTrue(latest_block.verify_integrity())

    def test_system_wide_cryptographic_scan(self):
        self.client.force_login(self.auditor_user)
        scan_resp = self.client.get('/auditor/integrity-scan/')
        self.assertEqual(scan_resp.status_code, 200)
        data = scan_resp.json()
        self.assertEqual(data['status'], 'SUCCESS')
        self.assertTrue(data['is_system_clean'])
        self.assertGreaterEqual(data['total_blocks_scanned'], 1)
        self.assertEqual(data['tampered_blocks'], 0)

    def test_export_statutory_audit_reports(self):
        self.client.force_login(self.auditor_user)

        # 1. CSV Export
        csv_resp = self.client.get('/auditor/export/?format=csv')
        self.assertEqual(csv_resp.status_code, 200)
        self.assertEqual(csv_resp.headers['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="DPIG_Statutory_Audit_Report_', csv_resp.headers['Content-Disposition'])
        csv_content = csv_resp.content.decode('utf-8')
        self.assertIn(self.complaint.ticket_number, csv_content)

        # 2. Excel (.xlsx) Export
        xlsx_resp = self.client.get('/auditor/export/?format=xlsx')
        self.assertEqual(xlsx_resp.status_code, 200)
        self.assertEqual(xlsx_resp.headers['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', xlsx_resp.headers['Content-Disposition'])
        self.assertGreater(len(xlsx_resp.content), 1000)

    def test_bulk_provisioning_with_auditor_role(self):
        df_officers = pd.DataFrame([
            {
                'Username': 'auditor_chennai_north',
                'FullName': 'Tmt. Anitha Kumar',
                'Email': 'anitha.kumar@tn.gov.in',
                'MobileNumber': '9840188888',
                'Workflow_Level': 'CL2',
                'Role': 'AUDITOR',
                'Department_Code': '',
                'Zone_Number': '',
                'Ward_Number': '',
                'Designation': 'North Regional Statutory Auditor',
                'Password': 'Admin@Dpig2026',
            }
        ])
        buffer = io.BytesIO()
        df_officers.to_excel(buffer, index=False)
        buffer.seek(0)
        file_obj = SimpleUploadedFile("auditor_upload.xlsx", buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        result = parse_and_provision_officers(file_obj, cluster=self.cluster)
        self.assertEqual(result['created_count'], 1)
        self.assertEqual(len(result['errors']), 0)

        created_user = User.objects.get(username='auditor_chennai_north')
        self.assertEqual(created_user.profile.role, 'AUDITOR')
        self.assertTrue(can_access_auditor_console(created_user))


class RegisteredCitizenGrievanceAccessTestCase(TestCase):
    """
    Test suite verifying that ONLY registered citizens can register civic grievances.
    Anonymous visitors and administrative/staff roles (Officers, Policymakers, Dept Admins,
    Auditors, SuperAdmins) are strictly barred.
    """
    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC_CITIZEN_GATE")
        self.zone = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.ward = Ward.objects.create(zone=self.zone, number=52, name="Royapuram North")
        self.dept = Department.objects.create(cluster=self.cluster, code="ROADS", name="Roads Dept", standard_sla_hours=24)
        self.cat = GrievanceCategory.objects.create(cluster=self.cluster, department=self.dept, name="Pothole", sla_hours=24)

        # DL1 Officer
        self.dl1_user = User.objects.create_user('dl1_officer_gate', 'dl1@gate.gov', 'pass')
        UserProfile.objects.create(
            user=self.dl1_user, cluster=self.cluster, role='WARD_OFFICER',
            hierarchy_level=1, zone=self.zone, ward=self.ward, department=self.dept
        )

        # Registered Citizen
        self.citizen_user = User.objects.create_user('citizen_anand', 'anand@citizen.org', 'pass', first_name='Anand')
        self.citizen_profile = UserProfile.objects.create(
            user=self.citizen_user, cluster=self.cluster, role='CITIZEN',
            is_aadhaar_verified=True, aadhaar_last4='4321', phone='9840155555'
        )

        # Department Admin
        self.dept_admin_user = User.objects.create_user('deptadmin_roads_gate', 'admin@roads.gov', 'pass')
        UserProfile.objects.create(
            user=self.dept_admin_user, cluster=self.cluster, role='DEPT_ADMIN',
            department=self.dept, hierarchy_level=4
        )

        # Policymaker
        self.policymaker_user = User.objects.create_user('policymaker_gate', 'policy@gate.gov', 'pass')
        UserProfile.objects.create(
            user=self.policymaker_user, cluster=self.cluster, role='POLICYMAKER',
            zone=self.zone, hierarchy_level=1
        )

        # Auditor
        self.auditor_user = User.objects.create_user('auditor_gate', 'auditor@gate.gov', 'pass')
        UserProfile.objects.create(
            user=self.auditor_user, cluster=self.cluster, role='AUDITOR', hierarchy_level=5
        )

        # Superadmin
        self.superadmin = User.objects.create_superuser('superadmin_gate', 'admin@gate.gov', 'pass')
        UserProfile.objects.create(user=self.superadmin, cluster=self.cluster, role='SUPERADMIN')

    def test_anonymous_user_cannot_access_or_submit_grievance(self):
        """Unauthenticated visitors must be redirected to citizen login with ?next=/complaint/new/"""
        # GET access
        resp_get = self.client.get('/complaint/new/')
        self.assertEqual(resp_get.status_code, 302)
        self.assertIn('/citizen/login/', resp_get.url)
        self.assertIn('next=/complaint/new/', resp_get.url)

        # POST submission
        initial_count = Complaint.objects.count()
        resp_post = self.client.post('/complaint/new/', {
            'title': 'Unauthorized guest complaint',
            'description': 'Attempting anonymous registration',
            'latitude': 13.0827,
            'longitude': 80.2707,
            'zone': self.zone.id,
            'ward': self.ward.id,
            'category': self.cat.id,
        })
        self.assertEqual(resp_post.status_code, 302)
        self.assertIn('/citizen/login/', resp_post.url)
        self.assertIn('next=/complaint/new/', resp_post.url)
        self.assertEqual(Complaint.objects.count(), initial_count, "No complaint should be created by anonymous visitor")

    def test_officers_and_staff_cannot_register_grievances(self):
        """Municipal staff and officers must be blocked from filing complaints and routed to their consoles."""
        staff_roles = [
            (self.dl1_user, '/officer/'),
            (self.dept_admin_user, '/dept-admin/'),
            (self.policymaker_user, '/policymaker/'),
            (self.auditor_user, '/auditor/'),
            (self.superadmin, '/superadmin/matrix/'),
        ]

        for user, expected_dashboard in staff_roles:
            self.client.force_login(user)

            # GET should redirect to their console
            resp = self.client.get('/complaint/new/')
            self.assertEqual(resp.status_code, 302, f"Staff {user.username} should be redirected")
            self.assertIn(expected_dashboard, resp.url, f"Staff {user.username} should land at {expected_dashboard}")

            # POST should not create a complaint
            count_before = Complaint.objects.count()
            post_resp = self.client.post('/complaint/new/', {
                'title': f'Staff rogue ticket by {user.username}',
                'description': 'Should not be allowed',
                'zone': self.zone.id,
                'ward': self.ward.id,
                'category': self.cat.id,
            })
            self.assertEqual(post_resp.status_code, 302)
            self.assertEqual(Complaint.objects.count(), count_before, f"Staff {user.username} must not create complaints")

    def test_registered_citizen_can_access_and_submit_grievance(self):
        """Authenticated registered citizens must successfully view form and register grievances."""
        self.client.force_login(self.citizen_user)

        # GET form
        resp_get = self.client.get('/complaint/new/')
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Registered Citizen Complainant")
        self.assertContains(resp_get, "UIDAI KYC Bound")

        # POST registration
        resp_post = self.client.post('/complaint/new/', {
            'title': 'Clogged stormwater drain',
            'description': 'Water stagnant on roadside near market',
            'citizen_name': 'Anand Citizen',
            'citizen_email': 'anand@citizen.org',
            'citizen_phone': '9840155555',
            'zone': self.zone.id,
            'ward': self.ward.id,
            'category': self.cat.id,
            'latitude': 13.0827,
            'longitude': 80.2707,
        }, follow=True)

        self.assertEqual(resp_post.status_code, 200)
        complaint = Complaint.objects.get(title='Clogged stormwater drain')
        self.assertEqual(complaint.citizen, self.citizen_user)
        self.assertTrue(complaint.is_aadhaar_verified)
        self.assertEqual(complaint.aadhaar_last4, '4321')
        self.assertEqual(complaint.current_level, 'DL1')
        self.assertEqual(complaint.current_assignee, self.dl1_user)

        # Verify Genesis audit block actor_role
        genesis_block = complaint.audit_logs.filter(action="CREATED").first()
        self.assertIsNotNone(genesis_block)
        self.assertEqual(genesis_block.actor_role, "CITIZEN")
        self.assertEqual(genesis_block.performed_by, self.citizen_user)

    def test_citizen_login_next_redirect_to_complaint_form(self):
        """Citizen signing in with ?next=/complaint/new/ must be routed straight to filing form."""
        # Using password mode
        resp = self.client.post('/citizen/login/', {
            'login_type': 'password',
            'identifier': self.citizen_user.username,
            'password': 'pass',
            'next': '/complaint/new/',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/complaint/new/')

    def test_ajax_rejection_for_unauthorized_users(self):
        """API/AJAX calls from unauthorized users must return HTTP 401 or 403 JSON."""
        # Anonymous AJAX -> 401
        resp = self.client.post(
            '/complaint/new/',
            {'title': 'Ajax test'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['status'], 'UNAUTHORIZED')

        # Staff Officer AJAX -> 403
        self.client.force_login(self.dl1_user)
        resp_staff = self.client.post(
            '/complaint/new/',
            {'title': 'Ajax staff test'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp_staff.status_code, 403)
        self.assertEqual(resp_staff.json()['status'], 'FORBIDDEN')


class ClusterEnableDisableTestCase(TestCase):
    """
    Test suite for enabling and disabling local government clusters (e.g. GCC).
    Verifies SuperAdmin toggle controls, RBAC security gates, citizen complaint fallback,
    and platform context processor metrics.
    """

    def setUp(self):
        self.client = Client()

        # Municipal Cluster
        self.cluster = Cluster.objects.create(
            name="Greater Chennai Corporation",
            code="GCC",
            emergency_helpline="1234",
            is_active=True
        )
        self.zone = Zone.objects.create(cluster=self.cluster, number=5, name="Royapuram")
        self.ward = Ward.objects.create(zone=self.zone, number=50, name="Royapuram North")
        self.dept = Department.objects.create(name="Public Works & Roads", code="ENG-RDS", cluster=self.cluster)
        self.category = GrievanceCategory.objects.create(
            cluster=self.cluster, department=self.dept, name="Pothole Repair", code="RDS-POT", sla_hours=48
        )

        # SuperAdmin user
        self.superadmin = User.objects.create_superuser('superadmin_cluster', 'admin@cluster.gov', 'pass')
        UserProfile.objects.create(user=self.superadmin, cluster=self.cluster, role='SUPERADMIN')

        # Regular Citizen user
        self.citizen = User.objects.create_user('citizen_cluster', 'citizen@cluster.org', 'pass')
        UserProfile.objects.create(
            user=self.citizen, cluster=self.cluster, role='CITIZEN',
            is_aadhaar_verified=True, aadhaar_last4='9988'
        )

        # Officer user
        self.officer = User.objects.create_user('officer_cluster', 'officer@cluster.gov', 'pass')
        UserProfile.objects.create(
            user=self.officer, cluster=self.cluster, role='WARD_OFFICER',
            zone=self.zone, ward=self.ward, department=self.dept
        )

        # Department Admin user
        self.dept_admin = User.objects.create_user('deptadmin_cluster', 'deptadmin@cluster.gov', 'pass')
        UserProfile.objects.create(
            user=self.dept_admin, cluster=self.cluster, role='DEPT_ADMIN',
            department=self.dept
        )

    def test_superadmin_can_toggle_cluster_via_dedicated_endpoint(self):
        """SuperAdmin can disable and re-enable cluster via /superadmin/clusters/<id>/toggle/"""
        self.client.force_login(self.superadmin)
        self.assertTrue(self.cluster.is_active)

        # Disable cluster
        resp_disable = self.client.post(f'/superadmin/clusters/{self.cluster.id}/toggle/', follow=True)
        self.assertEqual(resp_disable.status_code, 200)
        self.cluster.refresh_from_db()
        self.assertFalse(self.cluster.is_active)
        self.assertContains(resp_disable, "disabled and deactivated")

        # Re-enable cluster
        resp_enable = self.client.post(f'/superadmin/clusters/{self.cluster.id}/toggle/', follow=True)
        self.assertEqual(resp_enable.status_code, 200)
        self.cluster.refresh_from_db()
        self.assertTrue(self.cluster.is_active)
        self.assertContains(resp_enable, "enabled and activated")

    def test_superadmin_can_toggle_cluster_via_onboard_post_action(self):
        """SuperAdmin can toggle cluster via cluster_onboard form POST with action='toggle_status'"""
        self.client.force_login(self.superadmin)

        resp = self.client.post('/superadmin/clusters/', {
            'action': 'toggle_status',
            'cluster_id': self.cluster.id
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.cluster.refresh_from_db()
        self.assertFalse(self.cluster.is_active)

        # Toggle back
        resp2 = self.client.post('/superadmin/clusters/', {
            'action': 'toggle_status',
            'cluster_id': self.cluster.id
        }, follow=True)
        self.assertEqual(resp2.status_code, 200)
        self.cluster.refresh_from_db()
        self.assertTrue(self.cluster.is_active)

    def test_unauthorized_users_forbidden_from_toggling_cluster(self):
        """Non-SuperAdmins (Citizen, Officer, Dept Admin, Anonymous) cannot toggle cluster activation."""
        toggle_url = f'/superadmin/clusters/{self.cluster.id}/toggle/'

        # 1. Anonymous visitor -> redirect to login
        resp_anon = self.client.post(toggle_url)
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/login/', resp_anon.url)
        self.cluster.refresh_from_db()
        self.assertTrue(self.cluster.is_active)

        # 2. Citizen user -> 403 Forbidden
        self.client.force_login(self.citizen)
        resp_citizen = self.client.post(toggle_url)
        self.assertEqual(resp_citizen.status_code, 403)
        self.cluster.refresh_from_db()
        self.assertTrue(self.cluster.is_active)

        # 3. Officer user -> 403 Forbidden
        self.client.force_login(self.officer)
        resp_officer = self.client.post(toggle_url)
        self.assertEqual(resp_officer.status_code, 403)
        self.cluster.refresh_from_db()
        self.assertTrue(self.cluster.is_active)

        # 4. Department Admin user -> 403 Forbidden
        self.client.force_login(self.dept_admin)
        resp_dept = self.client.post(toggle_url)
        self.assertEqual(resp_dept.status_code, 403)
        self.cluster.refresh_from_db()
        self.assertTrue(self.cluster.is_active)

    def test_complaint_filing_behavior_when_cluster_is_disabled(self):
        """When all clusters or the active cluster is disabled, citizens receive a friendly maintenance notice (503)."""
        self.client.force_login(self.citizen)

        # When active, citizen can access filing page (200 OK)
        resp_active = self.client.get('/complaint/new/')
        self.assertEqual(resp_active.status_code, 200)
        self.assertTemplateUsed(resp_active, 'citizen/file_complaint.html')

        # Disable cluster
        self.cluster.is_active = False
        self.cluster.save()

        # When disabled, citizen visiting filing page receives cluster_disabled notice
        resp_disabled = self.client.get('/complaint/new/')
        self.assertEqual(resp_disabled.status_code, 503)
        self.assertTemplateUsed(resp_disabled, 'citizen/cluster_disabled.html')
        self.assertContains(resp_disabled, "Municipal Services Temporarily Inactive", status_code=503)
        self.assertContains(resp_disabled, "Helpline: 1234", status_code=503)

        # Re-enable cluster -> filing works again
        self.cluster.is_active = True
        self.cluster.save()
        resp_restored = self.client.get('/complaint/new/')
        self.assertEqual(resp_restored.status_code, 200)

    def test_cluster_context_processor_and_matrix_display(self):
        """Global context processor and superadmin matrix correctly calculate active vs disabled clusters."""
        # Create a second cluster for multi-cluster verification
        mdu_cluster = Cluster.objects.create(
            name="Madurai Corporation",
            code="MDU",
            is_active=False
        )

        self.client.force_login(self.superadmin)
        resp = self.client.get('/superadmin/matrix/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['active_clusters_count'], 1)
        self.assertEqual(resp.context['disabled_clusters_count'], 1)
        self.assertEqual(resp.context['total_clusters_count'], 2)
        self.assertContains(resp, "Greater Chennai Corporation")
        self.assertContains(resp, "Madurai Corporation")
        self.assertContains(resp, "Disable Cluster")
        self.assertContains(resp, "Enable Cluster")


class MaduraiClusterOfficersTestCase(TestCase):
    """
    Test suite verifying Madurai Municipal Corporation official users.
    Ensures all 15 accounts are provisioned under cluster MMC, authenticate
    via email or username, and have proper RBAC roles and permissions.
    """

    def test_madurai_officers_provisioning_and_authentication(self):
        from core.management.commands.provision_madurai_officers import provision_madurai_officers, MADURAI_OFFICERS_SPEC
        from django.contrib.auth import authenticate

        results = provision_madurai_officers()
        self.assertEqual(len(results), 15)

        for spec in MADURAI_OFFICERS_SPEC:
            email = spec['email']
            username = spec['username']
            password = 'Admin@Dpig2026'

            # User existence
            user = User.objects.filter(email__iexact=email).first()
            self.assertIsNotNone(user, f"User with email {email} should exist")

            # Direct authentication
            auth_user = authenticate(username=user.username, password=password)
            self.assertIsNotNone(auth_user, f"User {user.username} must authenticate with password {password}")

            # Profile verification
            profile = user.profile
            self.assertEqual(profile.cluster.code, 'MMC')
            self.assertEqual(profile.role, spec['role'])
            self.assertEqual(profile.hierarchy_level, spec['hierarchy_level'])

            # Web login via email
            resp = self.client.post('/login/', {
                'username': email,
                'password': password,
            })
            self.assertEqual(resp.status_code, 302, f"Login with email {email} must redirect")
            self.client.logout()


class P0P1HardeningAndIngestionTestCase(TestCase):
    """Verifies security controls, webhook ingestion, and workflow integrity."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC", is_active=True)
        self.zone = Zone.objects.create(cluster=self.cluster, number=1, name="Thiruvottiyur")
        self.ward = Ward.objects.create(zone=self.zone, number=1, name="Ward 1")
        self.dept = Department.objects.create(cluster=self.cluster, name="Roads and Bridges", code="ROADS")
        self.cat = GrievanceCategory.objects.create(cluster=self.cluster, department=self.dept, name="Pothole Repair", code="POTHOLE", sla_hours=24)

        # Setup DL1 Officer
        self.officer_user = User.objects.create_user('ae.w1', 'ae1@gcc.gov.in', 'Admin@Dpig2026')
        UserProfile.objects.create(
            user=self.officer_user, cluster=self.cluster, zone=self.zone, ward=self.ward,
            department=self.dept, role='WARD_OFFICER', hierarchy_level=1
        )

        # Citizens
        self.citizen_alice = User.objects.create_user('alice', 'alice@test.in', 'Pass@123')
        UserProfile.objects.create(user=self.citizen_alice, cluster=self.cluster, role='CITIZEN', is_aadhaar_verified=True, phone='9840111111')

        self.citizen_bob = User.objects.create_user('bob', 'bob@test.in', 'Pass@123')
        UserProfile.objects.create(user=self.citizen_bob, cluster=self.cluster, role='CITIZEN', is_aadhaar_verified=True, phone='9840222222')

    def test_external_api_complaint_ingest(self):
        """External bot / n8n webhook creates complaint with DIGIPIN and assigns DL1 officer."""
        payload = {
            'channel': 'WhatsApp',
            'sender_phone': '9840111111',
            'message_text': 'Heavy waterlogging near bus depot after heavy rains.',
            'latitude': 13.0827,
            'longitude': 80.2707
        }
        resp = self.client.post(
            '/api/complaints/ingest/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_INTERNAL_TOKEN='dpig-internal-webhook-secret-2026'
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['status'], 'REGISTERED')
        self.assertTrue('ticket_number' in data)
        self.assertTrue('digipin' in data)

        complaint = Complaint.objects.get(ticket_number=data['ticket_number'])
        self.assertEqual(complaint.citizen, self.citizen_alice)
        self.assertEqual(complaint.current_level, 'DL1')
        self.assertEqual(complaint.current_assignee, self.officer_user)

    def test_track_complaint_authorization_prevent_hijack(self):
        """Unauthorized citizen cannot confirm resolution or reopen another citizen's grievance."""
        complaint = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            title="Broken streetlamp", description="Lamp post damaged", latitude=13.0827, longitude=80.2707,
            citizen=self.citizen_alice, status="RESOLVED", current_level="DL1", current_assignee=self.officer_user
        )

        # Bob attempts to reopen Alice's complaint
        self.client.force_login(self.citizen_bob)
        resp = self.client.post(f'/track/{complaint.ticket_number}/', {'action': 'reopen', 'reopen_reason': 'Hijacked reopen'})
        self.assertEqual(resp.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, "RESOLVED", "Bob must not be able to reopen Alice's grievance")

        # Alice reopens her own complaint
        self.client.force_login(self.citizen_alice)
        resp = self.client.post(f'/track/{complaint.ticket_number}/', {'action': 'reopen', 'reopen_reason': 'Still not fixed'})
        self.assertEqual(resp.status_code, 302)
        complaint.refresh_from_db()
        self.assertIn(complaint.status, ['REOPENED', 'ESCALATED'])

    def test_officer_resolution_proof_required(self):
        """Officer cannot resolve without resolution photo or substantive note (>= 10 chars)."""
        complaint = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            title="Clogged drain", description="Drain blocked with plastic waste", latitude=13.0827, longitude=80.2707,
            citizen=self.citizen_alice, status="ASSIGNED", current_level="DL1", current_assignee=self.officer_user
        )

        self.client.force_login(self.officer_user)

        # Attempt resolve with empty notes
        resp = self.client.post(f'/officer/complaint/{complaint.id}/', {'action': 'resolve', 'notes': 'done'})
        self.assertEqual(resp.status_code, 302)
        complaint.refresh_from_db()
        self.assertNotEqual(complaint.status, 'RESOLVED', "Must reject resolution without substantive proof")

        # Resolve with substantive notes (>= 10 chars)
        resp = self.client.post(f'/officer/complaint/{complaint.id}/', {
            'action': 'resolve',
            'notes': 'Desilted drain and cleared blocked inlet pipeline completely.'
        })
        self.assertEqual(resp.status_code, 302)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, 'RESOLVED')

    def test_sla_watchdog_apex_level_deduplication(self):
        """Overdue complaint at CM_OFFICE does not generate duplicate APEX audit entries on multiple watchdog runs."""
        past_time = timezone.now() - timedelta(hours=5)
        cm_user = User.objects.create_user('cm.test', 'cm@tn.gov.in', 'Admin@Dpig2026')
        UserProfile.objects.create(user=cm_user, cluster=self.cluster, role='COMMISSIONER', hierarchy_level=7)

        complaint = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            title="Apex Critical Escalation", description="State level issue", latitude=13.0827, longitude=80.2707,
            status="ESCALATED", current_level="CM_OFFICE", escalated_to_level=7,
            current_assignee=cm_user, sla_deadline=past_time
        )

        from core.tasks import monitor_sla_deadlines_task
        # First watchdog run
        monitor_sla_deadlines_task()
        complaint.refresh_from_db()
        self.assertTrue(complaint.is_sla_breached)
        first_apex_count = complaint.audit_logs.filter(action='APEX_LEVEL_NOTIFICATION').count()
        self.assertEqual(first_apex_count, 1)

        # Second watchdog run (5 minutes later)
        monitor_sla_deadlines_task()
        second_apex_count = complaint.audit_logs.filter(action='APEX_LEVEL_NOTIFICATION').count()
        self.assertEqual(second_apex_count, 1, "Watchdog must not spam duplicate APEX audit blocks on subsequent runs")

    def test_open_redirect_protection_in_login(self):
        """Login view rejects unsafe offsite open redirects."""
        resp = self.client.post('/login/', {
            'username': 'alice',
            'password': 'Pass@123',
            'next': 'https://evil-phishing-site.com/steal'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp.url, 'https://evil-phishing-site.com/steal')
        self.assertIn(resp.url, ['/', '/citizen/'])


class P2ArchitectureAndScalabilityTestCase(TestCase):
    """Verifies P2 infrastructure probes, feature matrix toggles, bounding box queries, and upload constraints."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="Greater Chennai Corporation", code="GCC", is_active=True)
        self.zone = Zone.objects.create(cluster=self.cluster, number=1, name="Thiruvottiyur")
        self.ward = Ward.objects.create(zone=self.zone, number=1, name="Ward 1", centroid_lat=13.0827, centroid_lng=80.2707)
        self.dept = Department.objects.create(cluster=self.cluster, name="Roads and Bridges", code="ROADS")
        self.cat = GrievanceCategory.objects.create(cluster=self.cluster, department=self.dept, name="Pothole", code="POTHOLE", sla_hours=24)

    def test_healthz_endpoint(self):
        """Kubernetes /healthz/ probe returns 200 with HEALTHY status and database verification."""
        resp = self.client.get('/healthz/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get('status'), 'HEALTHY')
        self.assertEqual(data.get('db'), 'OK')

    def test_feature_matrix_disabling_sla_watchdog(self):
        """When sla_escalation_watchdog feature is disabled, watchdog task skips execution."""
        from core.feature_matrix import save_feature_matrix
        from core.tasks import monitor_sla_deadlines_task

        past_time = timezone.now() - timedelta(hours=3)
        dl1_user = User.objects.create_user('ae.w1_sla', 'ae_sla@gcc.gov.in', 'Admin@Dpig2026')
        UserProfile.objects.create(user=dl1_user, cluster=self.cluster, role='WARD_OFFICER', hierarchy_level=1)

        c = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            title="Overdue ticket", description="Testing watchdog disable", latitude=13.0827, longitude=80.2707,
            status="ASSIGNED", current_level="DL1", current_assignee=dl1_user, sla_deadline=past_time
        )

        try:
            # Disable watchdog feature
            save_feature_matrix({'sla_escalation_watchdog': False})
            monitor_sla_deadlines_task()
            c.refresh_from_db()
            self.assertEqual(c.current_level, 'DL1', "Watchdog must not escalate when feature is disabled")
        finally:
            save_feature_matrix({'sla_escalation_watchdog': True})

    def test_spatial_bounding_box_duplicate_detection(self):
        """Spatial duplicate detection clusters grievances within 350m using indexed bounding box query."""
        from core.tasks import detect_spatial_duplicates

        parent = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            title="Pothole near junction", description="Major road depression",
            latitude=13.0827, longitude=80.2707, status="ASSIGNED", current_level="DL1"
        )

        # Child complaint at ~100m distance
        child = Complaint.objects.create(
            cluster=self.cluster, zone=self.zone, ward=self.ward, department=self.dept, category=self.cat,
            title="Dangerous pothole", description="Nearby road depression",
            latitude=13.0832, longitude=80.2712, status="SUBMITTED", current_level="DL1"
        )

        detect_spatial_duplicates(child)
        child.refresh_from_db()
        self.assertEqual(child.is_duplicate_of, parent)

    def test_file_upload_format_validation(self):
        """File upload rejects non-image extension files in citizen grievance filing."""
        citizen = User.objects.create_user('charlie', 'charlie@test.in', 'Pass@123')
        UserProfile.objects.create(user=citizen, cluster=self.cluster, role='CITIZEN', is_aadhaar_verified=True)
        self.client.force_login(citizen)

        fake_script = SimpleUploadedFile("malicious.sh", b"#!/bin/bash\necho bad\n", content_type="text/x-shellscript")
        resp = self.client.post('/complaint/new/', {
            'title': 'Test with invalid file',
            'description': 'Description with invalid file attachment',
            'image': fake_script,
            'zone': self.zone.id,
            'category': self.cat.id,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Complaint.objects.filter(title='Test with invalid file').exists())


class ClusterAndUserCreationTemplatesTestCase(TestCase):
    """
    Comprehensive test suite verifying:
    1. Cluster Onboarding Template (sample, blank, export, resilient parsing)
    2. Officer Creation Template (download, openpyxl DataValidation, department scoping, roster export)
    3. Bulk Upload Protections (file size, format whitelist, warning tracking)
    """

    def setUp(self):
        self.client = Client()
        self.cluster = Cluster.objects.create(
            name="Greater Chennai Corporation",
            code="GCC",
            cluster_type="MUNICIPAL_CORP",
            state="Tamil Nadu",
            headquarters_lat=13.0827,
            headquarters_lng=80.2707,
            contact_email="commissioner@chennaicorporation.gov.in",
            emergency_helpline="1913",
            is_active=True
        )
        self.zone5 = Zone.objects.create(
            cluster=self.cluster,
            number=5,
            name="Royapuram",
            hq_lat=13.10,
            hq_lng=80.29
        )
        self.ward52 = Ward.objects.create(
            zone=self.zone5,
            number=52,
            name="Ward 52",
            centroid_lat=13.11,
            centroid_lng=80.29,
            digipin_prefix="4T38CT",
            area_sq_km=1.5
        )
        self.dept_roads = Department.objects.create(
            cluster=self.cluster,
            code="ROADS",
            name="Roads & Bridges",
            standard_sla_hours=36
        )
        self.dept_swm = Department.objects.create(
            cluster=self.cluster,
            code="SWM",
            name="Solid Waste Management",
            standard_sla_hours=24
        )
        self.cat_pothole = GrievanceCategory.objects.create(
            cluster=self.cluster,
            department=self.dept_roads,
            code="POTHOLE",
            name="Road Pothole",
            default_severity="MEDIUM",
            sla_hours=36,
            escalation_l1_hours=12,
            escalation_l2_hours=24,
            escalation_l3_hours=48
        )

        # SuperAdmin User
        self.superadmin_user = User.objects.create_superuser('state_admin', 'super@tn.gov.in', 'Password@123')
        self.superadmin_profile = UserProfile.objects.create(
            user=self.superadmin_user,
            cluster=self.cluster,
            role='SUPERADMIN',
            hierarchy_level=7
        )

        # Dept Admin User (ROADS)
        self.deptadmin_user = User.objects.create_user('roads_admin', 'roads.admin@gcc.gov.in', 'Password@123', is_staff=True)
        self.deptadmin_profile = UserProfile.objects.create(
            user=self.deptadmin_user,
            cluster=self.cluster,
            department=self.dept_roads,
            role='DEPT_ADMIN',
            hierarchy_level=4
        )

        # Regular Citizen User
        self.citizen_user = User.objects.create_user('citizen_user', 'citizen@example.com', 'Password@123')
        self.citizen_profile = UserProfile.objects.create(
            user=self.citizen_user,
            cluster=self.cluster,
            role='CITIZEN',
            hierarchy_level=1
        )

    def test_download_officer_template_accessible_by_superadmin_and_dept_admin(self):
        """Verifies both SuperAdmin and DeptAdmin can download officer templates in XLSX and CSV."""
        # 1. SuperAdmin download XLSX
        self.client.force_login(self.superadmin_user)
        resp = self.client.get(reverse('download_officer_template') + '?format=xlsx')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('dpig_officer_bulk_upload_template.xlsx', resp['Content-Disposition'])

        # 2. SuperAdmin download CSV
        resp_csv = self.client.get(reverse('download_officer_template') + '?format=csv')
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv['Content-Type'], 'text/csv; charset=utf-8')

        # 3. DeptAdmin download XLSX (must not return 403 Forbidden)
        self.client.force_login(self.deptadmin_user)
        resp_dept = self.client.get(reverse('download_officer_template') + '?format=xlsx')
        self.assertEqual(resp_dept.status_code, 200)
        self.assertIn('dpig_officer_bulk_upload_template_roads.xlsx', resp_dept['Content-Disposition'])

        # 4. Citizen denied
        self.client.force_login(self.citizen_user)
        resp_cit = self.client.get(reverse('download_officer_template'))
        self.assertEqual(resp_cit.status_code, 403)

    def test_officer_template_openpyxl_data_validation(self):
        """Verifies generated XLSX contains openpyxl DataValidation for Role, Workflow Level, and Department."""
        import openpyxl, io
        from core.officer_bulk_service import export_officer_template
        bytes_data, _, _ = export_officer_template('xlsx', department=self.dept_roads, cluster=self.cluster)

        wb = openpyxl.load_workbook(io.BytesIO(bytes_data))
        self.assertIn('Officers_Bulk_Upload', wb.sheetnames)
        self.assertIn('Instructions_&_Reference', wb.sheetnames)

        ws = wb['Officers_Bulk_Upload']
        # Check validations exist
        self.assertGreaterEqual(len(ws.data_validations.dataValidation), 2)
        validations = ws.data_validations.dataValidation
        formula_texts = [v.formula1 for v in validations]
        # At least one validation should contain WARD_OFFICER and DL1
        self.assertTrue(any('WARD_OFFICER' in f for f in formula_texts))
        self.assertTrue(any('DL1' in f for f in formula_texts))

    def test_export_officer_roster_view(self):
        """Tests live officer roster export for SuperAdmin and department-scoped for DeptAdmin."""
        # 1. SuperAdmin exports all
        self.client.force_login(self.superadmin_user)
        resp = self.client.get(reverse('export_officer_roster') + '?format=xlsx')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('dpig_active_officers_roster.xlsx', resp['Content-Disposition'])

        # 2. DeptAdmin exports ROADS only
        self.client.force_login(self.deptadmin_user)
        resp_dept = self.client.get(reverse('export_officer_roster') + '?format=xlsx')
        self.assertEqual(resp_dept.status_code, 200)
        self.assertIn('dpig_active_officers_roster_roads.xlsx', resp_dept['Content-Disposition'])

    def test_download_cluster_template_options(self):
        """Tests download_template with ?type=sample, ?type=blank, and ?type=export."""
        self.client.force_login(self.superadmin_user)

        # 1. Blank starter template
        resp_blank = self.client.get(reverse('download_template') + '?type=blank')
        self.assertEqual(resp_blank.status_code, 200)
        self.assertIn('dpig_blank_cluster_template.xlsx', resp_blank['Content-Disposition'])

        # 2. Live cluster export
        resp_export = self.client.get(reverse('download_template') + f'?type=export&cluster_id={self.cluster.id}')
        self.assertEqual(resp_export.status_code, 200)
        self.assertIn(f'cluster_export_{self.cluster.code.lower()}.xlsx', resp_export['Content-Disposition'])

        # 3. Sample master template
        resp_sample = self.client.get(reverse('download_template') + '?type=sample')
        self.assertEqual(resp_sample.status_code, 200)
        self.assertIn('.xlsx', resp_sample['Content-Disposition'])

    def test_cluster_importer_blank_and_export_roundtrip(self):
        """Verifies generate_blank_cluster_template -> import -> export_cluster_to_excel roundtrip."""
        import io
        from core.cluster_importer import (
            generate_blank_cluster_template,
            import_cluster_from_excel,
            export_cluster_to_excel,
            safe_int, safe_float, clean_str
        )

        # Safe helpers
        self.assertEqual(safe_int(' 42 '), 42)
        self.assertEqual(safe_int('42.0'), 42)
        self.assertEqual(safe_int('Zone 15'), 15)
        self.assertEqual(safe_int(''), 0)
        self.assertEqual(safe_float('13.0827'), 13.0827)
        self.assertEqual(safe_float('invalid', default=5.5), 5.5)
        self.assertEqual(clean_str('  hello  '), 'hello')
        self.assertEqual(clean_str('NaN'), '')

        # Generate blank template
        blank_bytes = generate_blank_cluster_template()
        self.assertGreater(len(blank_bytes), 1000)

        # Import blank template into DB
        res = import_cluster_from_excel(io.BytesIO(blank_bytes))
        self.assertEqual(res['status'], 'SUCCESS')
        self.assertEqual(res['cluster_code'], 'MMC')
        self.assertGreaterEqual(res['zones_count'], 1)
        self.assertGreaterEqual(res['wards_count'], 1)

        # Export live cluster back to Excel
        exported_bytes = export_cluster_to_excel(res['cluster_id'])
        self.assertGreater(len(exported_bytes), 1000)

    def test_parse_and_provision_officers_warnings_and_resilience(self):
        """Verifies parse_and_provision_officers collects warnings when zones/wards/depts are missing."""
        import pandas as pd
        from core.officer_bulk_service import parse_and_provision_officers

        # Data with invalid zone 99 and invalid ward 999
        df = pd.DataFrame([
            {
                'Username': 'ae_test_warning',
                'Full_Name': 'Warning Test Officer',
                'Email': 'test.warning@gcc.gov.in',
                'Phone': '9840099999',
                'Role': 'WARD_OFFICER',
                'Workflow_Level': 'DL1',
                'Zone_Number': '99',  # non-existent zone
                'Ward_Number': '999', # non-existent ward
                'Department_Code': 'ROADS',
                'Designation': 'Junior AE',
                'Password': 'TestPassword@123'
            }
        ])

        res = parse_and_provision_officers(df, cluster=self.cluster, update_existing=True)
        self.assertEqual(res['status'], 'SUCCESS')
        self.assertEqual(res['created_count'], 1)
        # Should have captured warnings for missing zone and ward
        self.assertGreaterEqual(len(res['warnings']), 1)
        self.assertTrue(any('Zone' in w for w in res['warnings']))

        # Verify user was created in database
        u = User.objects.filter(username='ae_test_warning').first()
        self.assertIsNotNone(u)
        self.assertEqual(u.profile.role, 'WARD_OFFICER')
        self.assertIsNone(u.profile.zone)


class FreshDeploymentTestCase(TestCase):
    """Verifies that DPIG can be reset to a pristine deployment state with zero clusters and clean UI."""

    def test_reset_command_leaves_sole_superadmin_and_cleans_all_records(self):
        from django.core.management import call_command
        # Seed dummy cluster and users first
        c = Cluster.objects.create(name="TempCluster", code="TEMP")
        Zone.objects.create(cluster=c, number=1, name="Zone 1")
        demo_u = User.objects.create_user(username="demo.officer", password="Password123")
        UserProfile.objects.create(user=demo_u, cluster=c, role="WARD_OFFICER")

        # Run fresh deployment reset
        call_command('reset_to_fresh_deployment', admin_password='Admin@Dpig2026')

        # Verify database is pristine
        self.assertEqual(Cluster.objects.count(), 0)
        self.assertEqual(Zone.objects.count(), 0)
        self.assertEqual(Ward.objects.count(), 0)
        self.assertEqual(Department.objects.count(), 0)
        self.assertEqual(GrievanceCategory.objects.count(), 0)
        self.assertEqual(Complaint.objects.count(), 0)
        self.assertEqual(ComplaintAuditLog.objects.count(), 0)
        self.assertEqual(CapitalProjectRecommendation.objects.count(), 0)
        self.assertEqual(GovernmentBroadcast.objects.count(), 0)

        # Exactly 1 user: superadmin
        self.assertEqual(User.objects.count(), 1)
        sa = User.objects.first()
        self.assertEqual(sa.username, 'superadmin')
        self.assertEqual(sa.email, 'admin@dpig.gov.in')
        self.assertTrue(sa.is_superuser)
        self.assertTrue(sa.is_staff)
        self.assertEqual(sa.profile.role, 'SUPERADMIN')
        self.assertEqual(sa.profile.hierarchy_level, 7)
        self.assertIsNone(sa.profile.cluster)

    def test_login_and_admin_pages_in_zero_cluster_state(self):
        from django.core.management import call_command
        call_command('reset_to_fresh_deployment', admin_password='Admin@Dpig2026')

        client = Client()
        # 1. Login page renders clean without 1-Click Evaluation buttons
        login_res = client.get('/login/')
        self.assertEqual(login_res.status_code, 200)
        self.assertContains(login_res, "Staff & Officer Sign In")
        self.assertNotContains(login_res, "1-Click Instant Evaluation Logins")
        self.assertNotContains(login_res, "auditor.general")

        # 2. Public landing page renders safely with 0 clusters & 0 complaints
        home_res = client.get('/')
        self.assertEqual(home_res.status_code, 200)
        self.assertContains(home_res, "0 / 0")
        self.assertContains(home_res, "No active cluster onboarded")
        self.assertNotContains(home_res, "15 / 200")
        self.assertNotContains(home_res, "DPIG-2026-GCC-000001")

        # 3. SuperAdmin logs in and views administrative management consoles
        logged_in = client.login(username='superadmin', password='Admin@Dpig2026')
        self.assertTrue(logged_in)

        matrix_res = client.get('/superadmin/matrix/')
        self.assertEqual(matrix_res.status_code, 200)
        self.assertNotContains(matrix_res, "Direct Test Login")
        self.assertNotContains(matrix_res, "Test Switch")

        clusters_res = client.get('/superadmin/clusters/')
        self.assertEqual(clusters_res.status_code, 200)

        staff_res = client.get('/superadmin/staff/')
        self.assertEqual(staff_res.status_code, 200)


class CronWebhookEndpointsTestCase(TestCase):
    """Verify Serverless Cron webhook endpoints for Cloud Scheduler."""

    def test_cron_monitor_sla_unauthorized(self):
        client = Client()
        res = client.get('/api/cron/monitor-sla/')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json().get('status'), 'UNAUTHORIZED')

    def test_cron_monitor_sla_authorized_header(self):
        client = Client()
        token = getattr(settings, 'INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')
        res = client.get('/api/cron/monitor-sla/', HTTP_X_DPIG_CRON_KEY=token)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get('status'), 'SUCCESS')

    def test_cron_refresh_insights_unauthorized(self):
        client = Client()
        res = client.get('/api/cron/refresh-insights/')
        self.assertEqual(res.status_code, 401)

    def test_cron_refresh_insights_authorized_param(self):
        client = Client()
        token = getattr(settings, 'INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')
        res = client.get(f'/api/cron/refresh-insights/?token={token}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get('status'), 'SUCCESS')












