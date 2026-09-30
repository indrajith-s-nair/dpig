"""
Script to generate the Google-Sheets-ready Greater Chennai Corporation (GCC)
workbook template (XLSX) and accompanying CSV files.
"""
import os
import pandas as pd
from core.digipin import encode as encode_digipin, format_digipin

os.makedirs('templates_data/csv_sheets', exist_ok=True)

# 1. Cluster Profile
profile_data = [{
    'cluster_code': 'GCC',
    'cluster_name': 'Greater Chennai Corporation',
    'cluster_type': 'MUNICIPAL_CORP',
    'state': 'Tamil Nadu',
    'headquarters_lat': 13.0827,
    'headquarters_lng': 80.2707,
    'commissioner_name': 'J. Kumaragurubaran IAS',
    'contact_email': 'commissioner@chennaicorporation.gov.in',
    'emergency_helpline': '1234',
    'description': 'Greater Chennai Corporation is the civic body that governs the metropolis of Chennai, Tamil Nadu.'
}]
df_profile = pd.DataFrame(profile_data)

# 2. Zones (15 Zones of GCC)
zones_raw = [
    (1, "Thiruvottiyur", "High Court Rd, Thiruvottiyur", 13.1600, 80.3000, "Dr. K. Senthil", "zo1@chennaicorp.gov.in", "044-25732101"),
    (2, "Manali", "Market Road, Manali", 13.1700, 80.2600, "Thiru. R. Murugan", "zo2@chennaicorp.gov.in", "044-25941072"),
    (3, "Madhavaram", "Redhills Rd, Madhavaram", 13.1480, 80.2310, "Tmt. S. Gomathi", "zo3@chennaicorp.gov.in", "044-25530172"),
    (4, "Tondiarpet", "G.A. Road, Tondiarpet", 13.1250, 80.2850, "Thiru. P. Arumugam", "zo4@chennaicorp.gov.in", "044-25912345"),
    (5, "Royapuram", "Basin Bridge Rd, Royapuram", 13.1090, 80.2940, "Dr. M. Suresh", "zo5@chennaicorp.gov.in", "044-25952134"),
    (6, "Thiru Vi Ka Nagar", "Strahans Road, Pattalam", 13.1080, 80.2450, "Thiru. G. Jayaraman", "zo6@chennaicorp.gov.in", "044-26620194"),
    (7, "Ambattur", "CTH Road, Ambattur", 13.1140, 80.1540, "Tmt. A. Revathi", "zo7@chennaicorp.gov.in", "044-26581234"),
    (8, "Anna Nagar", "2nd Avenue, Anna Nagar", 13.0850, 80.2100, "Thiru. N. Balachandar", "zo8@chennaicorp.gov.in", "044-26151234"),
    (9, "Teynampet", "Eldams Road, Teynampet", 13.0400, 80.2500, "Dr. V. Kavitha", "zo9@chennaicorp.gov.in", "044-24341234"),
    (10, "Kodambakkam", "Arcot Road, Kodambakkam", 13.0520, 80.2250, "Thiru. S. Natarajan", "zo10@chennaicorp.gov.in", "044-24801234"),
    (11, "Valasaravakkam", "Arcot Road, Valasaravakkam", 13.0400, 80.1700, "Tmt. P. Jayashree", "zo11@chennaicorp.gov.in", "044-24861234"),
    (12, "Alandur", "GST Road, Alandur", 13.0030, 80.2000, "Thiru. K. Rajendran", "zo12@chennaicorp.gov.in", "044-22341234"),
    (13, "Adyar", "L.B. Road, Adyar", 13.0060, 80.2570, "Dr. R. Anitha", "zo13@chennaicorp.gov.in", "044-24421234"),
    (14, "Perungudi", "OMR, Perungudi", 12.9650, 80.2400, "Thiru. T. Dinesh", "zo14@chennaicorp.gov.in", "044-24961234"),
    (15, "Sholinganallur", "ECR, Sholinganallur", 12.8990, 80.2270, "Tmt. M. Geetha", "zo15@chennaicorp.gov.in", "044-24501234"),
]
zones_data = [{
    'zone_number': z[0], 'zone_name': z[1], 'hq_address': z[2],
    'hq_lat': z[3], 'hq_lng': z[4], 'zonal_officer_name': z[5],
    'zonal_officer_email': z[6], 'zonal_officer_phone': z[7]
} for z in zones_raw]
df_zones = pd.DataFrame(zones_data)

