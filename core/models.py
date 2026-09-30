"""
DPIG Core Models: Multi-Tenant Local Governance, Spatial Grievances,
SHA-256 Audit Chains, SLAs, Broadcasts & AI Capital Project Recommendations.
"""
import hashlib
import json
import uuid
from datetime import timedelta
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from core.digipin import encode as encode_digipin, format_digipin


class Cluster(models.Model):
    """Local Government Cluster (e.g. Greater Chennai Corporation)."""
    CLUSTER_TYPES = [
        ('MUNICIPAL_CORP', 'Municipal Corporation'),
        ('MUNICIPALITY', 'Municipality'),
        ('DISTRICT', 'District Administration'),
        ('TOWN_PANCHAYAT', 'Town Panchayat'),
    ]

    name = models.CharField(max_length=200, help_text="e.g. Greater Chennai Corporation")
    code = models.CharField(max_length=30, unique=True, help_text="e.g. GCC")
    cluster_type = models.CharField(max_length=30, choices=CLUSTER_TYPES, default='MUNICIPAL_CORP')
    state = models.CharField(max_length=100, default='Tamil Nadu')
    headquarters_lat = models.FloatField(default=13.0827)
    headquarters_lng = models.FloatField(default=80.2707)
    commissioner_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    emergency_helpline = models.CharField(max_length=50, default='1234')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.emergency_helpline or str(self.emergency_helpline).strip() == '1913':
            self.emergency_helpline = '1234'

    def save(self, *args, **kwargs):
        if not self.emergency_helpline or str(self.emergency_helpline).strip() == '1913':
            self.emergency_helpline = '1234'
        super().save(*args, **kwargs)

    @property
    def helpline(self):
        return '1234' if (not self.emergency_helpline or str(self.emergency_helpline).strip() == '1913') else self.emergency_helpline

    @property
    def total_wards_count(self):
        return Ward.objects.filter(zone__cluster=self).count()

    def __str__(self):
        return f"{self.name} ({self.code})"

    class Meta:
        ordering = ['name']


class Zone(models.Model):
    """Administrative Zone within a Cluster (e.g. Zone 1 Thiruvottiyur to Zone 15 Sholinganallur)."""
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='zones')
    number = models.PositiveIntegerField(help_text="Zone Number 1-15")
    name = models.CharField(max_length=150, help_text="e.g. Thiruvottiyur")
    hq_address = models.TextField(blank=True)
    hq_lat = models.FloatField(default=13.0827)
    hq_lng = models.FloatField(default=80.2707)
    zonal_officer_name = models.CharField(max_length=150, blank=True)
    zonal_officer_email = models.EmailField(blank=True)
    zonal_officer_phone = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f"Zone {self.number}: {self.name} ({self.cluster.code})"

    class Meta:
        ordering = ['cluster', 'number']
        unique_together = ('cluster', 'number')


class Ward(models.Model):
    """Electoral / Administrative Ward within a Zone (e.g. Wards 1 to 200)."""
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='wards')
    number = models.PositiveIntegerField(help_text="Ward Number 1-200")
    name = models.CharField(max_length=150, help_text="e.g. Kathivakkam")
    centroid_lat = models.FloatField(default=13.0827)
    centroid_lng = models.FloatField(default=80.2707)
    digipin_prefix = models.CharField(max_length=20, blank=True, help_text="DIGIPIN prefix for ward area")
    area_sq_km = models.FloatField(default=1.5)

    def __str__(self):
        return f"Ward {self.number} - {self.name} (Zone {self.zone.number})"

    class Meta:
        ordering = ['number']
        unique_together = ('zone', 'number')


class Department(models.Model):
    """Municipal Service Department (Solid Waste, Drains, Roads, etc.)."""
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='departments')
    code = models.CharField(max_length=30, help_text="e.g. SWM, SWD, ROADS, LIGHTS, HEALTH")
    name = models.CharField(max_length=150, help_text="e.g. Solid Waste Management")
    description = models.TextField(blank=True)
    head_officer = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    standard_sla_hours = models.PositiveIntegerField(default=24)

    def __str__(self):
        return f"{self.name} ({self.code})"

    class Meta:
        ordering = ['name']
        unique_together = ('cluster', 'code')


class GrievanceCategory(models.Model):
    """Grievance classification with SLA and escalation thresholds."""
    SEVERITY_LEVELS = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical / Emergency'),
    ]

    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='categories')
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='categories')
    code = models.CharField(max_length=50, help_text="e.g. POTHOLE, WATERLOGGING")
    name = models.CharField(max_length=200, help_text="e.g. Road Pothole Repair")
    default_severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='MEDIUM')
    sla_hours = models.PositiveIntegerField(default=24, help_text="Resolution deadline in hours")
    escalation_l1_hours = models.PositiveIntegerField(default=12, help_text="Escalate to AE/JE")
    escalation_l2_hours = models.PositiveIntegerField(default=24, help_text="Escalate to EE")
    escalation_l3_hours = models.PositiveIntegerField(default=48, help_text="Escalate to Zonal Officer / Commissioner")

    def __str__(self):
        return f"{self.name} [{self.department.code}]"

    class Meta:
        ordering = ['department', 'name']
        unique_together = ('cluster', 'code')


