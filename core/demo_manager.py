"""
Demo Data Manager for DPIG:
Provides SuperAdmin with one-click capabilities to seed realistic Tamil Nadu
civic grievances across GCC zones/wards, and purge demo data safely.
"""
import random
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from core.models import (
    Cluster, Zone, Ward, Department, GrievanceCategory,
    Complaint, ComplaintAuditLog, SLAEscalationLog, AIDecisionLog
)
from core.digipin import encode as encode_digipin, format_digipin


SAMPLE_COMPLAINTS_DATA = [
    {
        "title": "Severe Waterlogging & Broken Sump Drain near Bus Terminus",
        "description": "After yesterday's rain, over 2 feet of stagnant stormwater has accumulated outside the main entrance. Pedestrian traffic completely blocked.",
        "lat": 13.0418, "lng": 80.2341, "landmark": "T. Nagar Bus Terminus, Usman Road",
        "cat_code": "WATERLOGGING", "dept_code": "SWD", "zone_num": 10, "ward_num": 108,
        "severity": "HIGH", "status": "FIELD_VERIFICATION",
    },
    {
        "title": "Dangerous Deep Pothole and Asphalt Subsidence",
        "description": "Deep asphalt trench formed near bus shelter. Two two-wheelers skidded last night. Immediate cold-mix patch work required.",
        "lat": 13.0588, "lng": 80.2520, "landmark": "Anna Salai near Thousand Lights Mosque",
        "cat_code": "POTHOLE", "dept_code": "ROADS", "zone_num": 9, "ward_num": 114,
        "severity": "CRITICAL", "status": "ASSIGNED",
    },
    {
        "title": "Overflowing Garbage Compactor Bin with Stray Cattle Hazard",
        "description": "Secondary waste bin has not been cleared for 48 hours. Waste spilling onto the carriageway attracting stray animals.",
        "lat": 13.1580, "lng": 80.3012, "landmark": "Kathivakkam High Road, Ennore",
        "cat_code": "GARBAGE", "dept_code": "SWM", "zone_num": 1, "ward_num": 1,
        "severity": "MEDIUM", "status": "RESOLVED",
    },
    {
        "title": "Non-Functional Streetlight High Mast Column",
        "description": "Entire 200m stretch is in pitch darkness since last Thursday. Poses serious safety hazard for women and night commuters.",
        "lat": 12.9815, "lng": 80.2180, "landmark": "100 Feet Bypass Road, Velachery",
        "cat_code": "STREETLIGHT", "dept_code": "LIGHTS", "zone_num": 13, "ward_num": 170,
        "severity": "MEDIUM", "status": "SUBMITTED",
    },
    {
        "title": "Open Manhole Without Warning Barricade",
        "description": "Cover collapsed into the sewer chamber. Chamber is 8 feet deep. Residents have placed wooden branches as temporary hazard marker.",
        "lat": 13.0836, "lng": 80.2825, "landmark": "EVR Periyar Salai near Central Metro",
        "cat_code": "WATERLOGGING", "dept_code": "SWD", "zone_num": 5, "ward_num": 52,
        "severity": "CRITICAL", "status": "FIELD_VERIFICATION",
    },
    {
        "title": "Foul Odor & Clogged Micro-Canal Culvert",
        "description": "Plastic silt accumulation blocking storm drain outlet leading into Buckingham canal. Stagnant black water accumulating.",
        "lat": 13.0334, "lng": 80.2707, "landmark": "Kutchery Road near Santhome",
        "cat_code": "WATERLOGGING", "dept_code": "SWD", "zone_num": 9, "ward_num": 124,
        "severity": "HIGH", "status": "RESOLVED",
    },
    {
        "title": "Broken Footpath Paver Blocks & Exposed Cables",
        "description": "Utility trench left open after optical cable laying. Paver blocks scattered across walkway forcing pedestrians onto busy road.",
        "lat": 13.0878, "lng": 80.2145, "landmark": "2nd Avenue, Anna Nagar East",
        "cat_code": "POTHOLE", "dept_code": "ROADS", "zone_num": 8, "ward_num": 102,
        "severity": "MEDIUM", "status": "ASSIGNED",
    },
    {
        "title": "Illegal Debris & C&D Waste Dumping on Open Plot",
        "description": "Truckload of demolition concrete dumped overnight adjacent to corporation park. Creating severe dust pollution.",
        "lat": 12.9010, "lng": 80.2279, "landmark": "OMR Service Lane, Sholinganallur",
        "cat_code": "GARBAGE", "dept_code": "SWM", "zone_num": 15, "ward_num": 197,
        "severity": "MEDIUM", "status": "SUBMITTED",
    },
]