# 3. Wards (All 200 Wards mapped to 15 Zones)
zone_ward_ranges = [
    (1, 1, 14, 13.1600, 80.3000),
    (2, 15, 21, 13.1700, 80.2600),
    (3, 22, 33, 13.1480, 80.2310),
    (4, 34, 48, 13.1250, 80.2850),
    (5, 49, 63, 13.1090, 80.2940),
    (6, 64, 78, 13.1080, 80.2450),
    (7, 79, 93, 13.1140, 80.1540),
    (8, 94, 108, 13.0850, 80.2100),
    (9, 109, 126, 13.0400, 80.2500),
    (10, 127, 142, 13.0520, 80.2250),
    (11, 143, 155, 13.0400, 80.1700),
    (12, 156, 167, 13.0030, 80.2000),
    (13, 168, 180, 13.0060, 80.2570),
    (14, 181, 191, 12.9650, 80.2400),
    (15, 192, 200, 12.8990, 80.2270),
]

wards_data = []
for z_num, start_w, end_w, base_lat, base_lng in zone_ward_ranges:
    for w in range(start_w, end_w + 1):
        offset = (w - start_w) * 0.003
        w_lat = round(base_lat + (offset if (w % 2 == 0) else -offset), 6)
        w_lng = round(base_lng + (offset if (w % 3 == 0) else -offset), 6)
        dp = format_digipin(encode_digipin(w_lat, w_lng, precision=6))
        wards_data.append({
            'ward_number': w,
            'zone_number': z_num,
            'ward_name': f"Ward {w} - Locality {chr(65 + (w % 26))}",
            'centroid_lat': w_lat,
            'centroid_lng': w_lng,
            'digipin_prefix': dp,
            'area_sq_km': round(1.2 + (w % 5) * 0.3, 2)
        })
df_wards = pd.DataFrame(wards_data)

# 4. Departments
depts_raw = [
    ('SWM', 'Solid Waste Management', 'Door-to-door garbage collection, micro-composting, street sweeping, dump yards', 'Dr. N. Mahesan', 'swm@chennaicorp.gov.in', '044-25381234', 24),
    ('SWD', 'Storm Water Drains', 'Rainwater conduits, macro & micro drain maintenance, flood pump operations', 'Thiru. S. Rajendran', 'swd@chennaicorp.gov.in', '044-25382345', 12),
    ('ROADS', 'Roads, Bridges & Footpaths', 'Bituminous road laying, pothole patching, pedestrian pathways, bridges', 'Thiru. K. Murugesan', 'roads@chennaicorp.gov.in', '044-25383456', 48),
    ('LIGHTS', 'Street Lights & Electrical', 'LED street lighting, smart feeder pillars, electrical safety', 'Tmt. R. Sumathi', 'lights@chennaicorp.gov.in', '044-25384567', 24),
    ('HEALTH', 'Public Health & Vector Control', 'Mosquito fogging, disease surveillance, rabies control, birth/death registry', 'Dr. M. Jagadeesan', 'health@chennaicorp.gov.in', '044-25385678', 24),
    ('PARKS', 'Parks & Playgrounds', 'Public park landscaping, gym equipment maintenance, tree pruning', 'Thiru. V. Shanmugam', 'parks@chennaicorp.gov.in', '044-25386789', 72),
    ('REVENUE', 'Revenue & Assessments', 'Property tax assessment, trade license, professional tax collection', 'Tmt. C. Jayanthi', 'revenue@chennaicorp.gov.in', '044-25387890', 96),
    ('WATER', 'Water Supply & Sewage Liaison', 'Coordination with CMWSSB for drinking water contamination & sewage overflows', 'Thiru. P. Ramesh', 'water@chennaicorp.gov.in', '044-25388901', 24),
]
depts_data = [{
    'dept_code': d[0], 'dept_name': d[1], 'description': d[2],
    'head_officer': d[3], 'contact_email': d[4], 'phone': d[5],
    'standard_sla_hours': d[6]
} for d in depts_raw]
df_depts = pd.DataFrame(depts_data)