WORKFLOW_LEVEL_CODES = ['DL1', 'DL2', 'DL3', 'CL1', 'CL2', 'CL3', 'CM_OFFICE']

LEVEL_INT_TO_CODE = {
    1: 'DL1',
    2: 'DL2',
    3: 'DL3',
    4: 'CL1',
    5: 'CL2',
    6: 'CL3',
    7: 'CM_OFFICE',
}

LEVEL_CODE_TO_INT = {
    'DL1': 1,
    'DL2': 2,
    'DL3': 3,
    'CL1': 4,
    'CL2': 5,
    'CL3': 6,
    'CM_OFFICE': 7,
}

LEVEL_LABELS = {
    'DL1': 'Department Level 1 (DL1 - Concerned Department)',
    'DL2': 'Department Level 2 (DL2 - DL1 + 1)',
    'DL3': 'Department Level 3 (DL3 - DL2 + 1)',
    'CL1': 'City Level 1 (CL1 - All DL3 + 1)',
    'CL2': 'City Level 2 (CL2 - CL1 + 1)',
    'CL3': 'City Level 3 (CL3 - CL2 + 1)',
    'CM_OFFICE': 'Escalated to CM Office (Apex Review)',
}

DEFAULT_LEVEL_SLA_HOURS = {
    'DL1': 24,
    'DL2': 24,
    'DL3': 24,
    'CL1': 48,
    'CL2': 48,
    'CL3': 72,
    'CM_OFFICE': 72,
}


def find_officer_for_workflow_level(cluster, zone, department, level_code: str):
    """
    Finds the designated officer profile for a complaint given its zone, department, and workflow level:
    - DL1: Dept Level 1 in zone & department (or zone DL1)
    - DL2: Dept Level 2 in zone & department (or zone DL2)
    - DL3: Dept Level 3 in zone (e.g. Zonal Officer / Dept Zonal Head)
    - CL1: City Level 1 (Citywide Dept Head / Joint Commissioner)
    - CL2: City Level 2 (Deputy / Additional Commissioner)
    - CL3: City Level 3 (Municipal Commissioner)
    - CM_OFFICE: Chief Minister's Executive Cell
    """
    if level_code == 'DL1':
        p = UserProfile.objects.filter(cluster=cluster, zone=zone, department=department, hierarchy_level=1).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, zone=zone, hierarchy_level=1).first()
        if not p and department:
            p = UserProfile.objects.filter(cluster=cluster, department=department, hierarchy_level=1).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, zone=zone, role__in=['WARD_OFFICER', 'FIELD_STAFF']).first()
        return p

    elif level_code == 'DL2':
        p = UserProfile.objects.filter(cluster=cluster, zone=zone, department=department, hierarchy_level=2).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, zone=zone, hierarchy_level=2).first()
        if not p and department:
            p = UserProfile.objects.filter(cluster=cluster, department=department, hierarchy_level=2).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, zone=zone, role='ZONAL_OFFICER').first()
        return p

    elif level_code == 'DL3':
        p = UserProfile.objects.filter(cluster=cluster, zone=zone, hierarchy_level=3).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, zone=zone, role='ZONAL_OFFICER').first()
        return p

    elif level_code == 'CL1':
        p = UserProfile.objects.filter(cluster=cluster, department=department, hierarchy_level=4).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, hierarchy_level=4).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, hierarchy_level=5).first()
        return p

    elif level_code == 'CL2':
        p = UserProfile.objects.filter(cluster=cluster, hierarchy_level=5).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, role='COMMISSIONER').first()
        return p

    elif level_code == 'CL3':
        p = UserProfile.objects.filter(cluster=cluster, hierarchy_level=6).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, role='COMMISSIONER').first()
        return p

    elif level_code == 'CM_OFFICE':
        p = UserProfile.objects.filter(cluster=cluster, hierarchy_level=7).first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, role='CM_OFFICE').first()
        if not p:
            p = UserProfile.objects.filter(cluster=cluster, role='SUPERADMIN').first()
        return p

    return None


