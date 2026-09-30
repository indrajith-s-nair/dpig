"""
Django management command to provision or update all official Madurai Municipal Corporation (MMC) officers.
Usage: python manage.py provision_madurai_officers
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Cluster, Zone, Ward, Department, UserProfile


MADURAI_OFFICERS_SPEC = [
    {
        'username': 'commissioner.mdu',
        'email': 'commissioner@maduraicorp.gov.in',
        'first_name': 'K. Karthikeyan',
        'last_name': 'IAS',
        'role': 'COMMISSIONER',
        'hierarchy_level': 6,
        'designation': 'Municipal Commissioner IAS - Madurai Corporation',
        'zone_number': None,
        'ward_number': None,
        'department_code': None,
        'phone': '9445190001',
    },
    {
        'username': 'zo1.mdu',
        'email': 'zo1@maduraicorp.gov.in',
        'first_name': 'Dr. M.',
        'last_name': 'Soundararajan',
        'role': 'ZONAL_OFFICER',
        'hierarchy_level': 3,
        'designation': 'Zonal Officer - Zone 1 North (Vadakku)',
        'zone_number': 1,
        'ward_number': None,
        'department_code': None,
        'phone': '9445190101',
    },
    {
        'username': 'zo2.mdu',
        'email': 'zo2@maduraicorp.gov.in',
        'first_name': 'Er. R.',
        'last_name': 'Murugesan',
        'role': 'ZONAL_OFFICER',
        'hierarchy_level': 3,
        'designation': 'Zonal Officer - Zone 2 West (Merku)',
        'zone_number': 2,
        'ward_number': None,
        'department_code': None,
        'phone': '9445190102',
    },
    {
        'username': 'zo3.mdu',
        'email': 'zo3@maduraicorp.gov.in',
        'first_name': 'Dr. P.',
        'last_name': 'Meenakshi Sundaram',
        'role': 'ZONAL_OFFICER',
        'hierarchy_level': 3,
        'designation': 'Zonal Officer - Zone 3 Central (Madhyam)',
        'zone_number': 3,
        'ward_number': None,
        'department_code': None,
        'phone': '9445190103',
    },
    {
        'username': 'zo4.mdu',
        'email': 'zo4@maduraicorp.gov.in',
        'first_name': 'Er. S.',
        'last_name': 'Pandian',
        'role': 'ZONAL_OFFICER',
        'hierarchy_level': 3,
        'designation': 'Zonal Officer - Zone 4 South (Therku)',
        'zone_number': 4,
        'ward_number': None,
        'department_code': None,
        'phone': '9445190104',
    },
    {
        'username': 'zo5.mdu',
        'email': 'zo5@maduraicorp.gov.in',
        'first_name': 'Dr. V.',
        'last_name': 'Alagarsamy',
        'role': 'ZONAL_OFFICER',
        'hierarchy_level': 3,
        'designation': 'Zonal Officer - Zone 5 East (Kizhakku)',
        'zone_number': 5,
        'ward_number': None,
        'department_code': None,
        'phone': '9445190105',
    },
    {
        'username': 'ce.mdu',
        'email': 'ce@maduraicorp.gov.in',
        'first_name': 'Er. S.',
        'last_name': 'Arumugam',
        'role': 'DEPT_ADMIN',
        'hierarchy_level': 4,
        'designation': 'City Engineer / Superintending Engineer (Engineering & Roads)',
        'zone_number': None,
        'ward_number': None,
        'department_code': 'ROADS',
        'phone': '9445190201',
    },
    {
        'username': 'cho.mdu',
        'email': 'cho@maduraicorp.gov.in',
        'first_name': 'Dr. K.',
        'last_name': 'Vinoth Kumar',
        'role': 'DEPT_ADMIN',
        'hierarchy_level': 4,
        'designation': 'City Health Officer (Public Health & Sanitation)',
        'zone_number': None,
        'ward_number': None,
        'department_code': 'HEALTH',
        'phone': '9445190202',
    },
    {
        'username': 'ae.ward12',
        'email': 'ae.ward12@maduraicorp.gov.in',
        'first_name': 'Er. T.',
        'last_name': 'Muthuraman AE',
        'role': 'WARD_OFFICER',
        'hierarchy_level': 1,
        'designation': 'Assistant Engineer (SWD) - Ward 12',
        'zone_number': 1,
        'ward_number': 12,
        'department_code': 'SWD',
        'phone': '9445191201',
    },
    {
        'username': 'si.ward15',
        'email': 'si.ward15@maduraicorp.gov.in',
        'first_name': 'K.',
        'last_name': 'Selvam SI',
        'role': 'FIELD_STAFF',
        'hierarchy_level': 1,
        'designation': 'Sanitary Inspector (SWM) - Ward 15',
        'zone_number': 1,
        'ward_number': 15,
        'department_code': 'SWM',
        'phone': '9445191501',
    },
    {
        'username': 'ae.ward32',
        'email': 'ae.ward32@maduraicorp.gov.in',
        'first_name': 'Er. N.',
        'last_name': 'Rajesh AE',
        'role': 'WARD_OFFICER',
        'hierarchy_level': 1,
        'designation': 'Assistant Engineer (Roads) - Ward 32',
        'zone_number': 2,
        'ward_number': 32,
        'department_code': 'ROADS',
        'phone': '9445193201',
    },
    {
        'username': 'ae.ward54',
        'email': 'ae.ward54@maduraicorp.gov.in',
        'first_name': 'Er. M.',
        'last_name': 'Saravanan AE',
        'role': 'WARD_OFFICER',
        'hierarchy_level': 1,
        'designation': 'Assistant Engineer (Water) - Ward 54',
        'zone_number': 3,
        'ward_number': 54,
        'department_code': 'WATER',
        'phone': '9445195401',
    },
    {
        'username': 'si.ward72',
        'email': 'si.ward72@maduraicorp.gov.in',
        'first_name': 'G.',
        'last_name': 'Marimuthu SI',
        'role': 'FIELD_STAFF',
        'hierarchy_level': 1,
        'designation': 'Sanitary Inspector (SWM) - Ward 72',
        'zone_number': 4,
        'ward_number': 72,
        'department_code': 'SWM',
        'phone': '9445197201',
    },
    {
        'username': 'ae.ward88',
        'email': 'ae.ward88@maduraicorp.gov.in',
        'first_name': 'Er. J.',
        'last_name': 'Vijay AE',
        'role': 'WARD_OFFICER',
        'hierarchy_level': 1,
        'designation': 'Assistant Engineer (Electrical) - Ward 88',
        'zone_number': 5,
        'ward_number': 88,
        'department_code': 'LIGHTS',
        'phone': '9445198801',
    },
    {
        'username': 'policy.analyst.mdu',
        'email': 'policy.analyst.mdu@tn.gov.in',
        'first_name': 'Dr. Ananya',
        'last_name': 'Natarajan',
        'role': 'POLICYMAKER',
        'hierarchy_level': 1,
        'designation': 'Senior Policy Analyst - Madurai Corporation Policy Cell',
        'zone_number': None,
        'ward_number': None,
        'department_code': None,
        'phone': '9445199001',
    },
]


def provision_madurai_officers(default_password='Admin@Dpig2026'):
    """Ensures all 15 Madurai officers exist with accurate attributes and passwords."""
    cluster, _ = Cluster.objects.get_or_create(
        code='MMC',
        defaults={
            'name': 'Madurai Municipal Corporation',
            'cluster_type': 'MUNICIPAL_CORP',
            'state': 'Tamil Nadu',
            'headquarters_lat': 9.9252,
            'headquarters_lng': 78.1198,
            'commissioner_name': 'K. Karthikeyan IAS',
            'contact_email': 'commissioner@maduraicorp.gov.in',
            'emergency_helpline': '1234',
            'is_active': True,
        }
    )
    # Ensure cluster is active
    if not cluster.is_active:
        cluster.is_active = True
        cluster.save()

    # Ensure zones 1..5 exist
    zones_map = {}
    zone_names = {
        1: 'North (Vadakku)',
        2: 'West (Merku)',
        3: 'Central (Madhyam)',
        4: 'South (Therku)',
        5: 'East (Kizhakku)',
    }
    for znum, zname in zone_names.items():
        z, _ = Zone.objects.get_or_create(
            cluster=cluster,
            number=znum,
            defaults={'name': zname}
        )
        zones_map[znum] = z

    # Ensure departments exist
    depts_map = {}
    dept_specs = [
        ('ROADS', 'Roads, Bridges & Footpaths'),
        ('HEALTH', 'Public Health & Vector Control'),
        ('SWM', 'Solid Waste Management'),
        ('SWD', 'Storm Water Drains & Channels'),
        ('WATER', 'Water Supply & Sewage Liaison'),
        ('LIGHTS', 'Street Lights & Electrical'),
        ('PARKS', 'Parks, Playgrounds & Greenery'),
        ('REVENUE', 'Revenue & Assessments'),
    ]
    for dcode, dname in dept_specs:
        d, _ = Department.objects.get_or_create(
            cluster=cluster,
            code=dcode,
            defaults={'name': dname}
        )
        depts_map[dcode] = d

    # Ensure specific wards exist for the officers
    wards_map = {}
    ward_assignments = [(12, 1), (15, 1), (32, 2), (54, 3), (72, 4), (88, 5)]
    for wnum, znum in ward_assignments:
        zone = zones_map[znum]
        w, _ = Ward.objects.get_or_create(
            zone=zone,
            number=wnum,
            defaults={'name': f"Ward {wnum}"}
        )
        wards_map[wnum] = w

    results = []

    for spec in MADURAI_OFFICERS_SPEC:
        email = spec['email']
        username = spec['username']

        # Find existing user by exact email or exact username
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            user = User.objects.filter(username=username).first()

        created = False
        if not user:
            user = User.objects.create(
                username=username,
                email=email,
                first_name=spec['first_name'],
                last_name=spec['last_name'],
                is_staff=True,
            )
            created = True
        else:
            user.email = email
            user.first_name = spec['first_name']
            user.last_name = spec['last_name']
            user.is_staff = True

        # Always ensure password is set
        user.set_password(default_password)
        user.save()

        # Resolve relations
        zone = zones_map.get(spec['zone_number']) if spec['zone_number'] else None
        ward = wards_map.get(spec['ward_number']) if spec['ward_number'] else None
        dept = depts_map.get(spec['department_code']) if spec['department_code'] else None

        profile, p_created = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'cluster': cluster,
                'role': spec['role'],
                'hierarchy_level': spec['hierarchy_level'],
                'designation': spec['designation'],
                'zone': zone,
                'ward': ward,
                'department': dept,
                'phone': spec['phone'],
            }
        )

        # Update profile attributes
        profile.cluster = cluster
        profile.role = spec['role']
        profile.hierarchy_level = spec['hierarchy_level']
        profile.designation = spec['designation']
        profile.zone = zone
        profile.ward = ward
        profile.department = dept
        profile.phone = spec['phone']
        profile.save()

        results.append({
            'username': user.username,
            'email': user.email,
            'role': profile.role,
            'hierarchy_level': profile.hierarchy_level,
            'designation': profile.designation,
            'jurisdiction': f"Zone {zone.number}, Ward {ward.number}" if (zone and ward) else (f"Zone {zone.number}" if zone else "Cluster-Wide"),
            'department': dept.name if dept else "General / Municipal",
            'password': default_password,
            'created': created,
        })

    # Seed Capital Projects & Complaints for Madurai
    seed_madurai_civic_data(cluster, zones_map, wards_map, depts_map)

    return results


def seed_madurai_civic_data(cluster, zones_map, wards_map, depts_map):
    """Provisions priority capital projects and realistic complaints for Madurai."""
    from core.models import CapitalProjectRecommendation, Complaint, GrievanceCategory
    from core.digipin import encode as encode_digipin, format_digipin

    # 1. Capital Projects
    madurai_projects = [
        {
            'title': 'Vaigai Riverfront Flood Mitigation & Stormwater Interceptor Canal',
            'sector': 'Stormwater Drainage & Flood Control',
            'affected_zones': [1, 2, 3],
            'affected_wards': [12, 14, 32, 41],
            'complaint_cluster_count': 38,
            'problem_statement': 'Recurring monsoon runoff from northern channels inundates arterial roads along the Vaigai north bank during flash rains.',
            'proposed_solution': 'Construction of a 4.2 km RCC box-culvert stormwater interceptor canal with silt traps and automated outflow flood gates discharging to Vaigai river basin.',
            'estimated_budget_inr': 185000000.00,
            'priority_score': 94.5,
            'ai_rationale': 'Correlates 38 recurring drainage complaints across Wards 12, 14, and 32 with severe traffic disruptions on Goripalayam-Simmakkal corridor.',
            'status': 'PROPOSED',
        },
        {
            'title': 'Meenakshi Amman Temple Heritage Precinct Smart Sanitation & Pedestrian Plaza',
            'sector': 'Solid Waste & Heritage Precinct',
            'affected_zones': [3],
            'affected_wards': [41, 54],
            'complaint_cluster_count': 52,
            'problem_statement': 'Extreme pedestrian density around Four Masi and Avani Moola Streets generates high commercial solid waste loads causing frequent drainage chokes.',
            'proposed_solution': 'Underground pneumatic waste disposal bins, permeable cobblestone pedestrian walkways, and 24x7 automated micro-sweeper deployment.',
            'estimated_budget_inr': 120000000.00,
            'priority_score': 92.0,
            'ai_rationale': 'Synthesizes high volume of commercial sanitation and garbage overflow reports in Zone 3 Central Ward 54.',
            'status': 'PLANNED',
            'is_planned': True,
        },
        {
            'title': 'Mattuthavani Integrated Bus Terminal (MIBT) Multimodal Underpass & Road Widening',
            'sector': 'Roads, Bridges & Traffic Engineering',
            'affected_zones': [5],
            'affected_wards': [88, 90],
            'complaint_cluster_count': 27,
            'problem_statement': 'Chronic bottleneck at Mattuthavani junction between intra-city buses and southern district highway traffic.',
            'proposed_solution': 'Four-lane grade separator underpass with dedicated pedestrian skywalk connecting MIBT to the proposed Madurai Metro corridor.',
            'estimated_budget_inr': 240000000.00,
            'priority_score': 89.5,
            'ai_rationale': 'Pothole and congestion complaints on Ring Road junction escalated past SLA repeatedly in Zone 5 East.',
            'status': 'PROPOSED',
        },
        {
            'title': 'Madurai West & Arapalayam 24x7 Pressurized Drinking Water Distribution Grid',
            'sector': 'Water Supply & Distribution',
            'affected_zones': [2, 3],
            'affected_wards': [32, 54],
            'complaint_cluster_count': 31,
            'problem_statement': 'Low terminal pressure in drinking water supply lines across old town residential sectors during peak morning hours.',
            'proposed_solution': '2.5 MLD elevated balancing reservoir at Arapalayam with SCADA-controlled booster pumping station and ductile iron pipeline replacement.',
            'estimated_budget_inr': 162000000.00,
            'priority_score': 87.0,
            'ai_rationale': 'Drinking water pressure disruption grievances reported in Ward 54 and Arapalayam cluster.',
            'status': 'PROPOSED',
        },
        {
            'title': 'Madurai South & Villapuram Automated LED Streetlighting & Feeder Pillar Overhaul',
            'sector': 'Streetlighting & Energy Efficiency',
            'affected_zones': [4],
            'affected_wards': [72, 75],
            'complaint_cluster_count': 19,
            'problem_statement': 'High non-functional streetlight frequency due to legacy unmetered junction boxes in south zone outskirts.',
            'proposed_solution': '3,200 smart LED luminaires with centralized CCMS (Centralized Control and Monitoring System) and astronomical timer switches.',
            'estimated_budget_inr': 45000000.00,
            'priority_score': 81.5,
            'ai_rationale': 'Streetlight outage complaints in Zone 4 South Ward 72 identified as safety concern.',
            'status': 'PROPOSED',
        },
    ]

    for pdata in madurai_projects:
        is_pl = pdata.pop('is_planned', False)
        rec, _ = CapitalProjectRecommendation.objects.update_or_create(
            cluster=cluster,
            title=pdata['title'],
            defaults={**pdata, 'is_planned': is_pl}
        )

    # 2. Categories & Sample Complaints
    cat_specs = [
        ('ROADS', 'RDS-POT', 'Pothole & Asphalt Repair', 48),
        ('HEALTH', 'HLT-SAN', 'Public Sanitation & Fogging', 24),
        ('SWM', 'SWM-CLR', 'Garbage Clearance & Segregation', 24),
        ('SWD', 'SWD-DRN', 'Stormwater Drain Desilting', 36),
        ('WATER', 'WTR-SUP', 'Drinking Water Pipeline Supply', 24),
        ('LIGHTS', 'LGT-FIX', 'Streetlight Maintenance', 24),
    ]
    cats = {}
    for dcode, ccode, cname, sla in cat_specs:
        dept = depts_map[dcode]
        c, _ = GrievanceCategory.objects.get_or_create(
            cluster=cluster,
            code=ccode,
            defaults={'department': dept, 'name': cname, 'sla_hours': sla}
        )
        cats[ccode] = c

    madurai_complaints = [
        {
            'title': 'Severe Stormwater Drain Clog near Sellur Vaigai Bank',
            'desc': 'Drainage water overflowing onto North bank arterial road following evening rain. DIGIPIN 39M2-R4-T1.',
            'lat': 9.9380, 'lng': 78.1250, 'znum': 1, 'wnum': 12, 'dcode': 'SWD', 'ccode': 'SWD-DRN',
            'severity': 'HIGH', 'status': 'IN_PROGRESS', 'is_sla_breached': True
        },
        {
            'title': 'Garbage Pileup along Goripalayam Junction Bypass',
            'desc': 'Commercial solid waste accumulated for two days near flower market crossing. Odor affecting pedestrians.',
            'lat': 9.9320, 'lng': 78.1320, 'znum': 1, 'wnum': 15, 'dcode': 'SWM', 'ccode': 'SWM-CLR',
            'severity': 'MEDIUM', 'status': 'ASSIGNED', 'is_sla_breached': False
        },
        {
            'title': 'Deep Asphalt Potholes on Arapalayam Main Bus Road',
            'desc': 'Multiple deep craters outside Arapalayam terminal causing vehicle damage and traffic slow-downs.',
            'lat': 9.9350, 'lng': 78.1050, 'znum': 2, 'wnum': 32, 'dcode': 'ROADS', 'ccode': 'RDS-POT',
            'severity': 'HIGH', 'status': 'FIELD_VERIFICATION', 'is_sla_breached': False
        },
        {
            'title': 'Commercial Waste Bins Overflowing on South Masi Street',
            'desc': 'High market volume near textile showrooms overflowing onto pavement. Needs immediate clearance drive.',
            'lat': 9.9160, 'lng': 78.1220, 'znum': 3, 'wnum': 54, 'dcode': 'SWM', 'ccode': 'SWM-CLR',
            'severity': 'MEDIUM', 'status': 'RESOLVED', 'is_sla_breached': False
        },
        {
            'title': 'Dark Stretch - 6 Streetlights Out along Villapuram Rail Road',
            'desc': 'Entire row of sodium lights non-operational between junction pillar 14 and 18. Public safety hazard.',
            'lat': 9.8980, 'lng': 78.1150, 'znum': 4, 'wnum': 72, 'dcode': 'LIGHTS', 'ccode': 'LGT-FIX',
            'severity': 'HIGH', 'status': 'ASSIGNED', 'is_sla_breached': True
        },
        {
            'title': 'Drain Wall Cracking & Debris Blockage near Mattuthavani Market',
            'desc': 'Stormwater conduit broken near vegetable market exit. Water stagnant and breeding mosquitoes.',
            'lat': 9.9450, 'lng': 78.1520, 'znum': 5, 'wnum': 88, 'dcode': 'SWD', 'ccode': 'SWD-DRN',
            'severity': 'HIGH', 'status': 'INVESTIGATING', 'is_sla_breached': False
        },
    ]

    for idx, cdata in enumerate(madurai_complaints, start=2):
        tnum = f"DPIG-2026-MMC-{idx:06d}"
        if not Complaint.objects.filter(ticket_number=tnum).exists():
            z = zones_map[cdata['znum']]
            w = wards_map[cdata['wnum']]
            d = depts_map[cdata['dcode']]
            c = cats[cdata['ccode']]
            dpin = format_digipin(encode_digipin(cdata['lat'], cdata['lng'], precision=10))

            Complaint.objects.create(
                ticket_number=tnum,
                cluster=cluster,
                zone=z,
                ward=w,
                department=d,
                category=c,
                title=cdata['title'],
                description=cdata['desc'],
                citizen_name="Madurai Resident Citizen",
                citizen_phone="9840199999",
                latitude=cdata['lat'],
                longitude=cdata['lng'],
                digipin=dpin,
                address_landmark=f"{w.name}, Zone {z.number}, Madurai",
                severity=cdata['severity'],
                status=cdata['status'],
                is_sla_breached=cdata['is_sla_breached'],
            )


class Command(BaseCommand):
    help = 'Provisions all 15 Madurai Municipal Corporation official users with credentials and seeds civic data.'

    def handle(self, *args, **options):
        self.stdout.write("Provisioning Madurai Municipal Corporation Officers & Civic Data...")
        results = provision_madurai_officers()
        for r in results:
            status = "Created" if r['created'] else "Updated/Verified"
            self.stdout.write(self.style.SUCCESS(
                f"  [{r['role']}] {r['email']} (user: {r['username']}) -> {r['designation']} [{status}]"
            ))
        self.stdout.write(self.style.SUCCESS(f"\nSuccessfully provisioned {len(results)} Madurai officers and seeded cluster intelligence."))