# 5. Officers & Staff
staff_data = [
    {'staff_id': 'STAFF-001', 'full_name': 'J. Kumaragurubaran IAS', 'email': 'commissioner@chennaicorp.gov.in', 'phone': '9840011111', 'role': 'COMMISSIONER', 'assigned_zone': 0, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Principal Secretary / Commissioner'},
    {'staff_id': 'STAFF-002', 'full_name': 'Dr. K. Senthil', 'email': 'zo1@chennaicorp.gov.in', 'phone': '9840011101', 'role': 'ZONAL_OFFICER', 'assigned_zone': 1, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Thiruvottiyur'},
    {'staff_id': 'STAFF-003', 'full_name': 'Thiru. R. Murugan', 'email': 'zo2@chennaicorp.gov.in', 'phone': '9840011102', 'role': 'ZONAL_OFFICER', 'assigned_zone': 2, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Manali'},
    {'staff_id': 'STAFF-004', 'full_name': 'Tmt. S. Gomathi', 'email': 'zo3@chennaicorp.gov.in', 'phone': '9840011103', 'role': 'ZONAL_OFFICER', 'assigned_zone': 3, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Madhavaram'},
    {'staff_id': 'STAFF-005', 'full_name': 'Thiru. P. Arumugam', 'email': 'zo4@chennaicorp.gov.in', 'phone': '9840011104', 'role': 'ZONAL_OFFICER', 'assigned_zone': 4, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Tondiarpet'},
    {'staff_id': 'STAFF-006', 'full_name': 'Dr. M. Suresh', 'email': 'zo5@chennaicorp.gov.in', 'phone': '9840011105', 'role': 'ZONAL_OFFICER', 'assigned_zone': 5, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Royapuram'},
    {'staff_id': 'STAFF-007', 'full_name': 'Thiru. G. Jayaraman', 'email': 'zo6@chennaicorp.gov.in', 'phone': '9840011106', 'role': 'ZONAL_OFFICER', 'assigned_zone': 6, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Thiru Vi Ka Nagar'},
    {'staff_id': 'STAFF-008', 'full_name': 'Tmt. A. Revathi', 'email': 'zo7@chennaicorp.gov.in', 'phone': '9840011107', 'role': 'ZONAL_OFFICER', 'assigned_zone': 7, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Ambattur'},
    {'staff_id': 'STAFF-009', 'full_name': 'Thiru. N. Balachandar', 'email': 'zo8@chennaicorp.gov.in', 'phone': '9840011108', 'role': 'ZONAL_OFFICER', 'assigned_zone': 8, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Anna Nagar'},
    {'staff_id': 'STAFF-010', 'full_name': 'Dr. V. Kavitha', 'email': 'zo9@chennaicorp.gov.in', 'phone': '9840011109', 'role': 'ZONAL_OFFICER', 'assigned_zone': 9, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Teynampet'},
    {'staff_id': 'STAFF-011', 'full_name': 'Thiru. S. Natarajan', 'email': 'zo10@chennaicorp.gov.in', 'phone': '9840011110', 'role': 'ZONAL_OFFICER', 'assigned_zone': 10, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Zonal Officer - Kodambakkam'},
    {'staff_id': 'STAFF-012', 'full_name': 'K. Anbarasan AE', 'email': 'ae.ward108@chennaicorp.gov.in', 'phone': '9840022108', 'role': 'WARD_OFFICER', 'assigned_zone': 8, 'assigned_ward': 108, 'assigned_department': 'ROADS', 'designation': 'Assistant Engineer - Ward 108'},
    {'staff_id': 'STAFF-013', 'full_name': 'M. Vignesh AE', 'email': 'ae.ward142@chennaicorp.gov.in', 'phone': '9840022142', 'role': 'WARD_OFFICER', 'assigned_zone': 10, 'assigned_ward': 142, 'assigned_department': 'SWD', 'designation': 'Assistant Engineer - Ward 142'},
    {'staff_id': 'STAFF-014', 'full_name': 'S. Lakshmi SI', 'email': 'si.ward52@chennaicorp.gov.in', 'phone': '9840022052', 'role': 'FIELD_STAFF', 'assigned_zone': 5, 'assigned_ward': 52, 'assigned_department': 'SWM', 'designation': 'Sanitary Inspector - Ward 52'},
    {'staff_id': 'STAFF-015', 'full_name': 'State Policy Analyst', 'email': 'policy.analyst@tn.gov.in', 'phone': '9840033001', 'role': 'POLICYMAKER', 'assigned_zone': 0, 'assigned_ward': 0, 'assigned_department': '', 'designation': 'Lead Urban Governance Analyst'},
]
df_staff = pd.DataFrame(staff_data)

# 6. Categories & SLAs
cats_raw = [
    ('POTHOLE', 'Road Pothole Repair', 'ROADS', 'MEDIUM', 36, 12, 24, 48),
    ('ROAD_CAVEIN', 'Road Cave-in / Collapse', 'ROADS', 'CRITICAL', 6, 2, 4, 8),
    ('FOOTPATH_DAMAGED', 'Damaged Footpath / Missing Paver', 'ROADS', 'LOW', 72, 24, 48, 96),
    ('GARBAGE_OVERFLOW', 'Overflowing Garbage Bin / Blackspot', 'SWM', 'HIGH', 12, 4, 8, 24),
    ('GARBAGE_COLLECTION', 'Door to Door Collection Missed', 'SWM', 'MEDIUM', 24, 8, 16, 36),
    ('DEAD_ANIMAL', 'Removal of Dead Animals', 'SWM', 'CRITICAL', 6, 2, 4, 12),
    ('DEBRIS_DUMPING', 'Illegal C&D Debris Dumping', 'SWM', 'MEDIUM', 48, 16, 32, 72),
    ('WATERLOGGING', 'Rainwater Stagnation / Waterlogging', 'SWD', 'HIGH', 12, 4, 8, 24),
    ('DRAIN_CLOGGED', 'Stormwater Drain Silt / Clogged Drain', 'SWD', 'MEDIUM', 24, 8, 16, 48),
    ('MANHOLE_OPEN', 'Open or Broken Drain / Manhole Cover', 'SWD', 'CRITICAL', 6, 2, 4, 8),
    ('STREETLIGHT_OUT', 'Street Light Non-Functional', 'LIGHTS', 'MEDIUM', 24, 8, 16, 48),
    ('POLE_DAMAGED', 'Damaged Electric Pole / Dangling Wire', 'LIGHTS', 'CRITICAL', 6, 2, 4, 12),
    ('LIGHTS_DAYTIME', 'Street Lights Burning in Daytime', 'LIGHTS', 'LOW', 24, 8, 16, 48),
    ('MOSQUITO_BREEDING', 'Mosquito Menace & Fogging Request', 'HEALTH', 'MEDIUM', 24, 8, 16, 48),
    ('STRAY_DOGS', 'Stray Dog Control & Vaccination', 'HEALTH', 'MEDIUM', 72, 24, 48, 96),
    ('CONTAMINATED_WATER', 'Contaminated Drinking Water Supply', 'WATER', 'CRITICAL', 12, 4, 8, 24),
    ('SEWAGE_OVERFLOW', 'Underground Sewage Overflow on Road', 'WATER', 'HIGH', 18, 6, 12, 36),
    ('PARK_MAINTENANCE', 'Park Cleaning & Play Equipment Repair', 'PARKS', 'LOW', 72, 24, 48, 120),
    ('TREE_FALLEN', 'Fallen Tree / Dangerous Overhanging Branch', 'PARKS', 'HIGH', 12, 4, 8, 24),
    ('PROPERTY_TAX', 'Property Tax Assessment / Name Transfer Issue', 'REVENUE', 'LOW', 96, 36, 72, 144),
]
cats_data = [{
    'category_code': c[0], 'category_name': c[1], 'dept_code': c[2],
    'default_severity': c[3], 'sla_hours': c[4], 'escalation_l1_hours': c[5],
    'escalation_l2_hours': c[6], 'escalation_l3_hours': c[7]
} for c in cats_raw]
df_cats = pd.DataFrame(cats_data)

# 7. Broadcast Services
broadcasts_data = [
    {
        'broadcast_type': 'ALERT',
        'title': 'Monsoon Cyclone Preparedness & 24x7 Control Room',
        'description': 'Residents are advised that 169 relief centers and 850 dewatering motor pumps are deployed across all 15 zones. For waterlogging emergencies or fallen trees, dial 1234.',
        'target_audience': 'All Chennai Residents',
        'priority': 'EMERGENCY',
        'scheme_url': 'https://chennaicorporation.gov.in/gcc/monsoon'
    },
    {
        'broadcast_type': 'WELFARE_SCHEME',
        'title': 'Kalaignar Magalir Urimai Thittam (KMUT)',
        'description': 'Monthly basic income support of ₹1,000 for women heads of households. Apply or verify your Aadhaar-linked status at your respective Ward Zonal e-Seva centers.',
        'target_audience': 'Women Residents',
        'priority': 'NORMAL',
        'scheme_url': 'https://kmut.tn.gov.in'
    },
    {
        'broadcast_type': 'WELFARE_SCHEME',
        'title': "Chief Minister's Comprehensive Health Insurance Scheme (CMCHIS)",
        'description': 'Free cashless medical treatment up to ₹5 Lakhs per family per year across 1,027 empaneled government and private hospitals in Chennai and Tamil Nadu.',
        'target_audience': 'Low & Middle Income Families',
        'priority': 'HIGH',
        'scheme_url': 'https://cmchistn.com'
    },
    {
        'broadcast_type': 'CIVIC_GUIDANCE',
        'title': 'Mandatory Source Segregation of Solid Waste',
        'description': 'Please hand over segregated wet waste (green bin) and dry recyclable waste (blue bin) to GCC battery-operated vehicle (BOV) operators. Unsegregated garbage will attract penalties under SWM Bye-laws.',
        'target_audience': 'All Households & Commercial Establishments',
        'priority': 'NORMAL',
        'scheme_url': 'https://chennaicorporation.gov.in/gcc/swm'
    },
    {
        'broadcast_type': 'ADVISORY',
        'title': 'Early Bird Rebate on Property Tax Assessment',
        'description': 'Pay your half-yearly property tax within the first 15 days of the assessment period to avail a 5% incentive rebate (up to ₹5,000). Pay online without service charges.',
        'target_audience': 'Property Owners',
        'priority': 'NORMAL',
        'scheme_url': 'https://chennaicorporation.gov.in/gcc/online-payment'
    }
]
df_broadcasts = pd.DataFrame(broadcasts_data)

# Export Master Excel Workbook
excel_path = 'templates_data/gcc_government_cluster_template.xlsx'
with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
    df_profile.to_excel(writer, sheet_name='01_Cluster_Profile', index=False)
    df_zones.to_excel(writer, sheet_name='02_Zones', index=False)
    df_wards.to_excel(writer, sheet_name='03_Wards', index=False)
    df_depts.to_excel(writer, sheet_name='04_Departments', index=False)
    df_staff.to_excel(writer, sheet_name='05_Officers_Staff', index=False)
    df_cats.to_excel(writer, sheet_name='06_Categories_SLAs', index=False)
    df_broadcasts.to_excel(writer, sheet_name='07_Broadcast_Services', index=False)

# Export individual CSV files for Google Sheets import
df_profile.to_csv('templates_data/csv_sheets/01_Cluster_Profile.csv', index=False)
df_zones.to_csv('templates_data/csv_sheets/02_Zones.csv', index=False)
df_wards.to_csv('templates_data/csv_sheets/03_Wards.csv', index=False)
df_depts.to_csv('templates_data/csv_sheets/04_Departments.csv', index=False)
df_staff.to_csv('templates_data/csv_sheets/05_Officers_Staff.csv', index=False)
df_cats.to_csv('templates_data/csv_sheets/06_Categories_SLAs.csv', index=False)
df_broadcasts.to_csv('templates_data/csv_sheets/07_Broadcast_Services.csv', index=False)

print(f"Successfully generated Master Template: {excel_path}")
print("Generated 7 CSV files in templates_data/csv_sheets/")