class UserProfile(models.Model):
    """Role-based access control profile linked to Django User."""
    ROLES = [
        ('SUPERADMIN', 'State SuperAdmin'),
        ('DEPT_ADMIN', 'Departmental Administrator'),
        ('COMMISSIONER', 'Municipal Commissioner (CL3)'),
        ('ZONAL_OFFICER', 'Zonal Officer (DL3)'),
        ('WARD_OFFICER', 'Ward / Dept Officer (DL1/DL2)'),
        ('FIELD_STAFF', 'Field Verification Staff (DL1)'),
        ('CM_OFFICE', 'Chief Minister Special Cell (CM Office)'),
        ('POLICYMAKER', 'State / National Policymaker'),
        ('AUDITOR', 'Statutory / Compliance Auditor'),
        ('CITIZEN', 'Citizen'),
    ]

    HIERARCHY_LEVELS = [
        (1, 'DL1: Department Level 1 (Ward/Junior AE)'),
        (2, 'DL2: Department Level 2 (Assistant Executive Engineer)'),
        (3, 'DL3: Department Level 3 (Executive Engineer / Zonal Head)'),
        (4, 'CL1: City Level 1 (Citywide Dept Head / Joint Commissioner)'),
        (5, 'CL2: City Level 2 (Deputy / Additional Commissioner)'),
        (6, 'CL3: City Level 3 (Municipal Commissioner)'),
        (7, 'CM_OFFICE: Chief Minister Executive Cell (Apex Level)'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    cluster = models.ForeignKey(Cluster, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=30, choices=ROLES, default='CITIZEN')
    hierarchy_level = models.PositiveSmallIntegerField(
        choices=HIERARCHY_LEVELS,
        default=1,
        help_text="Departmental Hierarchy Tier for SLA Escalation (DL1..CL3, CM_OFFICE)"
    )
    zone = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True)
    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=25, blank=True)
    designation = models.CharField(max_length=150, blank=True)
    aadhaar_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="SHA-256 hash of 12-digit Aadhaar for deduplication & verification lookup"
    )
    aadhaar_last4 = models.CharField(
        max_length=4,
        blank=True,
        help_text="Masked Aadhaar display XXXX-XXXX-1234"
    )
    is_aadhaar_verified = models.BooleanField(
        default=False,
        help_text="Whether this citizen account has completed UIDAI OTP authentication"
    )

    @property
    def workflow_level(self):
        return LEVEL_INT_TO_CODE.get(self.hierarchy_level, 'DL1')

    @property
    def hierarchy_label(self):
        if self.role == 'SUPERADMIN':
            return "State SuperAdmin (Executive Control)"
        if self.role == 'DEPT_ADMIN':
            dept_name = self.department.name if self.department else "Statewide"
            return f"Department Admin - {dept_name}"
        if self.role == 'POLICYMAKER':
            if self.ward:
                return f"Policymaker - Ward {self.ward.number}"
            zone_txt = f" - Zone {self.zone.number}" if self.zone else " - Statewide"
            return f"Policymaker{zone_txt}"
        if self.role == 'AUDITOR':
            return "Statutory / Compliance Auditor"
        if self.role == 'CITIZEN':
            return f"Citizen (Aadhaar: ****-****-{self.aadhaar_last4})" if self.is_aadhaar_verified and self.aadhaar_last4 else "Citizen"
        if self.role == 'CM_OFFICE' or self.hierarchy_level == 7:
            return "CM Office: Chief Minister Executive Cell (Apex Level)"
        if self.role == 'COMMISSIONER' or self.hierarchy_level == 6:
            return "CL3: City Level 3 (Municipal Commissioner)"
        if self.hierarchy_level == 5:
            return "CL2: City Level 2 (Deputy / Additional Commissioner)"
        if self.hierarchy_level == 4:
            return "CL1: City Level 1 (Citywide Dept Head / Joint Commissioner)"
        if self.role == 'ZONAL_OFFICER' or self.hierarchy_level == 3:
            return "DL3: Department Level 3 (Executive Engineer / Zonal Officer)"
        if self.hierarchy_level == 2:
            return "DL2: Department Level 2 (Assistant Executive Engineer)"
        return "DL1: Department Level 1 (Ward / Junior AE)"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.role} - {self.workflow_level})"


class AadhaarVerificationRecord(models.Model):
    """UIDAI Aadhaar OTP Verification log for citizen authentication and accountability."""
    aadhaar_hash = models.CharField(max_length=64, db_index=True)
    aadhaar_last4 = models.CharField(max_length=4)
    mobile_number = models.CharField(max_length=15)
    otp_code = models.CharField(max_length=6)
    is_verified = models.BooleanField(default=False)
    purpose = models.CharField(max_length=30, default='SIGNUP')  # SIGNUP, LOGIN, RECOVERY, GRIEVANCE
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"Aadhaar OTP for ****-****-{self.aadhaar_last4} [{self.purpose}] ({'Verified' if self.is_verified else 'Pending'})"

    class Meta:
        ordering = ['-created_at']


