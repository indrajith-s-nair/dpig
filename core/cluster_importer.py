"""
Cluster Onboarding & Google Sheets / Excel Workbook Importer & Exporter.
Parses multi-tab workbooks (or bundled CSVs) and atomically provisions
a Local Government Cluster (Zones, Wards, Departments, Officers, Categories, SLAs).
Also provides bidirectional Excel export of active clusters and blank starter templates.
"""
import io
import os
import re
import logging
from typing import Dict, Any, Tuple, List, Optional
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from django.db import transaction
from django.contrib.auth.models import User
from core.models import Cluster, Zone, Ward, Department, GrievanceCategory, UserProfile, GovernmentBroadcast

logger = logging.getLogger(__name__)


def safe_int(val: Any, default: int = 0) -> int:
    """Safely parse integer from string, float, or mixed text without throwing ValueError."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        try:
            return int(val)
        except (ValueError, OverflowError):
            return default
    s = str(val).strip()
    if not s or s.lower() in ('nan', 'none', 'null', ''):
        return default
    try:
        return int(float(s))
    except (ValueError, TypeError):
        match = re.search(r'\d+', s)
        if match:
            try:
                return int(match.group())
            except ValueError:
                pass
        return default


def safe_float(val: Any, default: float = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
    """Safely parse float from string or number with optional bounds checking."""
    if val is None:
        res = default
    elif isinstance(val, (int, float)):
        try:
            res = float(val)
        except (ValueError, OverflowError):
            res = default
    else:
        s = str(val).strip()
        if not s or s.lower() in ('nan', 'none', 'null', ''):
            res = default
        else:
            try:
                res = float(s)
            except (ValueError, TypeError):
                res = default
    if min_val is not None and res < min_val:
        return default
    if max_val is not None and res > max_val:
        return default
    return res


def clean_str(val: Any, default: str = '') -> str:
    """Sanitize string values, stripping whitespace and filtering NaN/None strings."""
    if val is None:
        return default
    s = str(val).strip()
    return default if s.lower() in ('nan', 'none', 'null') else s


def import_cluster_from_excel(file_path_or_buffer) -> Dict[str, Any]:
    """
    Parses an Excel workbook (.xlsx) containing the 7 standardized sheets:
    1. 01_Cluster_Profile (or sheet matching 'profile' / 'cluster')
    2. 02_Zones (or sheet matching 'zone')
    3. 03_Wards (or sheet matching 'ward')
    4. 04_Departments (or sheet matching 'dept' / 'department')
    5. 05_Officers_Staff (or sheet matching 'staff' / 'officer' / 'personnel')
    6. 06_Categories_SLAs (or sheet matching 'cat' / 'sla' / 'grievance')
    7. 07_Broadcast_Services (or sheet matching 'broadcast' / 'service' / 'scheme')
    """
    xls = pd.ExcelFile(file_path_or_buffer)
    sheet_names = xls.sheet_names

    def get_df(keywords):
        if isinstance(keywords, str):
            keywords = [keywords]
        for s in sheet_names:
            s_lower = s.lower().strip()
            for kw in keywords:
                kw_lower = kw.lower().strip()
                if s_lower.startswith(kw_lower) or kw_lower in s_lower:
                    try:
                        return pd.read_excel(xls, sheet_name=s).fillna('')
                    except Exception as e:
                        logger.warning(f"Error reading sheet {s}: {e}")
                        return pd.DataFrame()
        return pd.DataFrame()

    df_profile = get_df(['01', 'profile', 'cluster'])
    df_zones = get_df(['02', 'zone'])
    df_wards = get_df(['03', 'ward'])
    df_depts = get_df(['04', 'dept', 'department'])
    df_staff = get_df(['05', 'staff', 'officer', 'personnel'])
    df_cats = get_df(['06', 'cat', 'sla', 'grievance'])
    df_broadcasts = get_df(['07', 'broadcast', 'service', 'scheme', 'alert'])

    return _process_cluster_data(
        df_profile, df_zones, df_wards, df_depts, df_staff, df_cats, df_broadcasts
    )


@transaction.atomic
def _process_cluster_data(
    df_profile: pd.DataFrame,
    df_zones: pd.DataFrame,
    df_wards: pd.DataFrame,
    df_depts: pd.DataFrame,
    df_staff: pd.DataFrame,
    df_cats: pd.DataFrame,
    df_broadcasts: pd.DataFrame
) -> Dict[str, Any]:
    """Atomically executes database creation for all entities in the cluster with full error resilience."""
    if df_profile.empty:
        raise ValueError("Sheet '01_Cluster_Profile' (or profile sheet) is missing or empty.")

    warnings: List[str] = []

    p_row = df_profile.iloc[0]
    code = clean_str(p_row.get('cluster_code', 'GCC'), 'GCC').upper()
    name = clean_str(p_row.get('cluster_name', 'Greater Chennai Corporation'), 'Greater Chennai Corporation')
    c_type = clean_str(p_row.get('cluster_type', 'MUNICIPAL_CORP'), 'MUNICIPAL_CORP').upper()
    state = clean_str(p_row.get('state', 'Tamil Nadu'), 'Tamil Nadu')
    lat = safe_float(p_row.get('headquarters_lat', 13.0827), default=13.0827, min_val=-90.0, max_val=90.0)
    lng = safe_float(p_row.get('headquarters_lng', 80.2707), default=80.2707, min_val=-180.0, max_val=180.0)
    comm_name = clean_str(p_row.get('commissioner_name', 'Commissioner IAS'), 'Commissioner IAS')
    email = clean_str(p_row.get('contact_email', 'commissioner@chennaicorporation.gov.in'), 'commissioner@chennaicorporation.gov.in')
    helpline = clean_str(p_row.get('emergency_helpline', '1913'), '1913')

    cluster, created = Cluster.objects.update_or_create(
        code=code,
        defaults={
            'name': name,
            'cluster_type': c_type,
            'state': state,
            'headquarters_lat': lat,
            'headquarters_lng': lng,
            'commissioner_name': comm_name,
            'contact_email': email,
            'emergency_helpline': helpline,
            'is_active': True,
        }
    )

    # 1. Provision Zones
    zones_map = {}
    zones_count = 0
    if not df_zones.empty:
        for idx, zrow in df_zones.iterrows():
            z_num = safe_int(zrow.get('zone_number', 0))
            if not z_num:
                if any(clean_str(zrow.get(k)) for k in zrow.keys() if k != 'zone_number'):
                    warnings.append(f"Zones sheet row {idx + 2}: Skipped due to missing or invalid zone_number.")
                continue
            z_name = clean_str(zrow.get('zone_name'), f'Zone {z_num}')
            hq_addr = clean_str(zrow.get('hq_address'))
            hq_lat = safe_float(zrow.get('hq_lat', lat), default=lat, min_val=-90.0, max_val=90.0)
            hq_lng = safe_float(zrow.get('hq_lng', lng), default=lng, min_val=-180.0, max_val=180.0)
            zo_name = clean_str(zrow.get('zonal_officer_name'))
            zo_email = clean_str(zrow.get('zonal_officer_email'))
            zo_phone = clean_str(zrow.get('zonal_officer_phone'))

            zone, _ = Zone.objects.update_or_create(
                cluster=cluster,
                number=z_num,
                defaults={
                    'name': z_name,
                    'hq_address': hq_addr,
                    'hq_lat': hq_lat,
                    'hq_lng': hq_lng,
                    'zonal_officer_name': zo_name,
                    'zonal_officer_email': zo_email,
                    'zonal_officer_phone': zo_phone,
                }
            )
            zones_map[z_num] = zone
            zones_count += 1

    # 2. Provision Wards
    wards_map = {}
    wards_count = 0
    if not df_wards.empty:
        for idx, wrow in df_wards.iterrows():
            w_num = safe_int(wrow.get('ward_number', 0))
            z_num = safe_int(wrow.get('zone_number', 1), default=1)
            if not w_num:
                if any(clean_str(wrow.get(k)) for k in wrow.keys() if k != 'ward_number'):
                    warnings.append(f"Wards sheet row {idx + 2}: Skipped due to missing ward_number.")
                continue
            if z_num not in zones_map:
                warnings.append(f"Wards sheet row {idx + 2} (Ward {w_num}): Referenced Zone {z_num} not found. Skipped.")
                continue
            w_name = clean_str(wrow.get('ward_name'), f'Ward {w_num}')
            w_lat = safe_float(wrow.get('centroid_lat', lat), default=lat, min_val=-90.0, max_val=90.0)
            w_lng = safe_float(wrow.get('centroid_lng', lng), default=lng, min_val=-180.0, max_val=180.0)
            digipin_pfx = clean_str(wrow.get('digipin_prefix'))
            area = safe_float(wrow.get('area_sq_km', 1.5), default=1.5, min_val=0.01)

            ward, _ = Ward.objects.update_or_create(
                zone=zones_map[z_num],
                number=w_num,
                defaults={
                    'name': w_name,
                    'centroid_lat': w_lat,
                    'centroid_lng': w_lng,
                    'digipin_prefix': digipin_pfx,
                    'area_sq_km': area,
                }
            )
            wards_map[w_num] = ward
            wards_count += 1

    # 3. Provision Departments
    depts_map = {}
    depts_count = 0
    if not df_depts.empty:
        for idx, drow in df_depts.iterrows():
            d_code = clean_str(drow.get('dept_code')).upper()
            if not d_code:
                if any(clean_str(drow.get(k)) for k in drow.keys() if k != 'dept_code'):
                    warnings.append(f"Departments sheet row {idx + 2}: Skipped due to missing dept_code.")
                continue
            d_name = clean_str(drow.get('dept_name'), d_code)
            d_desc = clean_str(drow.get('description'))
            d_head = clean_str(drow.get('head_officer'))
            d_email = clean_str(drow.get('contact_email'))
            d_phone = clean_str(drow.get('phone'))
            d_sla = safe_int(drow.get('standard_sla_hours', 24), default=24)
            if d_sla <= 0:
                d_sla = 24

            dept, _ = Department.objects.update_or_create(
                cluster=cluster,
                code=d_code,
                defaults={
                    'name': d_name,
                    'description': d_desc,
                    'head_officer': d_head,
                    'contact_email': d_email,
                    'phone': d_phone,
                    'standard_sla_hours': d_sla,
                }
            )
            depts_map[d_code] = dept
            depts_count += 1

    # 4. Provision Grievance Categories & SLAs
    cats_count = 0
    if not df_cats.empty:
        for idx, crow in df_cats.iterrows():
            c_code = clean_str(crow.get('category_code')).upper()
            d_code = clean_str(crow.get('dept_code')).upper()
            if not c_code:
                continue
            if d_code not in depts_map:
                warnings.append(f"Categories sheet row {idx + 2} ({c_code}): Department code '{d_code}' not found in cluster. Skipped.")
                continue
            c_name = clean_str(crow.get('category_name'), c_code)
            c_sev = clean_str(crow.get('default_severity'), 'MEDIUM').upper()
            if c_sev not in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
                c_sev = 'MEDIUM'
            c_sla = safe_int(crow.get('sla_hours', 24), default=24)
            l1 = safe_int(crow.get('escalation_l1_hours', 12), default=max(1, c_sla // 2))
            l2 = safe_int(crow.get('escalation_l2_hours', 24), default=c_sla)
            l3 = safe_int(crow.get('escalation_l3_hours', 48), default=c_sla * 2)

            GrievanceCategory.objects.update_or_create(
                cluster=cluster,
                code=c_code,
                defaults={
                    'department': depts_map[d_code],
                    'name': c_name,
                    'default_severity': c_sev,
                    'sla_hours': c_sla,
                    'escalation_l1_hours': l1,
                    'escalation_l2_hours': l2,
                    'escalation_l3_hours': l3,
                }
            )
            cats_count += 1

    # 5. Provision Officers & Staff User Accounts
    staff_count = 0
    if not df_staff.empty:
        for idx, srow in df_staff.iterrows():
            s_email = clean_str(srow.get('email'))
            if not s_email or '@' not in s_email:
                if any(clean_str(srow.get(k)) for k in srow.keys() if k != 'email'):
                    warnings.append(f"Staff sheet row {idx + 2}: Skipped due to invalid email '{s_email}'.")
                continue
            s_name = clean_str(srow.get('full_name'))
            s_role = clean_str(srow.get('role', 'WARD_OFFICER'), 'WARD_OFFICER').upper()
            s_phone = clean_str(srow.get('phone'))
            s_desig = clean_str(srow.get('designation', s_role), s_role)
            s_znum = safe_int(srow.get('assigned_zone', 0))
            s_wnum = safe_int(srow.get('assigned_ward', 0))
            s_dcode = clean_str(srow.get('assigned_department')).upper()

            raw_username = clean_str(srow.get('username') or srow.get('staff_id'))
            if not raw_username or raw_username.startswith('STAFF-'):
                raw_username = s_email.split('@')[0]
            username = re.sub(r'[^a-zA-Z0-9_.]', '_', raw_username).lower()

            user = User.objects.filter(username=username).first()
            if not user:
                user_by_email = User.objects.filter(email=s_email).first()
                if user_by_email:
                    user = user_by_email
                else:
                    first_n = s_name.split()[0] if s_name else username
                    last_n = " ".join(s_name.split()[1:]) if len(s_name.split()) > 1 else ""
                    pwd = clean_str(srow.get('password')) or 'Admin@Dpig2026'
                    user = User.objects.create_user(
                        username=username,
                        email=s_email,
                        first_name=first_n,
                        last_name=last_n,
                        password=pwd
                    )
                    user.is_staff = True
                    user.is_superuser = (s_role == 'SUPERADMIN')
                    user.save()
            else:
                if s_name:
                    user.first_name = s_name.split()[0]
                    user.last_name = " ".join(s_name.split()[1:]) if len(s_name.split()) > 1 else ""
                user.email = s_email
                user.is_staff = True
                user.is_superuser = (s_role == 'SUPERADMIN')
                user.save()

            # Determine hierarchy level (1: DL1 to 7: CM_OFFICE)
            h_level = 1
            wf_input = clean_str(srow.get('workflow_level')).upper()
            from core.models import LEVEL_CODE_TO_INT
            if wf_input in LEVEL_CODE_TO_INT:
                h_level = LEVEL_CODE_TO_INT[wf_input]
            elif s_role == 'CM_OFFICE':
                h_level = 7
            elif s_role == 'COMMISSIONER':
                h_level = 6
            elif s_role == 'ZONAL_OFFICER':
                h_level = 3
            elif s_role in ['WARD_OFFICER', 'FIELD_STAFF']:
                h_level = 1

            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'cluster': cluster,
                    'role': s_role if s_role in dict(UserProfile.ROLES) else 'WARD_OFFICER',
                    'hierarchy_level': h_level,
                    'zone': zones_map.get(s_znum),
                    'ward': wards_map.get(s_wnum),
                    'department': depts_map.get(s_dcode),
                    'phone': s_phone,
                    'designation': s_desig,
                }
            )
            staff_count += 1

    # 6. Provision Initial Government Broadcasts
    broadcasts_count = 0
    if not df_broadcasts.empty:
        for idx, brow in df_broadcasts.iterrows():
            b_title = clean_str(brow.get('title'))
            if not b_title:
                continue
            b_type = clean_str(brow.get('broadcast_type', 'WELFARE_SCHEME'), 'WELFARE_SCHEME').upper()
            b_content = clean_str(brow.get('description'))
            b_audience = clean_str(brow.get('target_audience', 'All Citizens'), 'All Citizens')
            b_prio = clean_str(brow.get('priority', 'NORMAL'), 'NORMAL').upper()
            b_url = clean_str(brow.get('scheme_url'))

            GovernmentBroadcast.objects.update_or_create(
                cluster=cluster,
                title=b_title,
                defaults={
                    'broadcast_type': b_type if b_type in dict(GovernmentBroadcast.BROADCAST_TYPES) else 'WELFARE_SCHEME',
                    'content': b_content,
                    'target_audience': b_audience,
                    'priority': b_prio if b_prio in dict(GovernmentBroadcast.PRIORITY_LEVELS) else 'NORMAL',
                    'scheme_url': b_url,
                    'is_active': True,
                }
            )
            broadcasts_count += 1

    # Automatically provision Department Admins for all imported departments
    try:
        from core.dept_admin_service import ensure_department_admins
        ensure_department_admins(cluster)
    except Exception as e:
        logger.warning(f"Could not auto-provision department admins for {cluster}: {e}")

    return {
        'status': 'SUCCESS' if not warnings else 'PARTIAL',
        'cluster_id': cluster.id,
        'cluster_name': cluster.name,
        'cluster_code': cluster.code,
        'zones_count': zones_count,
        'wards_count': wards_count,
        'departments_count': depts_count,
        'categories_count': cats_count,
        'staff_count': staff_count,
        'broadcasts_count': broadcasts_count,
        'warnings': warnings,
    }


def _style_excel_sheet(ws, title_color="1E3A8A"):
    """Applies standardized government styling, frozen headers, and auto column widths."""
    header_fill = PatternFill(start_color=title_color, end_color=title_color, fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 26

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 14)


def export_cluster_to_excel(cluster_or_id: Any) -> bytes:
    """
    Exports a municipal cluster and its entire administrative hierarchy
    (Zones, Wards, Departments, Staff, Categories, Broadcasts) into a 7-sheet Excel workbook.
    """
    if isinstance(cluster_or_id, Cluster):
        cluster = cluster_or_id
    else:
        cluster = Cluster.objects.filter(id=cluster_or_id).first()
        if not cluster:
            cluster = Cluster.objects.filter(is_active=True).first()
        if not cluster:
            raise ValueError("No active Cluster found to export.")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    # 1. Sheet 01: Cluster Profile
    ws_profile = wb.create_sheet('01_Cluster_Profile')
    ws_profile.append([
        'cluster_code', 'cluster_name', 'cluster_type', 'state',
        'headquarters_lat', 'headquarters_lng', 'commissioner_name',
        'contact_email', 'emergency_helpline', 'description'
    ])
    ws_profile.append([
        cluster.code, cluster.name, cluster.cluster_type, cluster.state,
        cluster.headquarters_lat, cluster.headquarters_lng, cluster.commissioner_name,
        cluster.contact_email, cluster.emergency_helpline,
        f"Administrative registry export for {cluster.name} ({cluster.code})"
    ])
    _style_excel_sheet(ws_profile)

    # 2. Sheet 02: Zones
    ws_zones = wb.create_sheet('02_Zones')
    ws_zones.append([
        'zone_number', 'zone_name', 'hq_address', 'hq_lat', 'hq_lng',
        'zonal_officer_name', 'zonal_officer_email', 'zonal_officer_phone'
    ])
    zones = Zone.objects.filter(cluster=cluster).order_by('number')
    for z in zones:
        ws_zones.append([
            z.number, z.name, z.hq_address, z.hq_lat, z.hq_lng,
            z.zonal_officer_name, z.zonal_officer_email, z.zonal_officer_phone
        ])
    _style_excel_sheet(ws_zones)

    # 3. Sheet 03: Wards
    ws_wards = wb.create_sheet('03_Wards')
    ws_wards.append([
        'ward_number', 'zone_number', 'ward_name', 'centroid_lat', 'centroid_lng',
        'digipin_prefix', 'area_sq_km'
    ])
    wards = Ward.objects.filter(zone__cluster=cluster).select_related('zone').order_by('number')
    for w in wards:
        ws_wards.append([
            w.number, w.zone.number, w.name, w.centroid_lat, w.centroid_lng,
            w.digipin_prefix, w.area_sq_km
        ])
    _style_excel_sheet(ws_wards)

    # 4. Sheet 04: Departments
    ws_depts = wb.create_sheet('04_Departments')
    ws_depts.append([
        'dept_code', 'dept_name', 'description', 'head_officer',
        'contact_email', 'phone', 'standard_sla_hours'
    ])
    depts = Department.objects.filter(cluster=cluster).order_by('code')
    for d in depts:
        ws_depts.append([
            d.code, d.name, d.description, d.head_officer,
            d.contact_email, d.phone, d.standard_sla_hours
        ])
    _style_excel_sheet(ws_depts)

    # 5. Sheet 05: Officers Staff
    ws_staff = wb.create_sheet('05_Officers_Staff')
    ws_staff.append([
        'staff_id', 'full_name', 'email', 'phone', 'role', 'workflow_level',
        'assigned_zone', 'assigned_ward', 'assigned_department', 'designation'
    ])
    profiles = UserProfile.objects.filter(cluster=cluster).select_related(
        'user', 'zone', 'ward', 'department'
    ).order_by('hierarchy_level', 'user__username')
    from core.models import LEVEL_INT_TO_CODE
    for p in profiles:
        wf_code = LEVEL_INT_TO_CODE.get(p.hierarchy_level, 'DL1')
        full_n = p.user.get_full_name() or p.user.username
        ws_staff.append([
            p.user.username, full_n, p.user.email, p.phone, p.role, wf_code,
            p.zone.number if p.zone else '',
            p.ward.number if p.ward else '',
            p.department.code if p.department else '',
            p.designation
        ])
    _style_excel_sheet(ws_staff)

    # 6. Sheet 06: Categories & SLAs
    ws_cats = wb.create_sheet('06_Categories_SLAs')
    ws_cats.append([
        'category_code', 'category_name', 'dept_code', 'default_severity',
        'sla_hours', 'escalation_l1_hours', 'escalation_l2_hours', 'escalation_l3_hours'
    ])
    cats = GrievanceCategory.objects.filter(cluster=cluster).select_related('department').order_by('code')
    for c in cats:
        ws_cats.append([
            c.code, c.name, c.department.code, c.default_severity,
            c.sla_hours, c.escalation_l1_hours, c.escalation_l2_hours, c.escalation_l3_hours
        ])
    _style_excel_sheet(ws_cats)

    # 7. Sheet 07: Broadcast Services
    ws_broadcasts = wb.create_sheet('07_Broadcast_Services')
    ws_broadcasts.append([
        'broadcast_type', 'title', 'description', 'target_audience', 'priority', 'scheme_url'
    ])
    broadcasts = GovernmentBroadcast.objects.filter(cluster=cluster).order_by('-created_at')
    for b in broadcasts:
        ws_broadcasts.append([
            b.broadcast_type, b.title, b.content, b.target_audience, b.priority, b.scheme_url
        ])
    _style_excel_sheet(ws_broadcasts)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_blank_cluster_template() -> bytes:
    """
    Generates a clean, standardized starter workbook (.xlsx) with all 7 sheets,
    formatted headers, column descriptions, and one instructional example row.
    Designed for state onboarding of any new Urban Local Body / Corporation.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # 01_Cluster_Profile
    ws_p = wb.create_sheet('01_Cluster_Profile')
    ws_p.append([
        'cluster_code', 'cluster_name', 'cluster_type', 'state',
        'headquarters_lat', 'headquarters_lng', 'commissioner_name',
        'contact_email', 'emergency_helpline', 'description'
    ])
    ws_p.append([
        'MMC', 'Madurai Municipal Corporation', 'MUNICIPAL_CORP', 'Tamil Nadu',
        9.9252, 78.1198, 'Commissioner IAS',
        'commissioner@maduraicorp.gov.in', '1913',
        'Madurai Municipal Corporation is the civic body governing the temple city of Madurai.'
    ])
    _style_excel_sheet(ws_p)

    # 02_Zones
    ws_z = wb.create_sheet('02_Zones')
    ws_z.append([
        'zone_number', 'zone_name', 'hq_address', 'hq_lat', 'hq_lng',
        'zonal_officer_name', 'zonal_officer_email', 'zonal_officer_phone'
    ])
    ws_z.append([
        1, 'Zone 1 - North', 'Madurai North Zonal Office, Race Course Rd', 9.9320, 78.1250,
        'Dr. K. Sundaram', 'zo1@maduraicorp.gov.in', '0452-2531001'
    ])
    _style_excel_sheet(ws_z)

    # 03_Wards
    ws_w = wb.create_sheet('03_Wards')
    ws_w.append([
        'ward_number', 'zone_number', 'ward_name', 'centroid_lat', 'centroid_lng',
        'digipin_prefix', 'area_sq_km'
    ])
    ws_w.append([
        1, 1, 'Ward 1 - Sellur North', 9.9350, 78.1200, '4T38AA', 1.8
    ])
    _style_excel_sheet(ws_w)

    # 04_Departments
    ws_d = wb.create_sheet('04_Departments')
    ws_d.append([
        'dept_code', 'dept_name', 'description', 'head_officer',
        'contact_email', 'phone', 'standard_sla_hours'
    ])
    ws_d.append([
        'ROADS', 'Roads & Infrastructure', 'Pothole repairs, asphalt resurfacing, pedestrian sidewalks',
        'Executive Engineer - Roads', 'roads@maduraicorp.gov.in', '0452-2531002', 48
    ])
    _style_excel_sheet(ws_d)

    # 05_Officers_Staff
    ws_s = wb.create_sheet('05_Officers_Staff')
    ws_s.append([
        'staff_id', 'full_name', 'email', 'phone', 'role', 'workflow_level',
        'assigned_zone', 'assigned_ward', 'assigned_department', 'designation'
    ])
    ws_s.append([
        'ae_ward1_roads', 'M. Saravanan AE', 'ae.ward1.roads@maduraicorp.gov.in', '9840012345',
        'WARD_OFFICER', 'DL1', 1, 1, 'ROADS', 'Assistant Engineer - Ward 1'
    ])
    _style_excel_sheet(ws_s)

    # 06_Categories_SLAs
    ws_c = wb.create_sheet('06_Categories_SLAs')
    ws_c.append([
        'category_code', 'category_name', 'dept_code', 'default_severity',
        'sla_hours', 'escalation_l1_hours', 'escalation_l2_hours', 'escalation_l3_hours'
    ])
    ws_c.append([
        'POTHOLE', 'Road Pothole Repair', 'ROADS', 'MEDIUM', 36, 12, 24, 48
    ])
    _style_excel_sheet(ws_c)

    # 07_Broadcast_Services
    ws_b = wb.create_sheet('07_Broadcast_Services')
    ws_b.append([
        'broadcast_type', 'title', 'description', 'target_audience', 'priority', 'scheme_url'
    ])
    ws_b.append([
        'ALERT', 'Summer Drinking Water Supply Schedule',
        'Drinking water tanker supply timings and ward contact numbers for the summer season.',
        'All Residents', 'NORMAL', 'https://maduraicorporation.gov.in'
    ])
    _style_excel_sheet(ws_b)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