def seed_realistic_demo_complaints() -> int:
    """Seeds realistic demo complaints into the database with cryptographic audit chains."""
    cluster = Cluster.objects.filter(is_active=True).first()
    if not cluster:
        cluster = Cluster.objects.create(
            name="Greater Chennai Corporation",
            code="GCC",
            state="Tamil Nadu",
            headquarters_lat=13.0827,
            headquarters_lng=80.2707,
            emergency_helpline="1234"
        )

    # Ensure sample departments exist
    dept_cache = {}
    for d_code, d_name, d_sla in [
        ('SWD', 'Storm Water Drains', 24),
        ('SWM', 'Solid Waste Management', 12),
        ('ROADS', 'Bridges & Roads', 48),
        ('LIGHTS', 'Electrical & Street Lighting', 24),
    ]:
        dept, _ = Department.objects.get_or_create(
            cluster=cluster,
            code=d_code,
            defaults={'name': d_name, 'standard_sla_hours': d_sla}
        )
        dept_cache[d_code] = dept

    # Ensure sample categories exist
    cat_cache = {}
    for c_code, c_name, d_code, sev in [
        ('WATERLOGGING', 'Stormwater Drain Clogging & Flooding', 'SWD', 'HIGH'),
        ('POTHOLE', 'Road Potholes & Surface Damage', 'ROADS', 'MEDIUM'),
        ('GARBAGE', 'Garbage Overflow & Solid Waste Clearance', 'SWM', 'MEDIUM'),
        ('STREETLIGHT', 'Defective Streetlight & Cable Faults', 'LIGHTS', 'MEDIUM'),
    ]:
        cat, _ = GrievanceCategory.objects.get_or_create(
            cluster=cluster,
            code=c_code,
            defaults={
                'department': dept_cache[d_code],
                'name': c_name,
                'default_severity': sev,
                'sla_hours': 24,
            }
        )
        cat_cache[c_code] = cat

    # Find sample officer user
    officer_user = User.objects.filter(username__startswith='ae.').first() or User.objects.filter(is_staff=True).first()
    citizen_user = User.objects.filter(username='citizen.demo').first()

    created_count = 0
    now = timezone.now()

    for item in SAMPLE_COMPLAINTS_DATA:
        # Resolve Zone & Ward
        z_num = item["zone_num"]
        w_num = item["ward_num"]

        zone, _ = Zone.objects.get_or_create(
            cluster=cluster,
            number=z_num,
            defaults={'name': f'Zone {z_num}', 'hq_lat': item['lat'], 'hq_lng': item['lng']}
        )
        ward, _ = Ward.objects.get_or_create(
            zone=zone,
            number=w_num,
            defaults={'name': f'Ward {w_num}', 'centroid_lat': item['lat'], 'centroid_lng': item['lng']}
        )

        dept = dept_cache.get(item["dept_code"])
        cat = cat_cache.get(item["cat_code"])
        digipin = format_digipin(encode_digipin(item["lat"], item["lng"], precision=10))

        complaint = Complaint.objects.create(
            cluster=cluster,
            zone=zone,
            ward=ward,
            department=dept,
            category=cat,
            citizen=citizen_user,
            citizen_name="Thiru K. Sundaram" if random.random() > 0.5 else "Selvi R. Ananya",
            citizen_email="citizen.chennai@example.gov.in",
            citizen_phone="98401" + str(random.randint(10000, 99999)),
            title=item["title"],
            description=item["description"],
            latitude=item["lat"],
            longitude=item["lng"],
            digipin=digipin,
            address_landmark=item["landmark"],
            severity=item["severity"],
            urgency_score=0.85 if item["severity"] == "CRITICAL" else 0.65,
            status=item["status"],
            current_assignee=officer_user if item["status"] != "SUBMITTED" else None,
            sla_deadline=now + timedelta(hours=24),
            created_at=now - timedelta(hours=random.randint(1, 36)),
        )

        # Build cryptographic audit chain
        # Block 0: SUBMITTED
        b0 = complaint.create_audit_block(
            action="COMPLAINT_SUBMITTED",
            performed_by=citizen_user,
            actor_role="CITIZEN",
            details={"channel": "DJANGO_WEB", "digipin": digipin}
        )

        # Block 1: AI_CLASSIFIED
        b1 = complaint.create_audit_block(
            action="AI_TRIAGE_COMPLETED",
            actor_role="AI_ENGINE",
            details={
                "model": "gemini-3.8-flash",
                "detected_department": dept.code,
                "urgency_score": complaint.urgency_score
            }
        )

        if item["status"] in ["ASSIGNED", "FIELD_VERIFICATION", "RESOLVED"]:
            b2 = complaint.create_audit_block(
                action="ASSIGNED_TO_WARD_OFFICER",
                performed_by=officer_user,
                actor_role="OFFICER",
                details={"assignee": officer_user.username if officer_user else "ae.ward108"}
            )

        if item["status"] in ["FIELD_VERIFICATION", "RESOLVED"]:
            b3 = complaint.create_audit_block(
                action="FIELD_VERIFICATION_STARTED",
                performed_by=officer_user,
                actor_role="OFFICER",
                details={"inspection_vehicle": "GCC-QRT-04", "notes": "Officer dispatched to site"}
            )

        if item["status"] == "RESOLVED":
            complaint.resolved_at = now
            complaint.resolution_notes = "Field repairs completed satisfactorily. High-pressure jetting and de-silting executed."
            complaint.save(update_fields=['resolved_at', 'resolution_notes'])
            complaint.create_audit_block(
                action="RESOLVED_BY_OFFICER",
                performed_by=officer_user,
                actor_role="OFFICER",
                details={"notes": complaint.resolution_notes, "proof_uploaded": True}
            )

        created_count += 1

    return created_count


def purge_demo_complaints() -> int:
    """Purges all complaint tickets, audit blocks, and decision logs while keeping master cluster intact."""
    count = Complaint.objects.count()
    ComplaintAuditLog.objects.all().delete()
    SLAEscalationLog.objects.all().delete()
    AIDecisionLog.objects.all().delete()
    Complaint.objects.all().delete()
    return count