class YearlyTicketSequence(models.Model):
    """
    Yearly sequential counter for generating unique grievance ticket IDs.
    Enforces format: DPIG-YYYY-LLL-NNNNNN (e.g. DPIG-2026-GCC-000001).
    Every year beginning 'NNNNNN' restarts from '000001'.
    """
    cluster_code = models.CharField(max_length=30, default="GCC", db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('cluster_code', 'year')
        verbose_name = "Yearly Ticket Sequence"
        verbose_name_plural = "Yearly Ticket Sequences"

    def __str__(self):
        return f"{self.cluster_code}-{self.year}: {self.last_number:06d}"


@transaction.atomic
def generate_ticket_number(cluster=None, year=None) -> str:
    """
    Generates Ticket ID in the format: DPIG-YYYY-LLL-NNNNNN
    E.g., DPIG-2026-GCC-000001, DPIG-2026-GCC-555555.
    Every year beginning 'NNNNNN' restarts from '000001'.
    """
    if not year:
        year = timezone.now().year
    code = (cluster.code if cluster and cluster.code else "GCC").upper().strip()
    prefix = f"DPIG-{year}-{code}-"

    seq, _ = YearlyTicketSequence.objects.select_for_update().get_or_create(
        cluster_code=code,
        year=year,
        defaults={'last_number': 0}
    )

    if seq.last_number == 0:
        # Check if any existing complaints already have this prefix
        existing_tickets = Complaint.objects.filter(
            ticket_number__startswith=prefix
        ).values_list('ticket_number', flat=True)
        max_num = 0
        for t in existing_tickets:
            suffix = t[len(prefix):]
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))
        seq.last_number = max_num

    seq.last_number += 1
    # Check for any collision and increment if necessary
    while Complaint.objects.filter(ticket_number=f"{prefix}{seq.last_number:06d}").exists():
        seq.last_number += 1

    seq.save(update_fields=['last_number'])
    return f"{prefix}{seq.last_number:06d}"


class Complaint(models.Model):
    """Citizen Grievance Core Entity with State Machine, SLA, DIGIPIN, and Geo-coordinates."""
    STATUS_CHOICES = [
        ('SUBMITTED', 'Submitted'),
        ('AI_CLASSIFIED', 'AI Classified'),
        ('ASSIGNED', 'Assigned to Officer'),
        ('FIELD_VERIFICATION', 'Field Inspection in Progress'),
        ('RESOLVED', 'Resolved'),
        ('CITIZEN_CONFIRMED', 'Citizen Confirmed & Closed'),
        ('REOPENED', 'Reopened by Citizen'),
        ('DUPLICATE', 'Marked Duplicate'),
        ('REJECTED', 'Rejected'),
        ('ESCALATED', 'SLA Breached & Escalated'),
    ]

    SEVERITY_LEVELS = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical / Emergency'),
    ]

    ticket_number = models.CharField(max_length=40, unique=True, db_index=True)
    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='complaints')
    zone = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')
    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')
    category = models.ForeignKey(GrievanceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')

    citizen = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints_filed')
    citizen_name = models.CharField(max_length=150)
    citizen_email = models.EmailField()
    citizen_phone = models.CharField(max_length=25, blank=True)
    is_aadhaar_verified = models.BooleanField(default=False, help_text="Complainant authenticated via UIDAI Aadhaar")
    aadhaar_last4 = models.CharField(max_length=4, blank=True, help_text="Masked Aadhaar display XXXX-XXXX-1234")

    title = models.CharField(max_length=250)
    description = models.TextField()
    original_description = models.TextField(blank=True, help_text="Preserved verbatim citizen submission")
    translated_title = models.CharField(max_length=250, blank=True, help_text="Standardized English title")
    translated_description = models.TextField(blank=True, help_text="Standardized English description")
    translation_header = models.CharField(max_length=350, blank=True, help_text="Automated translation disclaimer and attribution")
    language_detected = models.CharField(max_length=20, default='en')
    script_detected = models.CharField(max_length=50, default='Latin')
    unicode_script_range = models.CharField(max_length=50, blank=True, default='U+0020–U+007F')

    latitude = models.FloatField(db_index=True)
    longitude = models.FloatField(db_index=True)
    digipin = models.CharField(max_length=30, db_index=True, blank=True)
    address_landmark = models.TextField(blank=True)
    image = models.ImageField(upload_to='complaints/%Y/%m/', null=True, blank=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='SUBMITTED', db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='MEDIUM')
    urgency_score = models.FloatField(default=0.5)

    current_assignee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_complaints')
    current_level = models.CharField(
        max_length=20,
        default='DL1',
        choices=[(k, v) for k, v in LEVEL_LABELS.items()],
        db_index=True,
        help_text="Current Sequential Escalation Level: DL1 -> DL2 -> DL3 -> CL1 -> CL2 -> CL3 -> CM_OFFICE"
    )
    escalated_to_level = models.PositiveSmallIntegerField(
        default=1,
        help_text="Current officer hierarchy level integer (1: DL1, 2: DL2, 3: DL3, 4: CL1, 5: CL2, 6: CL3, 7: CM_OFFICE)"
    )
    level_sla_hours = models.PositiveIntegerField(
        default=24,
        help_text="SLA hours allocated specifically for the current escalation level"
    )
    sla_deadline = models.DateTimeField(null=True, blank=True)
    is_sla_breached = models.BooleanField(default=False)
    sla_escalation_tier = models.PositiveIntegerField(default=0)

    resolution_notes = models.TextField(blank=True)
    resolution_image = models.ImageField(upload_to='resolutions/%Y/%m/', null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    is_duplicate_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='duplicates')
    citizen_rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1 to 5 stars")
    citizen_feedback = models.TextField(blank=True)

    AUDIT_STATUS_CHOICES = [
        ('NOT_AUDITED', 'Not Audited'),
        ('UNDER_REVIEW', 'Under Audit Review'),
        ('COMPLIANT', 'Compliant with Policies'),
        ('FLAGGED_NON_COMPLIANT', 'Flagged Non-Compliant'),
    ]
    audit_status = models.CharField(max_length=30, choices=AUDIT_STATUS_CHOICES, default='NOT_AUDITED', db_index=True)
    audit_notes = models.TextField(blank=True, help_text="Auditor findings, policy compliance notes and directives")
    audited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audited_complaints')
    audited_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # Auto-generate ticket number in format DPIG-YYYY-LLL-NNNNNN if not set
        if not self.ticket_number:
            year = timezone.now().year
            self.ticket_number = generate_ticket_number(cluster=self.cluster, year=year)

        # Calculate DIGIPIN automatically if coordinates present
        if self.latitude and self.longitude and not self.digipin:
            raw_digipin = encode_digipin(self.latitude, self.longitude, precision=10)
            self.digipin = format_digipin(raw_digipin)

        # Set default SLA deadline based on category or department
        if not self.sla_deadline and is_new:
            hours = 24
            if self.category and self.category.sla_hours:
                hours = self.category.sla_hours
            elif self.department and self.department.standard_sla_hours:
                hours = self.department.standard_sla_hours
            self.sla_deadline = timezone.now() + timedelta(hours=hours)

        super().save(*args, **kwargs)

        if is_new:
            # Create Genesis Audit Block
            self.create_audit_block(
                action="CREATED",
                performed_by=self.citizen,
                actor_role="CITIZEN" if self.citizen else "ANONYMOUS",
                details={
                    "title": self.title,
                    "digipin": self.digipin,
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "status": self.status,
                    "sla_deadline": self.sla_deadline.isoformat() if self.sla_deadline else None
                }
            )

    def create_audit_block(self, action: str, performed_by=None, actor_role: str = "", details: dict = None) -> "ComplaintAuditLog":
        """
        Creates an immutable SHA-256 hash-chained block for this complaint.
        Hash = SHA256(previous_hash + timestamp + action + details_json)
        """
        details = details or {}
        last_block = self.audit_logs.order_by('-id').first()
        prev_hash = last_block.current_hash if last_block else "0" * 64
        now_iso = timezone.now().isoformat()

        payload = {
            "ticket": self.ticket_number,
            "prev_hash": prev_hash,
            "timestamp": now_iso,
            "action": action,
            "actor": performed_by.username if performed_by else "SYSTEM",
            "details": details
        }
        canonical_str = json.dumps(payload, sort_keys=True)
        curr_hash = hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()

        return ComplaintAuditLog.objects.create(
            complaint=self,
            ticket_number=self.ticket_number,
            action=action,
            performed_by=performed_by,
            actor_role=actor_role or ("STAFF" if performed_by and performed_by.is_staff else "CITIZEN"),
            details=details,
            previous_hash=prev_hash,
            current_hash=curr_hash,
            timestamp_iso=now_iso
        )

    @property
    def is_overdue(self) -> bool:
        if self.status in ['RESOLVED', 'CITIZEN_CONFIRMED', 'REJECTED', 'DUPLICATE']:
            return False
        if self.is_sla_breached:
            return True
        if self.sla_deadline and timezone.now() > self.sla_deadline:
            return True
        return False

    @property
    def remaining_sla_seconds(self) -> int:
        if not self.sla_deadline or self.status in ['RESOLVED', 'CITIZEN_CONFIRMED', 'REJECTED', 'DUPLICATE']:
            return 0
        now = timezone.now()
        diff = (self.sla_deadline - now).total_seconds()
        return max(0, int(diff))

    @property
    def current_level_label(self) -> str:
        return LEVEL_LABELS.get(self.current_level, self.current_level)

    @property
    def has_resolution_proof(self) -> bool:
        """Checks if complaint has mandatory resolution evidence (photo or substantive note)."""
        return bool(self.resolution_image or (self.resolution_notes and len(self.resolution_notes.strip()) >= 10))

    @property
    def is_cryptographically_valid(self) -> bool:
        """Verifies integrity of all audit blocks chained to this complaint."""
        logs = self.audit_logs.all().order_by('id')
        if not logs.exists():
            return True
        for block in logs:
            if not block.verify_integrity():
                return False
        return True

    def get_next_escalation_level(self):
        """Returns next sequential level: DL1 -> DL2 -> DL3 -> CL1 -> CL2 -> CL3 -> CM_OFFICE."""
        curr = self.current_level or 'DL1'
        if curr not in WORKFLOW_LEVEL_CODES:
            curr = 'DL1'
        idx = WORKFLOW_LEVEL_CODES.index(curr)
        if idx < len(WORKFLOW_LEVEL_CODES) - 1:
            return WORKFLOW_LEVEL_CODES[idx + 1]
        return None

    def escalate_to_next_level(self, reason: str = "", actor=None, auto: bool = False) -> bool:
        """
        Escalates complaint sequentially: DL1 -> DL2 -> DL3 -> CL1 -> CL2 -> CL3 -> CM_OFFICE.
        Reassigns to the corresponding level officer, resets SLA for the new level,
        logs SLAEscalationLog and SHA-256 ComplaintAuditLog, and dispatches notifications.
        """
        next_level = self.get_next_escalation_level()
        if not next_level:
            # Already at CM_OFFICE (Apex Level)
            # Avoid logging redundant APEX blocks on repeated watchdog cycles
            if not (auto and self.is_sla_breached):
                self.create_audit_block(
                    action="APEX_LEVEL_NOTIFICATION",
                    performed_by=actor if (actor and actor.is_authenticated) else None,
                    actor_role="CITIZEN" if (actor and not actor.is_staff) else ("SLA_WATCHDOG" if auto else "OFFICER"),
                    details={
                        "current_level": "CM_OFFICE",
                        "note": "Complaint is at Apex CM Office. No further escalation possible.",
                        "reason": reason
                    }
                )
            return False

        old_level = self.current_level
        old_assignee = self.current_assignee
        next_int = LEVEL_CODE_TO_INT.get(next_level, 1)

        # Find designated officer for next level
        target_profile = find_officer_for_workflow_level(self.cluster, self.zone, self.department, next_level)
        target_user = target_profile.user if target_profile else None

        # Calculate new SLA deadline for the new level
        sla_hours = DEFAULT_LEVEL_SLA_HOURS.get(next_level, 24)
        if next_level == 'DL1' and self.category and self.category.sla_hours:
            sla_hours = self.category.sla_hours
        new_deadline = timezone.now() + timedelta(hours=sla_hours)

        self.current_level = next_level
        self.escalated_to_level = next_int
        self.level_sla_hours = sla_hours
        self.sla_deadline = new_deadline
        self.is_sla_breached = False  # fresh SLA window starts for the next level officer
        self.sla_escalation_tier += 1

        if self.status == 'RESOLVED':
            self.status = 'REOPENED'
        else:
            self.status = 'ESCALATED'

        if target_user:
            self.current_assignee = target_user

        self.save(update_fields=[
            'current_level', 'escalated_to_level', 'level_sla_hours',
            'sla_deadline', 'is_sla_breached', 'sla_escalation_tier',
            'status', 'current_assignee', 'updated_at'
        ])

        # Record SLA Escalation Log
        SLAEscalationLog.objects.create(
            complaint=self,
            tier=self.sla_escalation_tier,
            escalated_from_user=old_assignee,
            escalated_to_user=target_user,
            reason=f"[{old_level} -> {next_level}] {reason}"
        )

        # Record SHA-256 Audit Chain Block
        action_name = f"ESCALATED_{old_level}_TO_{next_level}"
        if auto:
            actor_role = "SLA_WATCHDOG"
        elif actor and not actor.is_staff:
            actor_role = "CITIZEN"
        else:
            actor_role = "OFFICER"

        self.create_audit_block(
            action=action_name,
            performed_by=actor if (actor and actor.is_authenticated) else None,
            actor_role=actor_role,
            details={
                "previous_level": old_level,
                "escalated_to_level": next_level,
                "target_officer": target_user.username if target_user else "UNASSIGNED",
                "sla_hours": sla_hours,
                "new_deadline": new_deadline.isoformat(),
                "reason": reason,
                "auto_escalated": auto
            }
        )

        # Dispatch notifications
        try:
            from core import notifications
            if target_user:
                notifications.notify_complaint_assigned(self, target_user, assigner=old_assignee)
            notifications.notify_complaint_status_changed(
                self, 'RESOLVED' if self.status == 'REOPENED' else 'ASSIGNED',
                self.status,
                notes=f"Escalated from {old_level} to {next_level} ({LEVEL_LABELS.get(next_level, next_level)}). Reason: {reason}"
            )
        except Exception:
            pass

        return True

    def __str__(self):
        return f"{self.ticket_number} - {self.title} [{self.status}]"

    class Meta:
        ordering = ['-created_at']


class ComplaintAuditLog(models.Model):
    """Immutable SHA-256 Hash Chained Audit Log for every state transition."""
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='audit_logs')
    ticket_number = models.CharField(max_length=64, blank=True, db_index=True)
    action = models.CharField(max_length=50)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    actor_role = models.CharField(max_length=50, blank=True)
    details = models.JSONField(default=dict)
    previous_hash = models.CharField(max_length=64)
    current_hash = models.CharField(max_length=64, db_index=True)
    timestamp_iso = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def verify_integrity(self) -> bool:
        """Verifies if the current block hash matches the canonical SHA-256 calculation."""
        last_block = ComplaintAuditLog.objects.filter(
            complaint=self.complaint,
            id__lt=self.id
        ).order_by('-id').first()
        expected_prev = last_block.current_hash if last_block else "0" * 64
        if self.previous_hash != expected_prev:
            return False

        ts = self.timestamp_iso if self.timestamp_iso else self.created_at.isoformat()
        ticket = self.ticket_number or self.complaint.ticket_number
        payload = {
            "ticket": ticket,
            "prev_hash": self.previous_hash,
            "timestamp": ts,
            "action": self.action,
            "actor": self.performed_by.username if self.performed_by else "SYSTEM",
            "details": self.details
        }
        canonical_str = json.dumps(payload, sort_keys=True)
        recalculated = hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()
        return recalculated == self.current_hash

    class Meta:
        ordering = ['created_at']


class AuditFinding(models.Model):
    """
    Statutory / Compliance Audit Finding recorded by an Auditor for a Grievance.
    Identifies policy violations, missing proofs, SLA breaches, and required corrective actions.
    """
    FINDING_CATEGORIES = [
        ('SLA_BREACH', 'SLA Breach / Unaddressed Escalation'),
        ('MISSING_PROOF', 'Missing Mandatory Resolution Proof / Photo'),
        ('PREMATURE_CLOSURE', 'Suspect Premature Closure without Verification'),
        ('GEOSPATIAL_MISMATCH', 'Geospatial or DIGIPIN Inaccuracy'),
        ('PROCEDURAL_VIOLATION', 'Departmental Procedural Violation'),
        ('DATA_INTEGRITY', 'Data Integrity / Cryptographic Discrepancy'),
        ('OTHER', 'General Policy Non-Compliance'),
    ]
    SEVERITY_LEVELS = [
        ('LOW', 'Low Severity'),
        ('MEDIUM', 'Medium Severity'),
        ('HIGH', 'High Severity'),
        ('CRITICAL', 'Critical / Statutory Non-Compliance'),
    ]

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='audit_findings')
    auditor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='filed_audit_findings')
    category = models.CharField(max_length=50, choices=FINDING_CATEGORIES)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='MEDIUM')
    observation = models.TextField(help_text="Detailed audit observation and rule/policy violation notes")
    action_required = models.TextField(blank=True, help_text="Corrective or remediation action required from department")
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity}] {self.category} on {self.complaint.ticket_number}"


class AIDecisionLog(models.Model):
    """Detailed log of Google Gemini AI triage decisions for complete explainability."""
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='ai_logs')
    model_name = models.CharField(max_length=50, default='gemini-3.8-flash')
    input_prompt = models.TextField()
    raw_response = models.TextField()
    classified_category = models.CharField(max_length=150, blank=True)
    classified_department = models.CharField(max_length=100, blank=True)
    confidence_score = models.FloatField(default=0.0)
    sentiment = models.CharField(max_length=50, blank=True)
    extracted_entities = models.JSONField(default=dict)
    execution_time_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AI Decision for {self.complaint.ticket_number} ({self.confidence_score * 100:.0f}%)"


class SLAEscalationLog(models.Model):
    """History of SLA breaches and officer escalations across tiers L1, L2, L3."""
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='escalations')
    tier = models.PositiveSmallIntegerField(default=1)
    escalated_from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='escalations_from')
    escalated_to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='escalations_to')
    reason = models.CharField(max_length=250)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.complaint.ticket_number} - Escalated to Tier {self.tier}"


class GovernmentBroadcastQuerySet(models.QuerySet):
    def active(self):
        """Returns broadcasts that are currently active based on boolean flag and time-based validity."""
        now = timezone.now()
        return self.filter(
            is_active=True,
            valid_from__lte=now
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=now)
        )


class GovernmentBroadcast(models.Model):
    """Public government alerts, welfare schemes, advisories and emergency guidance."""
    BROADCAST_TYPES = [
        ('ALERT', 'Emergency / Disaster Alert'),
        ('WELFARE_SCHEME', 'Welfare Scheme & Benefits'),
        ('ADVISORY', 'Civic Advisory / Water & Traffic Notice'),
        ('CIVIC_GUIDANCE', 'Citizen Guidance & FAQ'),
    ]

    PRIORITY_LEVELS = [
        ('INFO', 'Informational'),
        ('NORMAL', 'Standard Notice'),
        ('HIGH', 'High Priority'),
        ('EMERGENCY', 'Urgent / Emergency Warning'),
    ]

    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, null=True, blank=True, related_name='broadcasts', help_text="Null for statewide broadcasts")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True, related_name='broadcasts', help_text="Department publishing this alert or welfare scheme")
    broadcast_type = models.CharField(max_length=30, choices=BROADCAST_TYPES, default='WELFARE_SCHEME')
    title = models.CharField(max_length=250)
    content = models.TextField()
    eligibility_criteria = models.TextField(blank=True, help_text="Eligibility conditions for welfare scheme beneficiaries")
    benefits = models.TextField(blank=True, help_text="Details of financial/in-kind/service benefits offered")
    target_audience = models.CharField(max_length=150, default='All Citizens')
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='NORMAL')
    scheme_url = models.URLField(blank=True, help_text="Official application or portal link")
    is_active = models.BooleanField(default=True)
    valid_from = models.DateTimeField(default=timezone.now, help_text="Start timestamp from which this alert/scheme is active")
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Expiry or application deadline timestamp")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_broadcasts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = GovernmentBroadcastQuerySet.as_manager()

    @property
    def is_currently_active(self) -> bool:
        """Evaluates live time-based validity."""
        now = timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and self.valid_from > now:
            return False
        if self.valid_until and self.valid_until < now:
            return False
        return True

    @property
    def time_status(self) -> str:
        """Returns human-readable time-based status: ACTIVE, SCHEDULED, EXPIRED, or INACTIVE."""
        now = timezone.now()
        if not self.is_active:
            return 'INACTIVE'
        if self.valid_from and self.valid_from > now:
            return 'SCHEDULED'
        if self.valid_until and self.valid_until < now:
            return 'EXPIRED'
        return 'ACTIVE'

    def __str__(self):
        dept_str = f" [{self.department.code}]" if self.department else ""
        return f"[{self.broadcast_type}]{dept_str} {self.title}"

    class Meta:
        ordering = ['-created_at']


class CapitalProjectRecommendation(models.Model):
    """Consolidated policymaker intelligence: AI-synthesized priority infrastructure projects."""
    STATUS_CHOICES = [
        ('PROPOSED', 'Proposed / Identified by AI'),
        ('PLANNED', 'Planned Work'),
        ('UNDER_REVIEW', 'Under Review by Department'),
        ('SANCTIONED', 'Budget Sanctioned'),
        ('TENDERED', 'Tender Floated'),
        ('IN_EXECUTION', 'Work in Progress'),
        ('COMPLETED', 'Completed'),
    ]

    cluster = models.ForeignKey(Cluster, on_delete=models.CASCADE, related_name='project_recommendations')
    title = models.CharField(max_length=250)
    sector = models.CharField(max_length=100, help_text="e.g. Stormwater Drainage, Road Widening, Sanitation Hub")
    affected_zones = models.JSONField(default=list, help_text="List of Zone numbers")
    affected_wards = models.JSONField(default=list, help_text="List of Ward numbers")
    complaint_cluster_count = models.PositiveIntegerField(default=1, help_text="Number of citizen complaints in this cluster")
    problem_statement = models.TextField()
    proposed_solution = models.TextField()
    estimated_budget_inr = models.DecimalField(max_digits=14, decimal_places=2, default=5000000.00, help_text="Estimated Budget in INR")
    priority_score = models.FloatField(default=85.0, help_text="Priority score 0 - 100")
    ai_rationale = models.TextField(help_text="Gemini 3.8 Flash insight breakdown")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PROPOSED')
    is_planned = models.BooleanField(default=False, db_index=True, help_text="Added to Policymaker Planned Work List")
    planned_at = models.DateTimeField(null=True, blank=True)
    planned_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='planned_capital_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def mark_as_planned(self, user=None):
        self.is_planned = True
        self.status = 'PLANNED'
        self.planned_at = timezone.now()
        if user and user.is_authenticated:
            self.planned_by = user
        self.save(update_fields=['is_planned', 'status', 'planned_at', 'planned_by', 'updated_at'])

    def unmark_planned(self):
        self.is_planned = False
        self.status = 'PROPOSED'
        self.planned_at = None
        self.planned_by = None
        self.save(update_fields=['is_planned', 'status', 'planned_at', 'planned_by', 'updated_at'])

    def is_visible_to_ward(self, ward_num):
        """Check if this project recommendation affects the specified ward number."""
        if not ward_num:
            return False
        w_str = str(ward_num).strip()
        # 1. Check affected_wards JSON list
        for w in (self.affected_wards or []):
            if str(w).strip() == w_str:
                return True
        # 2. Check title, problem_statement, and ai_rationale
        import re
        text = f"{self.title} {self.problem_statement} {self.proposed_solution} {self.ai_rationale}"
        if re.search(rf'\bward\s*#?\s*{w_str}\b', text, re.IGNORECASE):
            return True
        return False

    def is_visible_to_zone(self, zone_num):
        """Check if this project recommendation affects the specified zone number."""
        if not zone_num:
            return False
        z_str = str(zone_num).strip()
        # 1. Check affected_zones JSON list
        for z in (self.affected_zones or []):
            if str(z).strip() == z_str:
                return True
        # 2. Check if any affected_wards belong to this zone
        try:
            from core.models import Ward
            z_int = int(zone_num)
            ward_numbers = set(Ward.objects.filter(zone__number=z_int).values_list('number', flat=True))
            for w in (self.affected_wards or []):
                try:
                    if int(w) in ward_numbers:
                        return True
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass
        # 3. Check text
        import re
        text = f"{self.title} {self.problem_statement} {self.proposed_solution}"
        if re.search(rf'\bzone\s*#?\s*{z_str}\b', text, re.IGNORECASE):
            return True
        return False

    def is_visible_to_user(self, user):
        """Check if recommendation is visible to the given user based on role and jurisdiction."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        profile = getattr(user, 'profile', None)
        if not profile:
            return False
        if profile.role == 'SUPERADMIN':
            return True
        if profile.role != 'POLICYMAKER':
            return False
        if profile.ward:
            return self.is_visible_to_ward(profile.ward.number)
        if profile.zone:
            return self.is_visible_to_zone(profile.zone.number)
        return True

    def __str__(self):
        return f"{self.title} - Priority {self.priority_score}/100"

    class Meta:
        ordering = ['-priority_score', '-created_at']
