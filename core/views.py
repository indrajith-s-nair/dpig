"""
DPIG Views: Citizen Grievances, Officer Triage, Policymaker Intelligence,
1-Click Cluster Onboarding, DIGIPIN APIs & Cryptographic Audit Verification.
"""
import json
import os
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Q, Avg
from django.conf import settings

from core.models import (
    Cluster, Zone, Ward, Department, GrievanceCategory, UserProfile,
    Complaint, ComplaintAuditLog, AuditFinding, AIDecisionLog, SLAEscalationLog,
    GovernmentBroadcast, CapitalProjectRecommendation, AadhaarVerificationRecord,
    find_officer_for_workflow_level, LEVEL_LABELS, WORKFLOW_LEVEL_CODES
)
from core.digipin import encode as encode_digipin, decode as decode_digipin, format_digipin, validate_digipin
from core.geo_service import resolve_ward_from_location
from core.aadhaar import (
    validate_aadhaar_format, clean_aadhaar_number, hash_aadhaar,
    mask_aadhaar, generate_aadhaar_otp, verify_aadhaar_otp
)
from core import notifications
from core import gemini_service
from core.cluster_importer import import_cluster_from_excel
from core.tasks import process_complaint_ai_triage_task
from core.rbac import (
    get_user_role, has_role, can_access_officer_console, can_access_policymaker_console,
    can_access_superadmin_console, can_access_dept_admin_console, can_access_auditor_console,
    can_access_complaint, can_access_capital_project, filter_capital_projects_for_user,
    is_corporation_or_state_officer, is_registered_citizen, citizen_required,
    officer_required, policymaker_required, superadmin_required, dept_admin_required, auditor_required
)
from core.feature_matrix import load_feature_matrix, save_feature_matrix, is_feature_enabled
from core.demo_manager import seed_realistic_demo_complaints, purge_demo_complaints
from core.unicode_scripts import (
    detect_unicode_script, generate_translation_header, heuristic_translate_indian_text, INDIAN_SCRIPT_RANGES
)


def health_check(request):
    """Ultra-lightweight Kubernetes and load balancer liveness & readiness probe."""
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "HEALTHY", "db": "OK"}, status=200)
    except Exception as e:
        return JsonResponse({"status": "UNHEALTHY", "error": str(e)}, status=503)


def home(request):
    """Platform landing page with civic metrics, public announcements, and tracking search."""
    if request.user.is_authenticated:
        role = get_user_role(request.user)
        if role in ['WARD_OFFICER', 'FIELD_STAFF', 'ZONAL_OFFICER', 'COMMISSIONER']:
            return redirect('officer_dashboard')
        elif role == 'DEPT_ADMIN':
            return redirect('dept_admin_dashboard')
        elif role == 'POLICYMAKER':
            return redirect('policymaker_dashboard')
        elif role == 'AUDITOR':
            return redirect('auditor_dashboard')
        elif role == 'SUPERADMIN':
            return redirect('feature_permission_matrix')

    cluster = Cluster.objects.filter(is_active=True).first()
    recent_broadcasts = GovernmentBroadcast.objects.active().order_by('-priority', '-created_at')[:4]

    total_complaints = Complaint.objects.count()
    resolved_complaints = Complaint.objects.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED']).count()
    resolution_rate = round((resolved_complaints / total_complaints * 100), 1) if total_complaints > 0 else 0
    sla_adherence = round(
        (Complaint.objects.filter(is_sla_breached=False).count() / total_complaints * 100), 1
    ) if total_complaints > 0 else 100

    # Capital projects are ONLY visible to respective policymakers
    capital_projects = []
    if request.user.is_authenticated and can_access_policymaker_console(request.user):
        all_recs = CapitalProjectRecommendation.objects.filter(cluster=cluster).order_by('-priority_score') if cluster else CapitalProjectRecommendation.objects.all().order_by('-priority_score')
        capital_projects = filter_capital_projects_for_user(request.user, all_recs)[:3]

    zones_count = cluster.zones.count() if cluster else 0
    wards_count = Ward.objects.filter(zone__cluster=cluster).count() if cluster else 0
    sample_complaint = Complaint.objects.order_by('-created_at').first()
    sample_ticket = sample_complaint.ticket_number if sample_complaint else None

    context = {
        'cluster': cluster,
        'broadcasts': recent_broadcasts,
        'total_complaints': total_complaints,
        'resolved_complaints': resolved_complaints,
        'resolution_rate': resolution_rate,
        'sla_adherence': sla_adherence,
        'zones_count': zones_count,
        'wards_count': wards_count,
        'sample_ticket': sample_ticket,
        'capital_projects': capital_projects,
    }
    return render(request, 'citizen/home.html', context)


def citizen_hub(request):
    """Citizen Hub: Welfare schemes, emergency alerts, civic advisories & my complaint history."""
    if request.user.is_authenticated and not (get_user_role(request.user) == 'CITIZEN'):
        if can_access_dept_admin_console(request.user) and get_user_role(request.user) == 'DEPT_ADMIN':
            return redirect('dept_admin_dashboard')
        elif can_access_officer_console(request.user):
            return redirect('officer_dashboard')
        elif can_access_policymaker_console(request.user):
            return redirect('policymaker_dashboard')
        elif can_access_auditor_console(request.user):
            return redirect('auditor_dashboard')
        elif can_access_superadmin_console(request.user):
            return redirect('feature_permission_matrix')

    cluster = Cluster.objects.filter(is_active=True).first()
    broadcasts = GovernmentBroadcast.objects.active()

    my_complaints = []
    if request.user.is_authenticated:
        my_complaints = Complaint.objects.filter(citizen=request.user).order_by('-created_at')

    context = {
        'cluster': cluster,
        'alerts': broadcasts.filter(broadcast_type='ALERT'),
        'schemes': broadcasts.filter(broadcast_type='WELFARE_SCHEME'),
        'advisories': broadcasts.filter(broadcast_type__in=['ADVISORY', 'CIVIC_GUIDANCE']),
        'my_complaints': my_complaints,
    }
    return render(request, 'citizen/citizen_hub.html', context)


@citizen_required
def file_complaint(request):
    """Citizen Grievance Submission: Strictly restricted to registered citizens."""
    cluster = Cluster.objects.filter(is_active=True).first()
    if not cluster:
        return render(request, 'citizen/cluster_disabled.html', status=503)

    categories = GrievanceCategory.objects.filter(cluster=cluster).select_related('department') if cluster else []
    zones = Zone.objects.filter(cluster=cluster) if cluster else []
    wards = Ward.objects.filter(zone__cluster=cluster) if cluster else []
    profile = getattr(request.user, 'profile', None)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        citizen_name = request.POST.get('citizen_name', '').strip()
        citizen_email = request.POST.get('citizen_email', '').strip()
        citizen_phone = request.POST.get('citizen_phone', '').strip()
        lat_str = request.POST.get('latitude', '')
        lng_str = request.POST.get('longitude', '')
        digipin_input = request.POST.get('digipin', '').strip()
        address_landmark = request.POST.get('address_landmark', '').strip()
        cat_id = request.POST.get('category')
        ward_id = request.POST.get('ward')
        image = request.FILES.get('image')

        if image:
            allowed_exts = ('.jpg', '.jpeg', '.png', '.webp')
            if not image.name.lower().endswith(allowed_exts):
                messages.error(request, "Invalid image format. Supported formats: JPG, JPEG, PNG, WEBP.")
                return render(request, 'citizen/file_complaint.html', {
                    'cluster': cluster, 'categories': categories, 'zones': zones, 'wards': wards
                })
            if image.size > 10 * 1024 * 1024:
                messages.error(request, "Uploaded image exceeds 10MB limit. Please upload a smaller photo.")
                return render(request, 'citizen/file_complaint.html', {
                    'cluster': cluster, 'categories': categories, 'zones': zones, 'wards': wards
                })

        try:
            latitude = float(lat_str) if lat_str else 13.0827
            longitude = float(lng_str) if lng_str else 80.2707
        except ValueError:
            latitude, longitude = 13.0827, 80.2707

        # Calculate or format DIGIPIN
        if digipin_input and validate_digipin(digipin_input):
            digipin = format_digipin(digipin_input)
        else:
            digipin = format_digipin(encode_digipin(latitude, longitude, precision=10))

        # Resolve Ward and Zone automatically based on zone_id, ward_id or Location/DIGIPIN
        zone_id = request.POST.get('zone')
        ward = None
        zone = None
        if zone_id:
            zone = Zone.objects.filter(id=zone_id).first()
            if not zone and str(zone_id).isdigit():
                zone = Zone.objects.filter(number=int(zone_id)).first()

        if ward_id:
            ward = Ward.objects.filter(id=ward_id).first()
            if ward:
                zone = ward.zone

        # Auto-resolve from Location & DIGIPIN if not explicitly set
        if not ward:
            ward, _ = resolve_ward_from_location(latitude, longitude, digipin=digipin, cluster=cluster)
            if ward and not zone:
                zone = ward.zone
            elif not zone and zones.exists():
                zone = zones.first()
                ward = zone.wards.first()

        category = GrievanceCategory.objects.filter(id=cat_id).first() if cat_id else None
        department = category.department if category else None

        # Assign immediately to DL1 Officer of concerned department in selected zone
        dl1_profile = find_officer_for_workflow_level(cluster, zone, department, 'DL1')
        initial_assignee = dl1_profile.user if dl1_profile else None

        # Unicode script detection & automated translation header generation across 10 Indian scripts
        detection = detect_unicode_script(f"{title} {description}")
        trans_header = generate_translation_header(detection)
        h_title, h_desc = heuristic_translate_indian_text(description or title, detection)
        trans_title = h_title or title or "Civic Grievance"
        trans_desc = h_desc or description
        if not title:
            title = trans_title

        # Aadhaar anti-spam and accountability verification from registered citizen profile
        user_is_aadhaar_verified = profile.is_aadhaar_verified if profile else True
        aadhaar_last4_val = (profile.aadhaar_last4 if profile and profile.aadhaar_last4 else "") or "7890"

        sla_hrs = category.sla_hours if (category and category.sla_hours) else 24

        complaint = Complaint.objects.create(
            cluster=cluster,
            zone=zone,
            ward=ward,
            department=department,
            category=category,
            citizen=request.user,
            citizen_name=citizen_name or request.user.get_full_name() or request.user.username,
            citizen_email=citizen_email or request.user.email or settings.NOTIFICATION_FALLBACK_EMAIL,
            citizen_phone=citizen_phone or (profile.phone if profile else ""),
            is_aadhaar_verified=user_is_aadhaar_verified,
            aadhaar_last4=aadhaar_last4_val,
            title=title or "Civic Grievance",
            description=description,
            original_description=description,
            translated_title=trans_title,
            translated_description=trans_desc,
            script_detected=detection.get('script', 'Latin'),
            language_detected=detection.get('lang_code', 'en'),
            unicode_script_range=detection.get('hex_range', 'U+0020–U+007F'),
            translation_header=trans_header,
            latitude=latitude,
            longitude=longitude,
            digipin=digipin,
            address_landmark=address_landmark,
            image=image,
            current_assignee=initial_assignee,
            current_level='DL1',
            escalated_to_level=1,
            level_sla_hours=sla_hrs,
            status='ASSIGNED' if initial_assignee else 'SUBMITTED'
        )

        # Dispatch immediate email confirmation to citizen and DL1 assignee
        base_url = request.build_absolute_uri('/')[:-1]
        notifications.notify_complaint_created(complaint, base_url=base_url)
        if initial_assignee:
            notifications.notify_complaint_assigned(complaint, initial_assignee, base_url=base_url)

        # Trigger Celery async AI triage or synchronous fallback
        try:
            process_complaint_ai_triage_task.delay(complaint.id)
        except Exception:
            # Fallback to direct synchronous execution if Redis/Celery is offline
            process_complaint_ai_triage_task(complaint.id)

        messages.success(request, f"Grievance registered successfully! Ticket Number: {complaint.ticket_number}")
        return redirect('track_complaint', ticket_number=complaint.ticket_number)

    user_is_aadhaar_verified = profile.is_aadhaar_verified if profile else True
    user_aadhaar_last4 = (profile.aadhaar_last4 if profile and profile.aadhaar_last4 else "") or "7890"

    context = {
        'cluster': cluster,
        'categories': categories,
        'zones': zones,
        'wards': wards,
        'default_lat': cluster.headquarters_lat if cluster else 13.0827,
        'default_lng': cluster.headquarters_lng if cluster else 80.2707,
        'user_is_aadhaar_verified': user_is_aadhaar_verified,
        'user_aadhaar_last4': user_aadhaar_last4,
        'profile': profile,
    }
    return render(request, 'citizen/file_complaint.html', context)


def track_complaint(request, ticket_number=None):
    """Live Grievance Tracking: Stepper, SLA countdown, officer details, SHA-256 audit, feedback."""
    query = ticket_number or request.GET.get('ticket')

    # If an officer/policymaker/auditor is browsing generic track page without ticket, route to console
    if not query and request.user.is_authenticated and not (get_user_role(request.user) == 'CITIZEN'):
        if can_access_officer_console(request.user):
            return redirect('officer_dashboard')
        elif can_access_dept_admin_console(request.user):
            return redirect('dept_admin_dashboard')
        elif can_access_policymaker_console(request.user):
            return redirect('policymaker_dashboard')
        elif can_access_auditor_console(request.user):
            return redirect('auditor_dashboard')
        elif can_access_superadmin_console(request.user):
            return redirect('feature_permission_matrix')

    complaint = None

    if query:
        complaint = Complaint.objects.filter(ticket_number__iexact=query.strip()).first()
        if not complaint and query.isdigit():
            complaint = Complaint.objects.filter(id=int(query)).first()

    if request.method == 'POST' and complaint:
        action = request.POST.get('action')
        base_url = request.build_absolute_uri('/')[:-1]

        # Restrict citizen actions (confirm resolution & reopen) to the grievance filer or administrative staff
        if action in ['confirm_resolution', 'reopen']:
            if complaint.citizen:
                if not request.user.is_authenticated or (request.user != complaint.citizen and not request.user.is_staff):
                    messages.error(request, "Permission denied: Only the registered citizen who filed this grievance can confirm resolution or request reopening.")
                    return redirect('track_complaint', ticket_number=complaint.ticket_number)
            elif request.user.is_authenticated:
                complaint.citizen = request.user

        if action == 'confirm_resolution':
            rating = int(request.POST.get('rating', 5))
            feedback = request.POST.get('feedback', '')
            old_status = complaint.status
            complaint.status = 'CITIZEN_CONFIRMED'
            complaint.citizen_rating = rating
            complaint.citizen_feedback = feedback
            complaint.closed_at = timezone.now()
            complaint.save()

            complaint.create_audit_block(
                action="CITIZEN_CONFIRMED_RESOLUTION",
                performed_by=request.user if request.user.is_authenticated else None,
                actor_role="CITIZEN",
                details={"rating": rating, "feedback": feedback}
            )
            notifications.notify_complaint_closed(complaint, closed_by_citizen=True, base_url=base_url)
            messages.success(request, "Thank you! Your confirmation and rating have been recorded.")
            return redirect('track_complaint', ticket_number=complaint.ticket_number)

        elif action == 'reopen':
            reopen_reason = request.POST.get('reopen_reason', 'Issue not satisfactorily resolved.')
            old_level = complaint.current_level
            actor = request.user if request.user.is_authenticated else None
            escalated = complaint.escalate_to_next_level(
                reason=f"Citizen reopened - issue not satisfactorily resolved: {reopen_reason}",
                actor=actor
            )
            if escalated:
                messages.warning(
                    request,
                    f"Complaint reopened and escalated to {complaint.current_level} ({complaint.current_level_label}) with new SLA window for supervisory review."
                )
            else:
                complaint.status = 'REOPENED'
                complaint.save(update_fields=['status', 'updated_at'])
                messages.warning(
                    request,
                    "Complaint is currently at Apex CM Office and marked under priority investigation."
                )
            return redirect('track_complaint', ticket_number=complaint.ticket_number)

    context = {
        'complaint': complaint,
        'query': query,
    }
    return render(request, 'citizen/track_complaint.html', context)


@officer_required
def officer_dashboard(request):
    """Officer Console: Assigned queue, SLA countdowns, hierarchy authority, field inspection, resolution proof upload."""
    profile = getattr(request.user, 'profile', None)
    cluster = profile.cluster if profile else Cluster.objects.filter(is_active=True).first()

    status_filter = request.GET.get('status', 'ALL')
    queue_filter = request.GET.get('queue', 'ALL')

    # Determine Officer Hierarchy Level across 7 sequential stages
    hierarchy_level = getattr(profile, 'hierarchy_level', 1) if profile else 1
    if profile:
        if profile.role == 'CM_OFFICE' or profile.hierarchy_level == 7:
            hierarchy_level = 7
        elif profile.role in ['COMMISSIONER', 'SUPERADMIN']:
            hierarchy_level = max(getattr(profile, 'hierarchy_level', 6), 6)
        elif profile.role == 'ZONAL_OFFICER' and hierarchy_level < 3:
            hierarchy_level = 3

    # Check if officer has Corporation or State Level oversight (CL1..CL3, CM_OFFICE, SUPERADMIN)
    is_corp_or_state = is_corporation_or_state_officer(request.user)

    complaints = Complaint.objects.filter(cluster=cluster).select_related(
        'zone', 'ward', 'department', 'category', 'current_assignee'
    )

    if is_corp_or_state:
        # Corporation / State Level Officers have citywide/statewide jurisdiction
        # Filter options (Zone, Department, Workflow Level) are exclusively available to them
        raw_zone_param = request.GET.get('zone')
        dept_filter = request.GET.get('dept', 'ALL')
        level_filter = request.GET.get('level', 'ALL')

        if raw_zone_param is not None and raw_zone_param != '':
            zone_filter = raw_zone_param
        else:
            zone_filter = 'ALL'

        if zone_filter != 'ALL' and zone_filter.isdigit():
            complaints = complaints.filter(zone__number=int(zone_filter))

        # If user is a Department Admin (CL1 Level 4 for a single department), lock department
        if profile and profile.role == 'DEPT_ADMIN' and profile.department:
            dept_filter = profile.department.code
            complaints = complaints.filter(department=profile.department)
        elif dept_filter != 'ALL':
            complaints = complaints.filter(department__code=dept_filter)

        if level_filter != 'ALL' and level_filter in WORKFLOW_LEVEL_CODES:
            complaints = complaints.filter(current_level=level_filter)
    else:
        # Department / Zone / Ward / Field Level Officers (DL1, DL2, DL3)
        # Strictly restricted to their assigned geographical and departmental jurisdiction
        dept_filter = 'ALL'
        level_filter = 'ALL'

        if profile and (profile.role == 'ZONAL_OFFICER' or hierarchy_level == 3):
            # DL3: Zonal Officer is strictly locked to their assigned Zone
            if profile.zone:
                zone_filter = str(profile.zone.number)
                complaints = complaints.filter(zone=profile.zone)
            else:
                zone_filter = 'ALL'
        elif profile and hierarchy_level <= 2:
            # DL1/DL2: Ward / Field Staff strictly locked to assigned Ward / Zone and Department
            zone_filter = str(profile.zone.number) if profile.zone else 'ALL'
            if profile.ward:
                complaints = complaints.filter(Q(ward=profile.ward) | Q(current_assignee=request.user))
            elif profile.zone:
                complaints = complaints.filter(Q(zone=profile.zone) | Q(current_assignee=request.user))
            else:
                complaints = complaints.filter(current_assignee=request.user)

            if profile.department:
                complaints = complaints.filter(Q(department=profile.department) | Q(current_assignee=request.user))
        else:
            zone_filter = str(profile.zone.number) if (profile and profile.zone) else 'ALL'
            if profile and profile.zone:
                complaints = complaints.filter(zone=profile.zone)

    # Base complaints before status/queue filter for accurate KPI card counters
    base_complaints = complaints

    # Specific queue filter for +1 SLA Escalations or Status
    if queue_filter == 'escalated_to_me':
        complaints = complaints.filter(
            Q(escalated_to_level=hierarchy_level) |
            Q(current_assignee=request.user) |
            Q(status='ESCALATED')
        )
    elif status_filter != 'ALL':
        complaints = complaints.filter(status=status_filter)

    counts = {
        'all': base_complaints.count(),
        'assigned': base_complaints.filter(status='ASSIGNED').count(),
        'in_progress': base_complaints.filter(status='FIELD_VERIFICATION').count(),
        'escalated': base_complaints.filter(status='ESCALATED').count(),
        'resolved': base_complaints.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED']).count(),
        'escalated_to_me': base_complaints.filter(
            Q(escalated_to_level=hierarchy_level) |
            Q(current_assignee=request.user) |
            Q(status='ESCALATED')
        ).count(),
    }

    context = {
        'complaints': complaints[:100],
        'counts': counts,
        'status_filter': status_filter,
        'zone_filter': zone_filter,
        'dept_filter': dept_filter,
        'queue_filter': queue_filter,
        'level_filter': level_filter,
        'officer_level': hierarchy_level,
        'officer_level_label': profile.hierarchy_label if profile else f"Level {hierarchy_level}",
        'is_corp_or_state_officer': is_corp_or_state,
        'zones': Zone.objects.filter(cluster=cluster),
        'departments': Department.objects.filter(cluster=cluster),
        'workflow_levels': WORKFLOW_LEVEL_CODES,
    }
    return render(request, 'officer/dashboard.html', context)


@officer_required
def officer_complaint_detail(request, complaint_id):
    """Officer action view: Update status, upload resolution proof photo, +1 Level Staff SLA Escalation, reassign or resolve."""
    complaint = get_object_or_404(Complaint, id=complaint_id)

    # Enforce strict geographic / department jurisdiction
    if not can_access_complaint(request.user, complaint):
        context = {
            'console_name': f"Complaint #{complaint.ticket_number}",
            'user_role': get_user_role(request.user),
            'required_roles': ["Assigned Ward/Zone Officer", "Commissioner", "SuperAdmin"],
            'path': request.path,
        }
        return render(request, 'errors/403_role_denied.html', context, status=403)

    base_url = request.build_absolute_uri('/')[:-1]
    profile = getattr(request.user, 'profile', None)
    curr_level = getattr(profile, 'hierarchy_level', 1) if profile else 1
    if profile and profile.role == 'ZONAL_OFFICER':
        curr_level = 2
    elif profile and profile.role in ['COMMISSIONER', 'SUPERADMIN']:
        curr_level = 3

    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        old_status = complaint.status

        if action == 'start_field_work':
            complaint.status = 'FIELD_VERIFICATION'
            complaint.save()
            complaint.create_audit_block(
                action="FIELD_VERIFICATION_STARTED",
                performed_by=request.user,
                actor_role="OFFICER",
                details={"notes": notes}
            )
            notifications.notify_complaint_status_changed(complaint, old_status, 'FIELD_VERIFICATION', notes=notes, base_url=base_url)
            messages.success(request, "Ticket moved to Field Verification.")

        elif action == 'resolve':
            resolution_image = request.FILES.get('resolution_image')
            if resolution_image:
                allowed_exts = ('.jpg', '.jpeg', '.png', '.webp')
                if not resolution_image.name.lower().endswith(allowed_exts):
                    messages.error(request, "Invalid resolution image format. Supported formats: JPG, JPEG, PNG, WEBP.")
                    return redirect('officer_complaint_detail', complaint_id=complaint.id)
                if resolution_image.size > 10 * 1024 * 1024:
                    messages.error(request, "Resolution image exceeds 10MB limit. Please upload a smaller photo.")
                    return redirect('officer_complaint_detail', complaint_id=complaint.id)

            notes_clean = notes.strip() if notes else ""
            if not resolution_image and len(notes_clean) < 10:
                messages.error(
                    request,
                    "Mandatory resolution proof required: Upload a resolution photo or provide substantive resolution notes (minimum 10 characters)."
                )
                return redirect('officer_complaint_detail', complaint_id=complaint.id)

            complaint.status = 'RESOLVED'
            complaint.resolution_notes = notes
            if resolution_image:
                complaint.resolution_image = resolution_image
            complaint.resolved_at = timezone.now()
            complaint.save()

            complaint.create_audit_block(
                action="RESOLVED_BY_OFFICER",
                performed_by=request.user,
                actor_role="OFFICER",
                details={"notes": notes, "proof_uploaded": bool(resolution_image)}
            )
            notifications.notify_complaint_status_changed(complaint, old_status, 'RESOLVED', notes=notes, base_url=base_url)
            messages.success(request, "Grievance marked RESOLVED. Citizen notified for confirmation.")

        elif action == 'escalate_plus_one':
            notes = request.POST.get('notes', 'Officer manual +1 escalation')
            escalated = complaint.escalate_to_next_level(
                reason=notes,
                actor=request.user
            )
            if escalated:
                messages.success(
                    request,
                    f"Grievance successfully escalated to {complaint.current_level}: {complaint.current_level_label}."
                )
            else:
                messages.info(request, "Complaint is already at Apex CM Office.")

        elif action == 'reassign':
            new_assignee_id = request.POST.get('new_assignee')
            new_assignee = User.objects.filter(id=new_assignee_id).first()
            if new_assignee:
                old_assignee = complaint.current_assignee
                complaint.current_assignee = new_assignee
                complaint.save()

                complaint.create_audit_block(
                    action="REASSIGNED",
                    performed_by=request.user,
                    actor_role="OFFICER",
                    details={
                        "from": old_assignee.username if old_assignee else "None",
                        "to": new_assignee.username
                    }
                )
                notifications.notify_complaint_transferred(complaint, old_assignee, new_assignee, base_url=base_url)
                messages.success(request, f"Grievance reassigned to {new_assignee.get_full_name() or new_assignee.username}.")

        return redirect('officer_complaint_detail', complaint_id=complaint.id)

    next_level_code = complaint.get_next_escalation_level()
    next_target_label = LEVEL_LABELS.get(next_level_code, next_level_code) if next_level_code else None

    available_staff = UserProfile.objects.filter(
        cluster=complaint.cluster,
        role__in=['WARD_OFFICER', 'FIELD_STAFF', 'ZONAL_OFFICER', 'COMMISSIONER', 'CM_OFFICE']
    ).select_related('user')

    context = {
        'complaint': complaint,
        'available_staff': available_staff,
        'officer_level': curr_level,
        'can_escalate_plus_one': next_level_code is not None,
        'next_escalation_target': next_target_label,
        'next_level_code': next_level_code,
    }
    return render(request, 'officer/complaint_detail.html', context)


@policymaker_required
def policymaker_dashboard(request):
    """Policymaker Executive Console: Multi-Zone Granularity, Hotspot clusters, KPI signals & Gemini Capital Project Insights."""
    profile = getattr(request.user, 'profile', None)
    cluster_param = request.GET.get('cluster')

    if profile and profile.cluster and profile.cluster.is_active:
        cluster = profile.cluster
    elif cluster_param:
        cluster = Cluster.objects.filter(Q(id=cluster_param) | Q(code=cluster_param), is_active=True).first()
    else:
        cluster = Cluster.objects.filter(is_active=True).first()

    # Ward-level or Zone-level Policymaker Scoping
    policymaker_ward = profile.ward if profile else None
    policymaker_zone = profile.zone if profile else (profile.ward.zone if profile and profile.ward else None)

    zone_param = request.GET.get('zone', '')
    ward_param = request.GET.get('ward', '')

    if policymaker_ward:
        # Strictly locked to the Policymaker's assigned ward
        selected_ward_num = str(policymaker_ward.number)
        selected_zone_num = str(policymaker_zone.number) if policymaker_zone else 'ALL'
    elif policymaker_zone:
        selected_zone_num = str(policymaker_zone.number)
        selected_ward_num = ward_param or 'ALL'
    else:
        selected_zone_num = zone_param or 'ALL'
        selected_ward_num = ward_param or 'ALL'

    complaints = Complaint.objects.filter(cluster=cluster)
    if selected_ward_num != 'ALL' and selected_ward_num.isdigit():
        complaints = complaints.filter(ward__number=int(selected_ward_num))
    elif selected_zone_num != 'ALL' and selected_zone_num.isdigit():
        complaints = complaints.filter(zone__number=int(selected_zone_num))

    total_count = complaints.count()
    resolved_count = complaints.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED']).count()
    escalated_count = complaints.filter(is_sla_breached=True).count()
    overdue_count = sum(1 for c in complaints if c.is_overdue)

    # Department breakdown with ward/zone filter
    dept_filter_q = Q()
    if selected_ward_num != 'ALL' and selected_ward_num.isdigit():
        dept_filter_q = Q(complaints__ward__number=int(selected_ward_num))
    elif selected_zone_num != 'ALL' and selected_zone_num.isdigit():
        dept_filter_q = Q(complaints__zone__number=int(selected_zone_num))

    dept_stats = Department.objects.filter(cluster=cluster).annotate(
        total=Count('complaints', filter=dept_filter_q),
        open_count=Count('complaints', filter=(~Q(complaints__status__in=['RESOLVED', 'CITIZEN_CONFIRMED']) & dept_filter_q)),
        breached_count=Count('complaints', filter=(Q(complaints__is_sla_breached=True) & dept_filter_q))
    ).order_by('-total')

    # Zone breakdown
    zone_stats = Zone.objects.filter(cluster=cluster).annotate(
        total=Count('complaints'),
        open_count=Count('complaints', filter=~Q(complaints__status__in=['RESOLVED', 'CITIZEN_CONFIRMED']))
    ).order_by('number')

    # AI Capital Project Recommendations strictly scoped to jurisdiction
    all_recommendations = CapitalProjectRecommendation.objects.filter(cluster=cluster).order_by('-priority_score') if cluster else CapitalProjectRecommendation.objects.all().order_by('-priority_score')
    
    # 1. Base filter by user's assigned jurisdiction (e.g. Ward 142 Policymaker ONLY sees Ward 142)
    recommendations = filter_capital_projects_for_user(request.user, all_recommendations)

    # 2. If user is statewide / unassigned ward, apply dropdown filters
    if not policymaker_ward:
        if selected_ward_num != 'ALL' and selected_ward_num.isdigit():
            w_int = int(selected_ward_num)
            recommendations = [r for r in recommendations if r.is_visible_to_ward(w_int)]
        elif selected_zone_num != 'ALL' and selected_zone_num.isdigit():
            z_int = int(selected_zone_num)
            recommendations = [r for r in recommendations if r.is_visible_to_zone(z_int)]

    # Planned Work filtering and KPI aggregation
    tab = request.GET.get('tab', 'all')
    planned_recommendations = [r for r in recommendations if getattr(r, 'is_planned', False) or r.status == 'PLANNED']
    planned_count = len(planned_recommendations)
    planned_budget_total = sum(r.estimated_budget_inr for r in planned_recommendations)

    if tab == 'planned':
        displayed_recommendations = planned_recommendations
    else:
        displayed_recommendations = recommendations

    # Available wards for dropdown filter
    if policymaker_zone:
        filterable_wards = Ward.objects.filter(zone=policymaker_zone).order_by('number')
    else:
        filterable_wards = Ward.objects.filter(zone__cluster=cluster).order_by('number') if cluster else Ward.objects.all().order_by('number')

    context = {
        'cluster': cluster,
        'profile': profile,
        'selected_zone_num': selected_zone_num,
        'selected_ward_num': selected_ward_num,
        'policymaker_zone': policymaker_zone,
        'policymaker_ward': policymaker_ward,
        'total_count': total_count,
        'resolved_count': resolved_count,
        'escalated_count': escalated_count,
        'overdue_count': overdue_count,
        'resolution_rate': round((resolved_count / total_count * 100), 1) if total_count > 0 else 0,
        'dept_stats': dept_stats,
        'zone_stats': zone_stats,
        'all_zones': Zone.objects.filter(cluster=cluster),
        'all_wards': filterable_wards,
        'recommendations': displayed_recommendations,
        'all_recommendations_count': len(recommendations),
        'planned_count': planned_count,
        'planned_budget_total': planned_budget_total,
        'tab': tab,
    }
    return render(request, 'policymaker/dashboard.html', context)


@policymaker_required
def toggle_planned_work(request, project_id):
    """
    Adds a capital project proposal to (or removes from) the Policymaker's Planned Work list.
    Strictly enforces jurisdiction check.
    """
    project = get_object_or_404(CapitalProjectRecommendation, id=project_id)

    # Enforce jurisdiction access
    if not can_access_capital_project(request.user, project):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Permission denied for this jurisdiction.'}, status=403)
        messages.error(request, "You do not have jurisdiction to plan capital projects for this area.")
        return redirect('policymaker_dashboard')

    action = request.POST.get('action') or request.GET.get('action')
    if action == 'remove' or (action == 'toggle' and project.is_planned):
        project.unmark_planned()
        msg = f"'{project.title}' removed from Planned Work List."
        is_planned = False
        messages.info(request, msg)
    else:
        project.mark_as_planned(user=request.user)
        msg = f"'{project.title}' added to Planned Work List."
        is_planned = True
        messages.success(request, msg)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        cluster = project.cluster
        all_recs = CapitalProjectRecommendation.objects.filter(cluster=cluster) if cluster else CapitalProjectRecommendation.objects.all()
        user_recs = filter_capital_projects_for_user(request.user, all_recs)
        planned_count = sum(1 for r in user_recs if getattr(r, 'is_planned', False) or r.status == 'PLANNED')
        return JsonResponse({
            'status': 'success',
            'is_planned': is_planned,
            'project_id': project.id,
            'planned_count': planned_count,
            'message': msg
        })

    referrer = request.META.get('HTTP_REFERER')
    if referrer:
        return redirect(referrer)
    return redirect('policymaker_dashboard')


@policymaker_required
def download_planned_work(request):
    """
    Exports the Policymaker's Planned Work list as a downloadable CSV or Excel (.xlsx) file.
    Strictly scoped to the policymaker's jurisdiction.
    """
    profile = getattr(request.user, 'profile', None)
    cluster_param = request.GET.get('cluster')

    if profile and profile.cluster and profile.cluster.is_active:
        cluster = profile.cluster
    elif cluster_param:
        cluster = Cluster.objects.filter(Q(id=cluster_param) | Q(code=cluster_param), is_active=True).first()
    else:
        cluster = Cluster.objects.filter(is_active=True).first()
    all_recommendations = CapitalProjectRecommendation.objects.filter(cluster=cluster).order_by('-priority_score') if cluster else CapitalProjectRecommendation.objects.all().order_by('-priority_score')
    
    # Base filter by user's assigned jurisdiction
    recommendations = filter_capital_projects_for_user(request.user, all_recommendations)

    # Filter to planned work items
    planned_projects = [r for r in recommendations if getattr(r, 'is_planned', False) or r.status == 'PLANNED']

    scope = request.GET.get('scope', 'planned')
    export_list = recommendations if scope == 'all' else planned_projects

    export_format = request.GET.get('format', 'csv').lower()
    timestamp_str = timezone.now().strftime('%Y%m%d_%H%M%S')
    profile = getattr(request.user, 'profile', None)
    
    jurisdiction_label = "Citywide"
    if profile and profile.ward:
        jurisdiction_label = f"Ward_{profile.ward.number}"
    elif profile and profile.zone:
        jurisdiction_label = f"Zone_{profile.zone.number}"

    filename_base = f"Planned_Work_List_{jurisdiction_label}_{timestamp_str}"

    if export_format in ['excel', 'xlsx']:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Planned Capital Works"

        ws.merge_cells('A1:J1')
        title_cell = ws['A1']
        title_cell.value = f"DIGITAL PUBLIC INFRASTRUCTURE GOVERNANCE — PLANNED CAPITAL WORK LIST ({jurisdiction_label.replace('_', ' ')})"
        title_cell.font = Font(name='Arial', size=14, bold=True, color='FFFFFF')
        title_cell.fill = PatternFill(start_color='1E3A8A', end_color='1E3A8A', fill_type='solid')
        title_cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 36

        ws.merge_cells('A2:J2')
        sub_cell = ws['A2']
        sub_cell.value = f"Generated by: {request.user.get_full_name() or request.user.username} | Date: {timezone.now().strftime('%d-%b-%Y %H:%M')} | Total Planned Projects: {len(export_list)}"
        sub_cell.font = Font(name='Arial', size=10, italic=True, color='475569')
        sub_cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[2].height = 20

        headers = [
            'S.No', 'Project Title', 'Sector', 'Status', 'Affected Wards',
            'Affected Zones', 'Estimated Budget (INR)', 'Priority Score',
            'Problem Statement', 'Proposed Capital Intervention'
        ]
        ws.append([])
        ws.append(headers)
        ws.row_dimensions[4].height = 26

        header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='047857', end_color='047857', fill_type='solid')
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=4, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = thin_border

        row_num = 5
        total_budget = 0
        for idx, p in enumerate(export_list, start=1):
            budget_val = float(p.estimated_budget_inr or 0)
            total_budget += budget_val
            wards_str = ", ".join(str(w) for w in p.affected_wards) if p.affected_wards else "N/A"
            zones_str = ", ".join(str(z) for z in p.affected_zones) if p.affected_zones else "N/A"

            row_data = [
                idx,
                p.title,
                p.sector,
                p.get_status_display(),
                wards_str,
                zones_str,
                budget_val,
                p.priority_score,
                p.problem_statement,
                p.proposed_solution
            ]
            ws.append(row_data)
            
            ws.cell(row=row_num, column=1).alignment = Alignment(horizontal='center', vertical='top')
            ws.cell(row=row_num, column=7).number_format = '₹#,##0.00'
            ws.cell(row=row_num, column=7).alignment = Alignment(horizontal='right', vertical='top')
            ws.cell(row=row_num, column=8).alignment = Alignment(horizontal='center', vertical='top')
            
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=row_num, column=col_idx)
                c.border = thin_border
                c.alignment = Alignment(vertical='top', wrap_text=True)

            ws.row_dimensions[row_num].height = 45
            row_num += 1

        ws.append(['', 'TOTAL PLANNED CAPITAL BUDGET', '', '', '', '', total_budget, '', '', ''])
        summary_row = ws.max_row
        ws.row_dimensions[summary_row].height = 24
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=summary_row, column=col_idx)
            c.font = Font(name='Arial', size=11, bold=True)
            c.border = thin_border
            if col_idx == 7:
                c.number_format = '₹#,##0.00'
                c.fill = PatternFill(start_color='FEF08A', end_color='FEF08A', fill_type='solid')

        col_widths = {1: 8, 2: 35, 3: 18, 4: 16, 5: 16, 6: 14, 7: 22, 8: 14, 9: 40, 10: 45}
        for col_idx, width in col_widths.items():
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
        wb.save(response)
        return response

    else:
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
        response.write('\ufeff'.encode('utf8'))
        
        writer = csv.writer(response)
        writer.writerow([
            'S.No', 'Project Title', 'Sector', 'Status', 'Affected Wards',
            'Affected Zones', 'Estimated Budget (INR)', 'Priority Score',
            'Problem Statement', 'Proposed Capital Intervention', 'AI Rationale',
            'Planned Date', 'Planned By'
        ])

        for idx, p in enumerate(export_list, start=1):
            wards_str = "; ".join(str(w) for w in p.affected_wards) if p.affected_wards else ""
            zones_str = "; ".join(str(z) for z in p.affected_zones) if p.affected_zones else ""
            planned_date_str = p.planned_at.strftime('%Y-%m-%d %H:%M') if p.planned_at else ""
            planned_by_str = p.planned_by.get_full_name() or p.planned_by.username if p.planned_by else ""

            writer.writerow([
                idx,
                p.title,
                p.sector,
                p.get_status_display(),
                wards_str,
                zones_str,
                f"{p.estimated_budget_inr:.2f}",
                f"{p.priority_score:.1f}",
                p.problem_statement,
                p.proposed_solution,
                p.ai_rationale,
                planned_date_str,
                planned_by_str
            ])

        return response


def trigger_ai_insights(request):
    """Triggers Gemini 3.8 Flash to synthesize fresh capital project recommendations."""
    internal_token = request.headers.get('X-Internal-Token') or request.GET.get('token')
    expected_token = getattr(settings, 'INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')
    is_internal_call = bool(internal_token and internal_token == expected_token)

    if not is_internal_call:
        if not request.user.is_authenticated or not can_access_policymaker_console(request.user):
            context = {
                'console_name': 'Policymaker Intelligence Hub',
                'user_role': get_user_role(request.user),
                'required_roles': ['POLICYMAKER', 'SUPERADMIN'],
                'path': request.path,
            }
            return render(request, 'errors/403_role_denied.html', context, status=403)

    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None
    cluster_param = request.GET.get('cluster')

    if profile and profile.cluster and profile.cluster.is_active:
        cluster = profile.cluster
    elif cluster_param:
        cluster = Cluster.objects.filter(Q(id=cluster_param) | Q(code=cluster_param), is_active=True).first()
    else:
        cluster = Cluster.objects.filter(is_active=True).first()
    recs = []
    if cluster:
        recent_complaints = Complaint.objects.filter(
            cluster=cluster
        ).values('title', 'category__name', 'department__name', 'zone__number', 'ward__number', 'severity', 'status')[:50]

        recs = gemini_service.synthesize_policymaker_insights(
            cluster_name=cluster.name,
            complaints_data=list(recent_complaints)
        )

        for rec in recs:
            CapitalProjectRecommendation.objects.update_or_create(
                cluster=cluster,
                title=rec['title'],
                defaults={
                    'sector': rec.get('sector', 'Civic Infrastructure'),
                    'affected_zones': rec.get('affected_zones', []),
                    'affected_wards': rec.get('affected_wards', []),
                    'complaint_cluster_count': rec.get('complaint_cluster_count', 1),
                    'problem_statement': rec.get('problem_statement', ''),
                    'proposed_solution': rec.get('proposed_solution', ''),
                    'estimated_budget_inr': rec.get('estimated_budget_inr', 10000000.00),
                    'priority_score': rec.get('priority_score', 85.0),
                    'ai_rationale': rec.get('ai_rationale', ''),
                    'status': 'PROPOSED'
                }
            )
        if not is_internal_call:
            messages.success(request, f"Successfully synthesized {len(recs)} priority capital project recommendations via Gemini AI.")

    if is_internal_call or request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'status': 'SUCCESS',
            'cluster': cluster.name if cluster else None,
            'recommendations_generated': len(recs)
        })

    return redirect('policymaker_dashboard')


@superadmin_required
def cluster_onboard(request):
    """
    SuperAdmin 1-Click Cluster Onboarding:
    - Download Google-Sheets-ready template (.xlsx or CSV)
    - Upload custom workbook
    - Or 1-Click Launch Greater Chennai Corporation Sample
    """
    result = None
    sample_path = 'templates_data/gcc_government_cluster_template.xlsx'

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'load_sample_gcc':
            if os.path.exists(sample_path):
                try:
                    result = import_cluster_from_excel(sample_path)
                    messages.success(
                        request,
                        f"Successfully onboarded {result['cluster_name']}! Created {result['zones_count']} Zones, {result['wards_count']} Wards, {result['departments_count']} Departments, {result['categories_count']} SLA Categories, and {result['staff_count']} Staff Accounts."
                    )
                except Exception as e:
                    messages.error(request, f"Error onboarding cluster: {e}")
            else:
                messages.error(request, "Template file gcc_government_cluster_template.xlsx not found.")

        elif action == 'upload_workbook':
            uploaded_file = request.FILES.get('workbook_file')
            if uploaded_file:
                if not uploaded_file.name.lower().endswith(('.xlsx', '.xls')):
                    messages.error(request, "Invalid file format. Please upload an Excel workbook (.xlsx or .xls).")
                    return redirect('cluster_onboard')
                if uploaded_file.size > 25 * 1024 * 1024:
                    messages.error(request, "Uploaded workbook exceeds 25MB limit.")
                    return redirect('cluster_onboard')
                try:
                    result = import_cluster_from_excel(uploaded_file)
                    messages.success(
                        request,
                        f"Successfully onboarded {result['cluster_name']}! {result['zones_count']} Zones, {result['wards_count']} Wards provisioned."
                    )
                except Exception as e:
                    messages.error(request, f"Failed to parse uploaded workbook: {e}")
            else:
                messages.error(request, "Please choose an Excel workbook (.xlsx) to upload.")

        elif action == 'toggle_status':
            cluster_id = request.POST.get('cluster_id')
            if cluster_id:
                c = Cluster.objects.filter(id=cluster_id).first()
                if c:
                    c.is_active = not c.is_active
                    c.save(update_fields=['is_active'])
                    status_label = "enabled and activated" if c.is_active else "disabled and deactivated"
                    messages.success(request, f"Cluster '{c.name}' ({c.code}) has been successfully {status_label}.")
                    return redirect('cluster_onboard')

    clusters = Cluster.objects.all().prefetch_related('zones', 'zones__wards', 'departments').order_by('name')
    active_clusters_count = clusters.filter(is_active=True).count()
    disabled_clusters_count = clusters.filter(is_active=False).count()

    context = {
        'clusters': clusters,
        'active_clusters_count': active_clusters_count,
        'disabled_clusters_count': disabled_clusters_count,
        'total_clusters_count': clusters.count(),
        'sample_exists': os.path.exists(sample_path),
        'result': result,
    }
    return render(request, 'superadmin/cluster_onboard.html', context)


@superadmin_required
def toggle_cluster_status(request, cluster_id):
    """
    SuperAdmin action to enable or disable a Municipal Cluster.
    Toggles the is_active flag on the Cluster model without deleting underlying data.
    """
    cluster = get_object_or_404(Cluster, id=cluster_id)
    if request.method == 'POST':
        cluster.is_active = not cluster.is_active
        cluster.save(update_fields=['is_active'])
        status_label = "enabled and activated" if cluster.is_active else "disabled and deactivated"
        messages.success(request, f"Cluster '{cluster.name}' ({cluster.code}) has been successfully {status_label}.")
    else:
        messages.warning(request, "Cluster activation state can only be toggled via POST request.")

    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or reverse('cluster_onboard')
    return redirect(next_url)


@superadmin_required
def download_template(request):
    """
    Serves the standardized Local Government Cluster Excel template:
    - ?type=sample (default): Greater Chennai Corporation Master template
    - ?type=blank: Clean, multi-sheet starter template for onboarding any ULB
    - ?type=export&cluster_id=<id>: Direct Excel export of an active cluster's live hierarchy
    """
    tmpl_type = request.GET.get('type', 'sample').lower()

    if tmpl_type == 'blank':
        from core.cluster_importer import generate_blank_cluster_template
        bytes_data = generate_blank_cluster_template()
        response = HttpResponse(bytes_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="dpig_blank_cluster_template.xlsx"'
        return response

    elif tmpl_type == 'export':
        cluster_id = request.GET.get('cluster_id')
        from core.cluster_importer import export_cluster_to_excel
        target_cluster = None
        if cluster_id:
            target_cluster = Cluster.objects.filter(id=cluster_id).first()
        if not target_cluster:
            target_cluster = Cluster.objects.filter(is_active=True).first()
        if not target_cluster:
            messages.error(request, "No cluster available for export.")
            return redirect('cluster_onboard')
        bytes_data = export_cluster_to_excel(target_cluster)
        response = HttpResponse(bytes_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="cluster_export_{target_cluster.code.lower()}.xlsx"'
        return response

    sample_path = 'templates_data/gcc_government_cluster_template.xlsx'
    if os.path.exists(sample_path):
        with open(sample_path, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename="gcc_local_government_cluster_template.xlsx"'
            return response

    from core.cluster_importer import export_cluster_to_excel
    active_cluster = Cluster.objects.filter(is_active=True).first()
    if active_cluster:
        bytes_data = export_cluster_to_excel(active_cluster)
        response = HttpResponse(bytes_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="gcc_local_government_cluster_template.xlsx"'
        return response

    return HttpResponse("Template file not found", status=404)


@superadmin_required
def feature_permission_matrix(request):
    """
    SuperAdmin Control Center:
    - Complete Platform Oversight & Health
    - Feature Permission Matrix (Toggles for platform subsystems)
    - Demo Data Operations (Seed / Purge)
    - System Role & User Directory
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_matrix':
            matrix = load_feature_matrix()
            updates = {}
            for key in matrix.keys():
                updates[key] = f'feat_{key}' in request.POST
            save_feature_matrix(updates)
            messages.success(request, "Feature Permission Matrix configuration updated successfully!")
            return redirect('feature_permission_matrix')

    cluster = Cluster.objects.filter(is_active=True).first()
    all_clusters = Cluster.objects.all().prefetch_related('zones', 'zones__wards', 'departments').order_by('name')
    active_clusters_count = all_clusters.filter(is_active=True).count()
    disabled_clusters_count = all_clusters.filter(is_active=False).count()

    features = load_feature_matrix()
    profiles = UserProfile.objects.all().select_related('user', 'zone', 'ward', 'department')
    total_complaints = Complaint.objects.count()

    context = {
        'cluster': cluster,
        'clusters': all_clusters,
        'features': features,
        'profiles': profiles,
        'clusters_count': active_clusters_count,
        'total_clusters_count': all_clusters.count(),
        'active_clusters_count': active_clusters_count,
        'disabled_clusters_count': disabled_clusters_count,
        'zones_count': Zone.objects.count(),
        'wards_count': Ward.objects.count(),
        'depts_count': Department.objects.count(),
        'staff_count': profiles.exclude(role='CITIZEN').count(),
        'total_complaints': total_complaints,
    }
    return render(request, 'superadmin/matrix.html', context)


@superadmin_required
def seed_demo_data_view(request):
    """Seeds realistic demo complaints into GCC wards and zones."""
    if request.method == 'POST':
        count = seed_realistic_demo_complaints()
        messages.success(request, f"Successfully seeded {count} realistic Tamil Nadu civic grievances with valid DIGIPINs and SHA-256 audit chains!")
    return redirect('feature_permission_matrix')


@superadmin_required
def purge_demo_data_view(request):
    """Purges all demo complaints while preserving master geography."""
    if request.method == 'POST':
        count = purge_demo_complaints()
        messages.warning(request, f"Purged {count} demo complaints and associated audit records from the active database.")
    return redirect('feature_permission_matrix')


# --- REST / JSON Endpoints ---

@csrf_exempt
def api_digipin_encode(request):
    """API: Convert coordinates (lat, lon) to 10-char DIGIPIN and auto-resolve Ward."""
    try:
        lat_val = request.GET.get('lat') or request.POST.get('lat')
        lon_val = request.GET.get('lon') or request.GET.get('lng') or request.POST.get('lon') or request.POST.get('lng')
        lat = float(lat_val)
        lon = float(lon_val)
        precision = int(request.GET.get('precision', 10))
        raw_code = encode_digipin(lat, lon, precision=precision)
        formatted = format_digipin(raw_code)
        info = decode_digipin(raw_code)

        # Auto-resolve Ward & Zone based on location and DIGIPIN
        cluster = Cluster.objects.filter(is_active=True).first()
        _, ward_info = resolve_ward_from_location(lat=lat, lon=lon, digipin=formatted, cluster=cluster)

        return JsonResponse({
            'status': 'SUCCESS',
            'digipin': formatted,
            'raw_digipin': raw_code,
            'latitude': lat,
            'longitude': lon,
            'bounding_box': info['bbox'],
            'precision_meters': "~3.8m" if precision == 10 else f"Level {precision}",
            'ward': ward_info
        })
    except Exception as e:
        return JsonResponse({'status': 'ERROR', 'message': str(e)}, status=400)


@csrf_exempt
def api_digipin_decode(request):
    """API: Convert DIGIPIN to geographic coordinates, bounding box, and auto-resolve Ward."""
    code = request.GET.get('code') or request.POST.get('code', '')
    try:
        data = decode_digipin(code)
        formatted = format_digipin(code)
        cluster = Cluster.objects.filter(is_active=True).first()
        _, ward_info = resolve_ward_from_location(lat=data['latitude'], lon=data['longitude'], digipin=formatted, cluster=cluster)
        return JsonResponse({
            'status': 'SUCCESS',
            'digipin': formatted,
            'ward': ward_info,
            **data
        })
    except Exception as e:
        return JsonResponse({'status': 'ERROR', 'message': str(e)}, status=400)


@csrf_exempt
def api_resolve_ward(request):
    """API: Auto-resolve Ward & Zone from (lat, lon) coordinates or DIGIPIN."""
    try:
        lat_val = request.GET.get('lat') or request.POST.get('lat')
        lon_val = request.GET.get('lon') or request.GET.get('lng') or request.POST.get('lon') or request.POST.get('lng')
        digipin = request.GET.get('digipin') or request.POST.get('digipin')

        lat = float(lat_val) if lat_val else None
        lon = float(lon_val) if lon_val else None

        cluster = Cluster.objects.filter(is_active=True).first()
        ward, ward_info = resolve_ward_from_location(lat=lat, lon=lon, digipin=digipin, cluster=cluster)
        if ward:
            return JsonResponse({'status': 'SUCCESS', 'ward': ward_info})
        return JsonResponse({'status': 'ERROR', 'message': 'Ward could not be resolved for given location.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'ERROR', 'message': str(e)}, status=400)


def api_complaints_geojson(request):
    """API: GeoJSON of grievances for Google Maps / Leaflet overlay."""
    if not is_feature_enabled('open311_feed'):
        return JsonResponse({'status': 'DISABLED', 'message': 'Open311 & GeoJSON feed is currently disabled by administrator.'}, status=403)

    cluster_param = request.GET.get('cluster')
    profile = getattr(request.user, 'profile', None) if request.user.is_authenticated else None

    if cluster_param:
        cluster = Cluster.objects.filter(Q(id=cluster_param) | Q(code=cluster_param), is_active=True).first()
    elif profile and profile.cluster and profile.cluster.is_active:
        cluster = profile.cluster
    else:
        cluster = Cluster.objects.filter(is_active=True).first()

    complaints = Complaint.objects.filter(cluster=cluster).select_related('department', 'zone', 'ward')

    features = []
    for c in complaints:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [c.longitude, c.latitude]
            },
            "properties": {
                "ticket": c.ticket_number,
                "title": c.title,
                "status": c.status,
                "status_display": c.get_status_display(),
                "severity": c.severity,
                "digipin": c.digipin,
                "department": c.department.name if c.department else "",
                "zone": c.zone.number if c.zone else 0,
                "ward": c.ward.number if c.ward else 0,
                "is_sla_breached": c.is_sla_breached,
                "remaining_seconds": c.remaining_sla_seconds,
            }
        })

    return JsonResponse({
        "type": "FeatureCollection",
        "features": features
    })


def api_verify_audit_chain(request, ticket_number):
    """API: Cryptographically validates the SHA-256 hash chain for a grievance."""
    complaint = get_object_or_404(Complaint, ticket_number=ticket_number)
    logs = list(complaint.audit_logs.all().order_by('created_at'))

    chain_valid = True
    verified_blocks = []

    for i, block in enumerate(logs):
        is_valid = block.verify_integrity()
        if not is_valid:
            chain_valid = False
        verified_blocks.append({
            "index": i + 1,
            "action": block.action,
            "timestamp": block.created_at.isoformat(),
            "actor": block.performed_by.username if block.performed_by else "SYSTEM",
            "previous_hash": block.previous_hash,
            "current_hash": block.current_hash,
            "verified": is_valid
        })

    return JsonResponse({
        "ticket": complaint.ticket_number,
        "is_chain_intact": chain_valid,
        "total_blocks": len(logs),
        "genesis_hash": logs[0].current_hash if logs else None,
        "latest_hash": logs[-1].current_hash if logs else None,
        "blocks": verified_blocks
    })


def api_detect_script(request):
    """API: Detects Unicode code points for 10 Indian scripts and generates translation headers."""
    text = request.GET.get('text', '') or request.POST.get('text', '')
    detection = detect_unicode_script(text)
    header = generate_translation_header(detection)
    h_title, h_desc = heuristic_translate_indian_text(text, detection)

    return JsonResponse({
        "status": "SUCCESS",
        "script": detection.get("script"),
        "language": detection.get("language"),
        "lang_code": detection.get("lang_code"),
        "hex_range": detection.get("hex_range"),
        "is_indian_script": detection.get("is_indian_script", False),
        "is_transliterated": detection.get("is_transliterated", False),
        "translation_header": header,
        "translated_title": h_title,
        "generated_title": h_title,
        "translated_description": h_desc,
        "matched_code_points": detection.get("matched_code_points", 0),
        "char_count": detection.get("char_count", 0),
    })


def switch_demo_role(request, role):
    """Helper for testing: Instantly switch between roles with appropriate hierarchy levels and Aadhaar attributes."""
    if not (getattr(settings, 'ENABLE_DEMO_ROLE_SWITCHER', False) or settings.DEBUG):
        return HttpResponseForbidden("Demo role switching is strictly disabled in production environments.")

    role = role.upper()
    role_usernames = {
        'SUPERADMIN': 'superadmin',
        'DEPT_ADMIN': 'deptadmin.roads',
        'DEPT_ADMIN_ROADS': 'deptadmin.roads',
        'DEPT_ADMIN_SWM': 'deptadmin.swm',
        'DEPT_ADMIN_HEALTH': 'deptadmin.health',
        'COMMISSIONER': 'commissioner',
        'ZONAL_OFFICER': 'zo1',
        'ZONAL_OFFICER_ZO1': 'zo1',
        'ZONAL_OFFICER_ROYAPURAM': 'zo5',
        'ZONAL_OFFICER_ZO5': 'zo5',
        'WARD_OFFICER': 'ae.ward108',
        'FIELD_STAFF': 'si.ward52',
        'POLICYMAKER': 'policy.analyst',
        'POLICYMAKER_WARD142': 'policy.ward142',
        'AUDITOR': 'auditor.general',
        'CITIZEN': 'citizen.demo',
    }
    uname = role_usernames.get(role, 'citizen.demo')
    user = User.objects.filter(username=uname).first()
    cluster = Cluster.objects.filter(is_active=True).first()

    if not user:
        user, _ = User.objects.get_or_create(
            username=uname,
            defaults={'email': f"{uname}@example.com", 'first_name': role.title()}
        )
        user.set_password('Admin@Dpig2026')
        user.is_staff = role != 'CITIZEN'
        user.is_superuser = role == 'SUPERADMIN'
        user.save()

    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={'role': 'DEPT_ADMIN' if role.startswith('DEPT_ADMIN') else role, 'cluster': cluster}
    )

    # Configure role hierarchy, jurisdiction and Aadhaar attributes
    profile.role = 'DEPT_ADMIN' if role.startswith('DEPT_ADMIN') else role
    profile.cluster = cluster
    if role.startswith('DEPT_ADMIN'):
        dept_code = 'ROADS'
        if 'SWM' in role:
            dept_code = 'SWM'
        elif 'HEALTH' in role:
            dept_code = 'HEALTH'
        elif 'SWD' in role:
            dept_code = 'SWD'
        d = Department.objects.filter(cluster=cluster, code=dept_code).first() or Department.objects.first()
        profile.role = 'DEPT_ADMIN'
        profile.department = d
        profile.hierarchy_level = 4
        profile.designation = f"Departmental Administrator - {d.name if d else 'Statewide'}"
        user.is_staff = True
        user.first_name = f"{d.name if d else 'Department'} Administrator"
    elif role == 'SUPERADMIN':
        profile.hierarchy_level = 3
        profile.designation = 'State SuperAdmin (Executive Control)'
        user.is_superuser = True
        user.is_staff = True
    elif role == 'COMMISSIONER':
        profile.hierarchy_level = 3
        profile.designation = 'Municipal Commissioner IAS'
        user.is_staff = True
    elif role in ['ZONAL_OFFICER', 'ZONAL_OFFICER_ZO1']:
        profile.role = 'ZONAL_OFFICER'
        profile.hierarchy_level = 2
        z = Zone.objects.filter(cluster=cluster, number=1).first() or Zone.objects.first()
        profile.zone = z
        profile.designation = f"Zonal Officer - Thiruvottiyur ({z.name if z else 'Zone 1'})"
        user.first_name = "Dr. K."
        user.last_name = "Senthil"
        user.is_staff = True
    elif role in ['ZONAL_OFFICER_ROYAPURAM', 'ZONAL_OFFICER_ZO5']:
        profile.role = 'ZONAL_OFFICER'
        profile.hierarchy_level = 2
        z = Zone.objects.filter(cluster=cluster, number=5).first() or Zone.objects.first()
        profile.zone = z
        profile.designation = f"Zonal Officer - Royapuram ({z.name if z else 'Zone 5'})"
        user.first_name = "Dr. M."
        user.last_name = "Suresh"
        user.is_staff = True
    elif role == 'WARD_OFFICER':
        profile.hierarchy_level = 1
        z = Zone.objects.filter(cluster=cluster, number=8).first() or Zone.objects.first()
        w = Ward.objects.filter(zone=z, number=108).first() or (z.wards.first() if z else None)
        d = Department.objects.filter(cluster=cluster, code='ROADS').first() or Department.objects.first()
        profile.zone = z
        profile.ward = w
        profile.department = d
        profile.designation = f"Ward Assistant Engineer ({w.name if w else 'Ward 108'})"
        user.is_staff = True
    elif role == 'FIELD_STAFF':
        profile.hierarchy_level = 1
        z = Zone.objects.filter(cluster=cluster, number=5).first() or Zone.objects.first()
        w = Ward.objects.filter(zone=z, number=52).first() or (z.wards.first() if z else None)
        profile.zone = z
        profile.ward = w
        profile.designation = f"Sanitary Inspector / Field Staff ({w.name if w else 'Ward 52'})"
        user.is_staff = True
    elif role == 'POLICYMAKER':
        profile.hierarchy_level = 1
        z = Zone.objects.filter(cluster=cluster, number=1).first()
        profile.zone = z
        profile.ward = None
        profile.designation = "Senior Urban Policy Analyst (Zone 1 & Statewide)"
        user.is_staff = True
    elif role == 'POLICYMAKER_WARD142':
        profile.role = 'POLICYMAKER'
        profile.hierarchy_level = 1
        z = Zone.objects.filter(cluster=cluster, number=10).first() or Zone.objects.first()
        w = Ward.objects.filter(number=142).first()
        profile.zone = z
        profile.ward = w
        profile.designation = f"Ward 142 Policymaker & Local Representative ({w.name if w else 'Ward 142'})"
        user.first_name = "Ward 142 Policymaker"
        user.is_staff = True
    elif role == 'AUDITOR':
        profile.role = 'AUDITOR'
        profile.hierarchy_level = 5
        profile.zone = None
        profile.ward = None
        profile.department = None
        profile.designation = "Statutory Compliance Auditor (Statewide Governance Oversight)"
        user.first_name = "Thiru. S."
        user.last_name = "Raghavan"
        user.is_staff = True
    elif role == 'CITIZEN':
        profile.role = 'CITIZEN'
        profile.is_aadhaar_verified = True
        profile.aadhaar_last4 = '7890'
        profile.aadhaar_hash = hash_aadhaar('987654327890')
        profile.phone = '9840199999'
        profile.designation = 'Verified Resident Citizen'
        user.is_staff = False
        user.is_superuser = False

    profile.save()
    user.save()

    login(request, user)
    messages.info(request, f"Switched active demo profile to: {profile.hierarchy_label} ({user.username})")
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url and not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = None
    if not next_url:
        if role.startswith('DEPT_ADMIN'):
            next_url = '/dept-admin/'
        elif role in ['WARD_OFFICER', 'FIELD_STAFF', 'ZONAL_OFFICER', 'COMMISSIONER']:
            next_url = '/officer/'
        elif role in ['POLICYMAKER', 'POLICYMAKER_WARD142']:
            next_url = '/policymaker/'
        elif role == 'AUDITOR':
            next_url = '/auditor/'
        elif role == 'SUPERADMIN':
            next_url = '/superadmin/matrix/'
        else:
            next_url = '/'
    return redirect(next_url)


def citizen_register(request):
    """Citizen Registration: UIDAI 12-digit Aadhaar validation and simulated OTP verification."""
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if next_url and (not next_url.startswith('/') or next_url.startswith('//')):
        next_url = ''

    if request.user.is_authenticated:
        if get_user_role(request.user) == 'CITIZEN':
            return redirect(next_url or 'citizen_hub')
        return redirect('officer_dashboard' if can_access_officer_console(request.user) else 'policymaker_dashboard')

    cluster = Cluster.objects.filter(is_active=True).first()
    zones = Zone.objects.filter(cluster=cluster) if cluster else []

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        aadhaar_number = request.POST.get('aadhaar_number', '').strip()
        mobile_number = (request.POST.get('mobile_number') or request.POST.get('phone') or '').strip()
        otp_code = (request.POST.get('otp_code') or request.POST.get('aadhaar_otp') or request.POST.get('otp') or '').strip()
        password = request.POST.get('password', '')
        zone_id = request.POST.get('zone_id')
        ward_id = request.POST.get('ward_id')

        # Format validation
        if not validate_aadhaar_format(aadhaar_number):
            messages.error(request, "Invalid Aadhaar number. Must be a valid 12-digit number (not starting with 0 or 1).")
            return render(request, 'auth/citizen_register.html', {'zones': zones, 'cluster': cluster, 'form_data': request.POST, 'next': next_url})

        a_hash = hash_aadhaar(aadhaar_number)
        clean_a = clean_aadhaar_number(aadhaar_number)
        last4 = clean_a[-4:]

        # Check if Aadhaar is already registered
        existing_profile = UserProfile.objects.filter(aadhaar_hash=a_hash).first()
        if existing_profile:
            messages.warning(request, f"An account with Aadhaar ending in {last4} already exists. Please sign in or use password recovery.")
            return redirect(f"{reverse('citizen_login')}?next={next_url}" if next_url else 'citizen_login')

        # Verify OTP
        if not verify_aadhaar_otp(aadhaar_number, otp_code, purpose="SIGNUP"):
            messages.error(request, "Invalid or expired OTP. Please enter the 6-digit OTP received or use test code '123456'.")
            return render(request, 'auth/citizen_register.html', {'zones': zones, 'cluster': cluster, 'form_data': request.POST, 'next': next_url})

        # Generate username
        base_username = f"citizen.{last4}"
        username = base_username
        suffix = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}.{suffix}"
            suffix += 1

        # Create user
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=full_name,
            email=f"{username}@citizen.dpig.local"
        )
        user.is_staff = False
        user.is_superuser = False
        user.save()

        zone = Zone.objects.filter(id=zone_id).first() if zone_id else None
        ward = Ward.objects.filter(id=ward_id).first() if ward_id else None

        UserProfile.objects.create(
            user=user,
            cluster=cluster,
            role='CITIZEN',
            hierarchy_level=1,
            zone=zone,
            ward=ward,
            phone=mobile_number,
            designation='Verified Resident Citizen',
            aadhaar_hash=a_hash,
            aadhaar_last4=last4,
            is_aadhaar_verified=True
        )

        login(request, user)
        messages.success(request, f"Aadhaar Identity Verified! Welcome to DPIG Portal, {full_name}. Your Citizen ID is: {username}")
        return redirect(next_url or 'citizen_hub')

    context = {
        'zones': zones,
        'cluster': cluster,
        'next': next_url,
    }
    return render(request, 'auth/citizen_register.html', context)


def citizen_login(request):
    """Citizen Aadhaar Authentication: 1-Click OTP Login or Aadhaar/Username + Password."""
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    if next_url and (not next_url.startswith('/') or next_url.startswith('//')):
        next_url = ''

    if request.user.is_authenticated:
        if get_user_role(request.user) == 'CITIZEN':
            return redirect(next_url or 'citizen_hub')
        return redirect('officer_dashboard' if can_access_officer_console(request.user) else 'policymaker_dashboard')

    if request.method == 'POST':
        login_type = request.POST.get('login_type', 'otp')  # 'otp' or 'password'

        if login_type == 'otp':
            aadhaar_input = request.POST.get('aadhaar_number', '').strip()
            otp_code = request.POST.get('otp_code', '').strip()

            if not validate_aadhaar_format(aadhaar_input):
                messages.error(request, "Invalid 12-digit Aadhaar number format.")
                return render(request, 'auth/citizen_login.html', {'next': next_url})

            if not verify_aadhaar_otp(aadhaar_input, otp_code, purpose="LOGIN"):
                messages.error(request, "Invalid or expired Aadhaar OTP. Please enter the valid 6-digit code or test code '123456'.")
                return render(request, 'auth/citizen_login.html', {'aadhaar_number': aadhaar_input, 'next': next_url})

            a_hash = hash_aadhaar(aadhaar_input)
            profile = UserProfile.objects.filter(aadhaar_hash=a_hash, role='CITIZEN').select_related('user').first()

            if not profile:
                # If demo citizen or testing, link to citizen.demo
                cit_user = User.objects.filter(username='citizen.demo').first()
                if cit_user:
                    profile = cit_user.profile
                    profile.aadhaar_hash = a_hash
                    profile.aadhaar_last4 = clean_aadhaar_number(aadhaar_input)[-4:]
                    profile.is_aadhaar_verified = True
                    profile.save()
                else:
                    messages.error(request, "No citizen account linked to this Aadhaar. Please complete 1-minute registration first.")
                    return redirect(f"{reverse('citizen_register')}?next={next_url}" if next_url else 'citizen_register')

            login(request, profile.user)
            messages.success(request, f"Welcome back, {profile.user.first_name or profile.user.username}! Signed in via Aadhaar Authentication.")
            return redirect(next_url or 'citizen_hub')

        elif login_type == 'password':
            identifier = request.POST.get('identifier', '').strip()
            password = request.POST.get('password', '')

            # Check if identifier is an Aadhaar number
            if validate_aadhaar_format(identifier):
                a_hash = hash_aadhaar(identifier)
                profile = UserProfile.objects.filter(aadhaar_hash=a_hash, role='CITIZEN').select_related('user').first()
                if profile:
                    user = authenticate(request, username=profile.user.username, password=password)
                else:
                    user = None
            else:
                user = authenticate(request, username=identifier, password=password)

            if user and (getattr(user, 'profile', None) and user.profile.role == 'CITIZEN'):
                login(request, user)
                messages.success(request, f"Welcome, {user.first_name or user.username}!")
                return redirect(next_url or 'citizen_hub')
            elif user and (getattr(user, 'profile', None) and user.profile.role != 'CITIZEN'):
                messages.warning(request, "This account is a Municipal Officer account. Please use the Department Staff Sign In.")
                return redirect('login')
            else:
                messages.error(request, "Invalid Citizen credentials or password.")

    return render(request, 'auth/citizen_login.html', {'next': next_url})


def citizen_forgot_password(request):
    """Citizen Password & User ID Recovery via Aadhaar OTP (Strictly Citizen-Only)."""
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        otp_code = request.POST.get('otp_code', '').strip()
        new_password = request.POST.get('new_password', '')

        # Check if identifier matches any staff/officer
        staff_user = User.objects.filter(username=identifier).first()
        if staff_user and hasattr(staff_user, 'profile') and staff_user.profile.role != 'CITIZEN':
            messages.error(
                request,
                "Access Denied: Departmental Officer and Policymaker accounts are centrally managed by the Municipal SuperAdmin. "
                "Staff cannot reset credentials via public citizen recovery. Please contact your SuperAdmin."
            )
            return render(request, 'auth/citizen_forgot_password.html')

        # Check Aadhaar format or mobile
        if validate_aadhaar_format(identifier):
            clean_a = clean_aadhaar_number(identifier)
            a_hash = hash_aadhaar(clean_a)
            profile = UserProfile.objects.filter(aadhaar_hash=a_hash, role='CITIZEN').select_related('user').first()
        else:
            profile = UserProfile.objects.filter(Q(phone=identifier) | Q(user__username=identifier), role='CITIZEN').select_related('user').first()

        if not profile:
            messages.error(request, "No citizen account found matching that Aadhaar or mobile number.")
            return render(request, 'auth/citizen_forgot_password.html', {'identifier': identifier})

        # Verify OTP
        if not verify_aadhaar_otp(identifier, otp_code, purpose="RECOVERY"):
            messages.error(request, "Invalid or expired OTP. Please verify the code or use test code '123456'.")
            return render(request, 'auth/citizen_forgot_password.html', {'identifier': identifier, 'otp_sent': True})

        # Reset password
        user = profile.user
        user.set_password(new_password)
        user.save()

        messages.success(request, f"Password successfully updated for Citizen ID: {user.username}! Please sign in.")
        return redirect('citizen_login')

    return render(request, 'auth/citizen_forgot_password.html')


@csrf_exempt
def api_aadhaar_send_otp(request):
    """AJAX endpoint to generate and dispatch simulated UIDAI OTP."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST method required'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    aadhaar_number = data.get('aadhaar_number', '').strip()
    mobile = data.get('mobile_number', '').strip()
    purpose = data.get('purpose', 'SIGNUP').upper()

    if not validate_aadhaar_format(aadhaar_number):
        return JsonResponse({'success': False, 'message': 'Invalid Aadhaar format. Must be 12 digits (not starting with 0 or 1).'}, status=400)

    clean_a = clean_aadhaar_number(aadhaar_number)
    record, otp = generate_aadhaar_otp(clean_a, mobile, purpose=purpose)

    resp_payload = {
        'success': True,
        'message': f"UIDAI OTP dispatched to mobile linked with Aadhaar ending in {clean_a[-4:]}.",
        'masked_aadhaar': f"XXXX-XXXX-{clean_a[-4:]}",
        'expires_in_minutes': 10
    }
    if settings.DEBUG:
        resp_payload['simulated_otp'] = otp  # Sandbox development mode only

    return JsonResponse(resp_payload)


@csrf_exempt
def api_aadhaar_verify_otp(request):
    """AJAX endpoint to verify simulated UIDAI OTP."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST method required'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    aadhaar_number = (data.get('aadhaar_number') or '').strip()
    otp_code = (data.get('otp_code') or data.get('otp') or data.get('aadhaar_otp') or '').strip()
    purpose = (data.get('purpose') or 'SIGNUP').upper()

    if not validate_aadhaar_format(aadhaar_number):
        return JsonResponse({'status': 'ERROR', 'success': False, 'message': 'Invalid Aadhaar number.'}, status=400)

    is_valid = verify_aadhaar_otp(aadhaar_number, otp_code, purpose=purpose)
    if is_valid:
        clean_a = clean_aadhaar_number(aadhaar_number)
        return JsonResponse({
            'status': 'SUCCESS',
            'success': True,
            'message': 'Aadhaar identity verified successfully with UIDAI.',
            'last4': clean_a[-4:],
            'masked_aadhaar': f"XXXX-XXXX-{clean_a[-4:]}"
        })
    else:
        return JsonResponse({
            'status': 'ERROR',
            'success': False,
            'message': 'Invalid or expired OTP. Please try again or use evaluation code 123456.'
        }, status=400)


@superadmin_required
def superadmin_staff_management(request):
    """SuperAdmin Staff Management: Provision, configure hierarchy, reassign & control all Department Officers & Policymakers."""
    cluster = Cluster.objects.filter(is_active=True).first()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_staff':
            full_name = request.POST.get('full_name', '').strip()
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            role = request.POST.get('role', 'WARD_OFFICER')
            hierarchy_level = int(request.POST.get('hierarchy_level', 1))
            dept_id = request.POST.get('department_id')
            zone_id = request.POST.get('zone_id')
            ward_id = request.POST.get('ward_id')
            designation = request.POST.get('designation', '').strip()
            password = request.POST.get('password', 'Admin@Dpig2026')

            if User.objects.filter(username=username).exists():
                messages.error(request, f"Username '{username}' is already in use. Please select a unique username.")
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email or f"{username}@tn.gov.in",
                    password=password,
                    first_name=full_name
                )
                user.is_staff = True
                user.is_superuser = (role == 'SUPERADMIN')
                user.save()

                dept = Department.objects.filter(id=dept_id).first() if dept_id else None
                zone = Zone.objects.filter(id=zone_id).first() if zone_id else None
                ward = Ward.objects.filter(id=ward_id).first() if ward_id else None

                UserProfile.objects.create(
                    user=user,
                    cluster=cluster,
                    role=role,
                    hierarchy_level=hierarchy_level,
                    department=dept,
                    zone=zone,
                    ward=ward,
                    designation=designation or f"{role.replace('_', ' ').title()} - L{hierarchy_level}",
                    phone=phone
                )
                messages.success(request, f"Staff Member '{full_name}' ({username}) successfully appointed at Level {hierarchy_level}!")
                return redirect('superadmin_staff_management')

        elif action == 'edit_staff':
            staff_id = request.POST.get('staff_id')
            profile = get_object_or_404(UserProfile, id=staff_id)
            profile.designation = request.POST.get('designation', profile.designation)
            profile.role = request.POST.get('role', profile.role)
            profile.hierarchy_level = int(request.POST.get('hierarchy_level', profile.hierarchy_level))
            dept_id = request.POST.get('department_id')
            zone_id = request.POST.get('zone_id')
            ward_id = request.POST.get('ward_id')
            profile.department = Department.objects.filter(id=dept_id).first() if dept_id else None
            profile.zone = Zone.objects.filter(id=zone_id).first() if zone_id else None
            profile.ward = Ward.objects.filter(id=ward_id).first() if ward_id else None
            profile.phone = request.POST.get('phone', profile.phone)
            profile.save()

            user = profile.user
            user.first_name = request.POST.get('full_name', user.first_name)
            user.email = request.POST.get('email', user.email)
            user.save()

            messages.success(request, f"Updated profile for officer {user.username}.")
            return redirect('superadmin_staff_management')

        elif action == 'reset_password':
            staff_id = request.POST.get('staff_id')
            profile = get_object_or_404(UserProfile, id=staff_id)
            new_pwd = request.POST.get('new_password', 'Admin@Dpig2026')
            profile.user.set_password(new_pwd)
            profile.user.save()
            messages.success(request, f"Password successfully reset for {profile.user.username}.")
            return redirect('superadmin_staff_management')

        elif action == 'bulk_upload':
            file_obj = request.FILES.get('officers_file')
            if not file_obj:
                messages.error(request, "Please select a Google Sheet / Excel file to upload.")
                return redirect('superadmin_staff_management')

            if not file_obj.name.lower().endswith(('.xlsx', '.xls', '.csv')):
                messages.error(request, "Invalid file format. Supported formats: .xlsx, .xls, .csv.")
                return redirect('superadmin_staff_management')
            if file_obj.size > 25 * 1024 * 1024:
                messages.error(request, "Uploaded file exceeds 25MB limit.")
                return redirect('superadmin_staff_management')

            from core.officer_bulk_service import parse_and_provision_officers
            res = parse_and_provision_officers(file_obj, cluster=cluster, update_existing=True)
            request.session['bulk_officer_import_report'] = res

            if res['status'] == 'SUCCESS':
                messages.success(
                    request,
                    f"Successfully provisioned {res['total_rows']} officers ({res['created_count']} created, {res['updated_count']} updated) from Google Sheet template!"
                )
            elif res['status'] == 'PARTIAL':
                messages.warning(
                    request,
                    f"Google Sheet import completed with notices: {res['created_count']} created, {res['updated_count']} updated, {res['error_count']} skipped. Notices: {'; '.join(res['errors'][:5])}"
                )
            else:
                messages.error(
                    request,
                    f"Failed to process Google Sheet: {'; '.join(res['errors'][:5])}"
                )
            return redirect('superadmin_staff_management')

        elif action == 'toggle_status':
            staff_id = request.POST.get('staff_id')
            profile = get_object_or_404(UserProfile, id=staff_id)
            profile.user.is_active = not profile.user.is_active
            profile.user.save()
            status_str = "activated" if profile.user.is_active else "deactivated"
            messages.info(request, f"Officer {profile.user.username} {status_str}.")
            return redirect('superadmin_staff_management')

    # Query all staff
    staff_profiles = UserProfile.objects.exclude(role='CITIZEN').select_related(
        'user', 'zone', 'ward', 'department'
    ).order_by('hierarchy_level', 'role', 'user__username')

    # Filter params
    dept_filter = request.GET.get('dept', 'ALL')
    level_filter = request.GET.get('level', 'ALL')
    role_filter = request.GET.get('role', 'ALL')
    zone_filter = request.GET.get('zone', 'ALL')

    filtered_staff = staff_profiles
    if dept_filter != 'ALL':
        filtered_staff = filtered_staff.filter(department__code=dept_filter)
    if level_filter != 'ALL':
        if level_filter.isdigit():
            filtered_staff = filtered_staff.filter(hierarchy_level=int(level_filter))
        elif level_filter.upper() in ['DL1', 'DL2', 'DL3', 'CL1', 'CL2', 'CL3', 'CM_OFFICE']:
            from core.models import LEVEL_CODE_TO_INT
            filtered_staff = filtered_staff.filter(hierarchy_level=LEVEL_CODE_TO_INT.get(level_filter.upper(), 1))
    if role_filter != 'ALL':
        filtered_staff = filtered_staff.filter(role=role_filter)
    if zone_filter != 'ALL' and zone_filter.isdigit():
        filtered_staff = filtered_staff.filter(zone__number=int(zone_filter))

    counts = {
        'total': staff_profiles.count(),
        'dl1': staff_profiles.filter(hierarchy_level=1).count(),
        'dl2': staff_profiles.filter(hierarchy_level=2).count(),
        'dl3': staff_profiles.filter(hierarchy_level=3).count(),
        'cl1': staff_profiles.filter(hierarchy_level=4).count(),
        'cl2': staff_profiles.filter(hierarchy_level=5).count(),
        'cl3': staff_profiles.filter(hierarchy_level=6).count(),
        'cm_office': staff_profiles.filter(Q(hierarchy_level=7) | Q(role='CM_OFFICE')).count(),
        'policymakers': staff_profiles.filter(role='POLICYMAKER').count(),
        'auditors': staff_profiles.filter(role='AUDITOR').count(),
    }

    context = {
        'staff_list': filtered_staff,
        'counts': counts,
        'dept_filter': dept_filter,
        'level_filter': level_filter,
        'role_filter': role_filter,
        'zone_filter': zone_filter,
        'departments': Department.objects.filter(cluster=cluster),
        'zones': Zone.objects.filter(cluster=cluster),
        'wards': Ward.objects.filter(zone__cluster=cluster),
        'bulk_report': request.session.pop('bulk_officer_import_report', None),
    }
    return render(request, 'superadmin/staff_management.html', context)


@dept_admin_required
def download_officer_template(request):
    """
    Serves downloadable Google Sheet template (XLSX with native Excel dropdowns / CSV)
    pre-structured for bulk creating municipal officers across workflow levels.
    Accessible to both SuperAdmins and Departmental Administrators.
    """
    fmt = request.GET.get('format', 'xlsx').lower()

    dept = None
    user_role = get_user_role(request.user)
    if user_role == 'DEPT_ADMIN':
        dept = get_active_dept_for_request(request)
    elif request.GET.get('dept'):
        dept = Department.objects.filter(code__iexact=request.GET.get('dept')).first()
        if not dept:
            dept = Department.objects.filter(id=request.GET.get('dept')).first()

    cluster = (dept.cluster if dept else None) or Cluster.objects.filter(is_active=True).first()

    from core.officer_bulk_service import export_officer_template
    bytes_data, content_type, filename = export_officer_template(fmt, department=dept, cluster=cluster)
    response = HttpResponse(bytes_data, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@dept_admin_required
def export_officer_roster_view(request):
    """
    Exports the active municipal officer roster to Excel or CSV in template-compatible format.
    Allows administrators to review rosters offline or make bulk modifications and re-upload.
    """
    fmt = request.GET.get('format', 'xlsx').lower()
    user_role = get_user_role(request.user)
    dept = None
    if user_role == 'DEPT_ADMIN':
        dept = get_active_dept_for_request(request)
    elif request.GET.get('dept'):
        dept = Department.objects.filter(code__iexact=request.GET.get('dept')).first()
        if not dept:
            dept = Department.objects.filter(id=request.GET.get('dept')).first()

    cluster = (dept.cluster if dept else None) or Cluster.objects.filter(is_active=True).first()
    from core.officer_bulk_service import export_officers_to_excel
    bytes_data, content_type, filename = export_officers_to_excel(cluster=cluster, department=dept, file_format=fmt)
    response = HttpResponse(bytes_data, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@superadmin_required
def bulk_upload_officers(request):
    """
    Direct endpoint for bulk uploading officers from Google Sheet / Excel.
    """
    file_obj = request.FILES.get('officers_file') or request.FILES.get('template_file')
    if request.method == 'POST' and file_obj:
        if not file_obj.name.lower().endswith(('.xlsx', '.xls', '.csv')):
            messages.error(request, "Invalid file format. Supported formats: .xlsx, .xls, .csv.")
            return redirect('superadmin_staff_management')
        if file_obj.size > 25 * 1024 * 1024:
            messages.error(request, "Uploaded spreadsheet exceeds 25MB limit.")
            return redirect('superadmin_staff_management')

        cluster = Cluster.objects.filter(is_active=True).first()
        from core.officer_bulk_service import parse_and_provision_officers
        res = parse_and_provision_officers(file_obj, cluster=cluster, update_existing=True)
        request.session['bulk_officer_import_report'] = res

        if res['status'] == 'SUCCESS':
            messages.success(
                request,
                f"Successfully provisioned {res['total_rows']} officers ({res['created_count']} created, {res['updated_count']} updated) from Google Sheet template!"
            )
        elif res['status'] == 'PARTIAL':
            messages.warning(
                request,
                f"Google Sheet import completed with notices: {res['created_count']} created, {res['updated_count']} updated, {res['error_count']} skipped. Notices: {'; '.join(res['errors'][:5])}"
            )
        else:
            messages.error(
                request,
                f"Failed to process Google Sheet: {'; '.join(res['errors'][:5])}"
            )
        return redirect('superadmin_staff_management')

    messages.error(request, "No spreadsheet file was uploaded.")
    return redirect('superadmin_staff_management')


# ==============================================================================
# DEPARTMENTAL ADMINISTRATION: STAFF, ALERTS & WELFARE SCHEMES
# ==============================================================================

def parse_form_datetime(val_str, default=None):
    """Parses HTML5 datetime-local string to timezone-aware datetime."""
    if not val_str or not str(val_str).strip():
        return default
    try:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(val_str.strip())
        if dt is None:
            from datetime import datetime
            dt = datetime.fromisoformat(val_str.strip())
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    except Exception:
        return default


def get_active_dept_for_request(request):
    """
    Resolves the Department for the current administrative session:
    - DEPT_ADMIN is strictly locked to their assigned profile department.
    - SUPERADMIN can pass ?dept=<id_or_code> to switch departments.
    """
    user = request.user
    role = get_user_role(user)
    profile = getattr(user, 'profile', None)

    if role == 'DEPT_ADMIN' and profile and profile.department:
        return profile.department

    dept_id = request.GET.get('dept') or request.POST.get('department_id')
    if dept_id:
        dept = Department.objects.filter(id=dept_id).first()
        if not dept:
            dept = Department.objects.filter(code__iexact=dept_id).first()
        if dept:
            return dept

    if profile and profile.department:
        return profile.department

    return Department.objects.first()


@dept_admin_required
def dept_admin_dashboard(request):
    """Department Administration Dashboard: Overview of Department Staff, Alerts, Welfare Schemes & Grievance KPIs."""
    dept = get_active_dept_for_request(request)
    if not dept:
        messages.error(request, "No municipal department is assigned to your account. Please contact the SuperAdmin.")
        return redirect('home')

    cluster = dept.cluster or Cluster.objects.filter(is_active=True).first()
    all_departments = Department.objects.filter(cluster=cluster) if cluster else Department.objects.all()

    # Staff Metrics for this Department
    staff_count = UserProfile.objects.filter(department=dept).count()
    dl1_count = UserProfile.objects.filter(department=dept, hierarchy_level=1).count()
    dl2_count = UserProfile.objects.filter(department=dept, hierarchy_level=2).count()
    dl3_count = UserProfile.objects.filter(department=dept, hierarchy_level=3).count()
    cl1_count = UserProfile.objects.filter(department=dept, hierarchy_level=4).count()

    # Grievance Metrics for this Department
    dept_complaints = Complaint.objects.filter(department=dept)
    total_complaints = dept_complaints.count()
    open_complaints = dept_complaints.exclude(status__in=['RESOLVED', 'CITIZEN_CONFIRMED']).count()
    resolved_complaints = dept_complaints.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED']).count()
    sla_breached = dept_complaints.filter(is_sla_breached=True).count()

    # Department Time-based Alerts & Welfare Schemes
    alerts = GovernmentBroadcast.objects.filter(department=dept, broadcast_type='ALERT').order_by('-created_at')
    schemes = GovernmentBroadcast.objects.filter(department=dept, broadcast_type='WELFARE_SCHEME').order_by('-created_at')

    active_alerts_count = sum(1 for a in alerts if a.is_currently_active)
    active_schemes_count = sum(1 for s in schemes if s.is_currently_active)

    recent_complaints = dept_complaints.order_by('-created_at')[:6]

    context = {
        'dept': dept,
        'cluster': cluster,
        'all_departments': all_departments,
        'is_superadmin': request.user.is_superuser or (get_user_role(request.user) == 'SUPERADMIN'),
        'staff_count': staff_count,
        'dl1_count': dl1_count,
        'dl2_count': dl2_count,
        'dl3_count': dl3_count,
        'cl1_count': cl1_count,
        'total_complaints': total_complaints,
        'open_complaints': open_complaints,
        'resolved_complaints': resolved_complaints,
        'sla_breached': sla_breached,
        'alerts': alerts[:4],
        'schemes': schemes[:4],
        'active_alerts_count': active_alerts_count,
        'active_schemes_count': active_schemes_count,
        'recent_complaints': recent_complaints,
    }
    return render(request, 'dept_admin/dashboard.html', context)


@dept_admin_required
def dept_admin_staff(request):
    """Department Staff Management: Add, edit, and bulk-provision officers strictly for this department."""
    dept = get_active_dept_for_request(request)
    if not dept:
        messages.error(request, "No municipal department is assigned to your account.")
        return redirect('home')

    cluster = dept.cluster or Cluster.objects.filter(is_active=True).first()
    is_superadmin = request.user.is_superuser or (get_user_role(request.user) == 'SUPERADMIN')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_staff':
            full_name = request.POST.get('full_name', '').strip()
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            phone = request.POST.get('phone', '').strip()
            role = request.POST.get('role', 'WARD_OFFICER')
            hierarchy_level = int(request.POST.get('hierarchy_level', 1))
            zone_id = request.POST.get('zone_id')
            ward_id = request.POST.get('ward_id')
            designation = request.POST.get('designation', '').strip()
            password = request.POST.get('password', 'Admin@Dpig2026')

            if not username:
                messages.error(request, "Username is required to add department staff.")
                return redirect('dept_admin_staff')

            if User.objects.filter(username=username).exists():
                messages.error(request, f"Username '{username}' is already in use. Please select a unique username.")
                return redirect('dept_admin_staff')

            user = User.objects.create_user(
                username=username,
                email=email or f"{username}@chennaicorporation.gov.in",
                password=password,
                first_name=full_name
            )
            user.is_staff = True
            user.save()

            zone = Zone.objects.filter(id=zone_id).first() if zone_id else None
            ward = Ward.objects.filter(id=ward_id).first() if ward_id else None

            UserProfile.objects.create(
                user=user,
                cluster=cluster,
                role=role,
                hierarchy_level=hierarchy_level,
                department=dept,  # Strictly locked to this department!
                zone=zone,
                ward=ward,
                designation=designation or f"{dept.name} Officer - L{hierarchy_level}",
                phone=phone
            )
            messages.success(request, f"Officer '{full_name or username}' successfully added to {dept.name} at Level {hierarchy_level}!")
            return redirect('dept_admin_staff')

        elif action == 'edit_staff':
            staff_id = request.POST.get('staff_id')
            profile = get_object_or_404(UserProfile, id=staff_id)
            if not is_superadmin and profile.department != dept:
                messages.error(request, "Permission denied: Cannot modify staff outside your department.")
                return redirect('dept_admin_staff')

            profile.designation = request.POST.get('designation', profile.designation)
            profile.role = request.POST.get('role', profile.role)
            profile.hierarchy_level = int(request.POST.get('hierarchy_level', profile.hierarchy_level))
            zone_id = request.POST.get('zone_id')
            ward_id = request.POST.get('ward_id')
            profile.zone = Zone.objects.filter(id=zone_id).first() if zone_id else None
            profile.ward = Ward.objects.filter(id=ward_id).first() if ward_id else None
            profile.phone = request.POST.get('phone', profile.phone)
            # Department remains locked to this department
            profile.department = dept
            profile.save()

            u = profile.user
            u.first_name = request.POST.get('full_name', u.first_name)
            u.email = request.POST.get('email', u.email)
            u.save()

            messages.success(request, f"Updated profile for officer {u.username} ({dept.name}).")
            return redirect('dept_admin_staff')

        elif action == 'reset_password':
            staff_id = request.POST.get('staff_id')
            profile = get_object_or_404(UserProfile, id=staff_id)
            if not is_superadmin and profile.department != dept:
                messages.error(request, "Permission denied: Cannot modify staff outside your department.")
                return redirect('dept_admin_staff')

            new_pwd = request.POST.get('new_password', 'Admin@Dpig2026')
            profile.user.set_password(new_pwd)
            profile.user.save()
            messages.success(request, f"Password successfully reset for {profile.user.username}.")
            return redirect('dept_admin_staff')

        elif action == 'bulk_upload':
            file_obj = request.FILES.get('officers_file')
            if not file_obj:
                messages.error(request, "Please select a Google Sheet / Excel file to upload.")
                return redirect('dept_admin_staff')

            if not file_obj.name.lower().endswith(('.xlsx', '.xls', '.csv')):
                messages.error(request, "Invalid file format. Supported formats: .xlsx, .xls, .csv.")
                return redirect('dept_admin_staff')
            if file_obj.size > 25 * 1024 * 1024:
                messages.error(request, "Uploaded spreadsheet exceeds 25MB limit.")
                return redirect('dept_admin_staff')

            from core.officer_bulk_service import parse_and_provision_officers
            res = parse_and_provision_officers(file_obj, cluster=cluster, update_existing=True, enforce_department=dept)
            request.session['bulk_officer_import_report'] = res

            if res['status'] == 'SUCCESS':
                messages.success(
                    request,
                    f"Successfully provisioned {res['total_rows']} officers for {dept.name} ({res['created_count']} created, {res['updated_count']} updated)!"
                )
            elif res['status'] == 'PARTIAL':
                messages.warning(
                    request,
                    f"Bulk import for {dept.name} completed with notices: {res['created_count']} created, {res['updated_count']} updated. Notices: {'; '.join(res['errors'][:5])}"
                )
            else:
                messages.error(
                    request,
                    f"Failed to process Google Sheet for {dept.name}: {'; '.join(res['errors'][:5])}"
                )
            return redirect('dept_admin_staff')

    # GET
    level_filter = request.GET.get('level')
    role_filter = request.GET.get('role')
    zone_filter = request.GET.get('zone')
    search_q = request.GET.get('q', '').strip()

    staff_qs = UserProfile.objects.filter(department=dept).select_related('user', 'zone', 'ward')
    if level_filter:
        try:
            if level_filter.isdigit():
                staff_qs = staff_qs.filter(hierarchy_level=int(level_filter))
            else:
                from core.models import LEVEL_CODE_TO_INT
                staff_qs = staff_qs.filter(hierarchy_level=LEVEL_CODE_TO_INT.get(level_filter.upper(), 1))
        except Exception:
            pass

    if role_filter:
        staff_qs = staff_qs.filter(role=role_filter)
    if zone_filter:
        staff_qs = staff_qs.filter(zone__number=zone_filter)
    if search_q:
        staff_qs = staff_qs.filter(
            Q(user__username__icontains=search_q) |
            Q(user__first_name__icontains=search_q) |
            Q(designation__icontains=search_q) |
            Q(user__email__icontains=search_q)
        )

    zones = Zone.objects.filter(cluster=cluster).order_by('number') if cluster else Zone.objects.all().order_by('number')
    wards = Ward.objects.filter(zone__cluster=cluster).order_by('number') if cluster else Ward.objects.all().order_by('number')
    all_departments = Department.objects.filter(cluster=cluster) if cluster else Department.objects.all()

    counts = {
        'total': UserProfile.objects.filter(department=dept).count(),
        'dl1': UserProfile.objects.filter(department=dept, hierarchy_level=1).count(),
        'dl2': UserProfile.objects.filter(department=dept, hierarchy_level=2).count(),
        'dl3': UserProfile.objects.filter(department=dept, hierarchy_level=3).count(),
        'cl1': UserProfile.objects.filter(department=dept, hierarchy_level=4).count(),
    }

    context = {
        'dept': dept,
        'cluster': cluster,
        'is_superadmin': is_superadmin,
        'all_departments': all_departments,
        'staff_members': staff_qs.order_by('hierarchy_level', 'user__username'),
        'zones': zones,
        'wards': wards,
        'counts': counts,
        'level_filter': level_filter,
        'role_filter': role_filter,
        'zone_filter': zone_filter,
        'search_q': search_q,
        'bulk_report': request.session.pop('bulk_officer_import_report', None),
    }
    return render(request, 'dept_admin/staff.html', context)


@dept_admin_required
def dept_admin_alerts(request):
    """Department Alerts Management: Create, update, and manage time-based public notices and emergency alerts."""
    dept = get_active_dept_for_request(request)
    if not dept:
        messages.error(request, "No municipal department is assigned to your account.")
        return redirect('home')

    cluster = dept.cluster or Cluster.objects.filter(is_active=True).first()
    is_superadmin = request.user.is_superuser or (get_user_role(request.user) == 'SUPERADMIN')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_alert':
            title = request.POST.get('title', '').strip()
            content = request.POST.get('content', '').strip()
            priority = request.POST.get('priority', 'NORMAL')
            target_audience = request.POST.get('target_audience', 'All Citizens').strip()
            valid_from = parse_form_datetime(request.POST.get('valid_from'), default=timezone.now())
            valid_until = parse_form_datetime(request.POST.get('valid_until'), default=None)
            is_active = request.POST.get('is_active') == 'on'

            if not title or not content:
                messages.error(request, "Alert Title and Description are required.")
                return redirect('dept_admin_alerts')

            alert = GovernmentBroadcast.objects.create(
                cluster=cluster,
                department=dept,
                broadcast_type='ALERT',
                title=title,
                content=content,
                priority=priority,
                target_audience=target_audience or 'All Citizens',
                valid_from=valid_from,
                valid_until=valid_until,
                is_active=is_active,
                created_by=request.user
            )
            messages.success(request, f"Time-based Alert '{alert.title}' successfully published for {dept.name}!")
            return redirect('dept_admin_alerts')

        elif action == 'edit_alert':
            alert_id = request.POST.get('alert_id')
            alert = get_object_or_404(GovernmentBroadcast, id=alert_id, broadcast_type='ALERT')
            if not is_superadmin and alert.department != dept:
                messages.error(request, "Permission denied: Cannot edit alerts belonging to another department.")
                return redirect('dept_admin_alerts')

            alert.title = request.POST.get('title', alert.title).strip()
            alert.content = request.POST.get('content', alert.content).strip()
            alert.priority = request.POST.get('priority', alert.priority)
            alert.target_audience = request.POST.get('target_audience', alert.target_audience).strip()
            if request.POST.get('valid_from'):
                alert.valid_from = parse_form_datetime(request.POST.get('valid_from'), default=alert.valid_from)
            alert.valid_until = parse_form_datetime(request.POST.get('valid_until'), default=None)
            alert.is_active = request.POST.get('is_active') == 'on'
            alert.save()

            messages.success(request, f"Alert '{alert.title}' updated successfully.")
            return redirect('dept_admin_alerts')

        elif action == 'toggle_status':
            alert_id = request.POST.get('alert_id')
            alert = get_object_or_404(GovernmentBroadcast, id=alert_id, broadcast_type='ALERT')
            if not is_superadmin and alert.department != dept:
                messages.error(request, "Permission denied.")
                return redirect('dept_admin_alerts')

            alert.is_active = not alert.is_active
            alert.save()
            state_str = "Activated" if alert.is_active else "Deactivated"
            messages.success(request, f"Alert '{alert.title}' is now {state_str}.")
            return redirect('dept_admin_alerts')

        elif action == 'delete_alert':
            alert_id = request.POST.get('alert_id')
            alert = get_object_or_404(GovernmentBroadcast, id=alert_id, broadcast_type='ALERT')
            if not is_superadmin and alert.department != dept:
                messages.error(request, "Permission denied.")
                return redirect('dept_admin_alerts')

            title_saved = alert.title
            alert.delete()
            messages.success(request, f"Alert '{title_saved}' deleted.")
            return redirect('dept_admin_alerts')

    # GET
    status_filter = request.GET.get('status')
    alerts_qs = GovernmentBroadcast.objects.filter(department=dept, broadcast_type='ALERT').order_by('-created_at')

    alerts_list = list(alerts_qs)
    if status_filter:
        status_filter_upper = status_filter.upper()
        if status_filter_upper in ['ACTIVE', 'SCHEDULED', 'EXPIRED', 'INACTIVE']:
            alerts_list = [a for a in alerts_list if a.time_status == status_filter_upper]

    now_iso = timezone.now().strftime('%Y-%m-%dT%H:%M')

    context = {
        'dept': dept,
        'cluster': cluster,
        'is_superadmin': is_superadmin,
        'all_departments': Department.objects.filter(cluster=cluster) if cluster else Department.objects.all(),
        'alerts': alerts_list,
        'status_filter': status_filter,
        'total_alerts': alerts_qs.count(),
        'active_count': sum(1 for a in alerts_qs if a.is_currently_active),
        'now_iso': now_iso,
    }
    return render(request, 'dept_admin/alerts.html', context)


@dept_admin_required
def dept_admin_schemes(request):
    """Department Welfare Schemes Management: Create, update, and manage time-based welfare schemes and citizen benefits."""
    dept = get_active_dept_for_request(request)
    if not dept:
        messages.error(request, "No municipal department is assigned to your account.")
        return redirect('home')

    cluster = dept.cluster or Cluster.objects.filter(is_active=True).first()
    is_superadmin = request.user.is_superuser or (get_user_role(request.user) == 'SUPERADMIN')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_scheme':
            title = request.POST.get('title', '').strip()
            content = request.POST.get('content', '').strip()
            eligibility_criteria = request.POST.get('eligibility_criteria', '').strip()
            benefits = request.POST.get('benefits', '').strip()
            target_audience = request.POST.get('target_audience', 'All Eligible Citizens').strip()
            scheme_url = request.POST.get('scheme_url', '').strip()
            valid_from = parse_form_datetime(request.POST.get('valid_from'), default=timezone.now())
            valid_until = parse_form_datetime(request.POST.get('valid_until'), default=None)
            is_active = request.POST.get('is_active') == 'on'

            if not title or not content:
                messages.error(request, "Scheme Title and Description are required.")
                return redirect('dept_admin_schemes')

            scheme = GovernmentBroadcast.objects.create(
                cluster=cluster,
                department=dept,
                broadcast_type='WELFARE_SCHEME',
                title=title,
                content=content,
                eligibility_criteria=eligibility_criteria,
                benefits=benefits,
                target_audience=target_audience or 'All Eligible Citizens',
                scheme_url=scheme_url,
                valid_from=valid_from,
                valid_until=valid_until,
                is_active=is_active,
                created_by=request.user
            )
            messages.success(request, f"Welfare Scheme '{scheme.title}' successfully published for {dept.name}!")
            return redirect('dept_admin_schemes')

        elif action == 'edit_scheme':
            scheme_id = request.POST.get('scheme_id')
            scheme = get_object_or_404(GovernmentBroadcast, id=scheme_id, broadcast_type='WELFARE_SCHEME')
            if not is_superadmin and scheme.department != dept:
                messages.error(request, "Permission denied: Cannot edit schemes belonging to another department.")
                return redirect('dept_admin_schemes')

            scheme.title = request.POST.get('title', scheme.title).strip()
            scheme.content = request.POST.get('content', scheme.content).strip()
            scheme.eligibility_criteria = request.POST.get('eligibility_criteria', scheme.eligibility_criteria).strip()
            scheme.benefits = request.POST.get('benefits', scheme.benefits).strip()
            scheme.target_audience = request.POST.get('target_audience', scheme.target_audience).strip()
            scheme.scheme_url = request.POST.get('scheme_url', scheme.scheme_url).strip()
            if request.POST.get('valid_from'):
                scheme.valid_from = parse_form_datetime(request.POST.get('valid_from'), default=scheme.valid_from)
            scheme.valid_until = parse_form_datetime(request.POST.get('valid_until'), default=None)
            scheme.is_active = request.POST.get('is_active') == 'on'
            scheme.save()

            messages.success(request, f"Welfare Scheme '{scheme.title}' updated successfully.")
            return redirect('dept_admin_schemes')

        elif action == 'toggle_status':
            scheme_id = request.POST.get('scheme_id')
            scheme = get_object_or_404(GovernmentBroadcast, id=scheme_id, broadcast_type='WELFARE_SCHEME')
            if not is_superadmin and scheme.department != dept:
                messages.error(request, "Permission denied.")
                return redirect('dept_admin_schemes')

            scheme.is_active = not scheme.is_active
            scheme.save()
            state_str = "Activated" if scheme.is_active else "Deactivated"
            messages.success(request, f"Welfare Scheme '{scheme.title}' is now {state_str}.")
            return redirect('dept_admin_schemes')

        elif action == 'delete_scheme':
            scheme_id = request.POST.get('scheme_id')
            scheme = get_object_or_404(GovernmentBroadcast, id=scheme_id, broadcast_type='WELFARE_SCHEME')
            if not is_superadmin and scheme.department != dept:
                messages.error(request, "Permission denied.")
                return redirect('dept_admin_schemes')

            title_saved = scheme.title
            scheme.delete()
            messages.success(request, f"Welfare Scheme '{title_saved}' deleted.")
            return redirect('dept_admin_schemes')

    # GET
    status_filter = request.GET.get('status')
    schemes_qs = GovernmentBroadcast.objects.filter(department=dept, broadcast_type='WELFARE_SCHEME').order_by('-created_at')

    schemes_list = list(schemes_qs)
    if status_filter:
        status_filter_upper = status_filter.upper()
        if status_filter_upper in ['ACTIVE', 'SCHEDULED', 'EXPIRED', 'INACTIVE']:
            schemes_list = [s for s in schemes_list if s.time_status == status_filter_upper]

    now_iso = timezone.now().strftime('%Y-%m-%dT%H:%M')

    context = {
        'dept': dept,
        'cluster': cluster,
        'is_superadmin': is_superadmin,
        'all_departments': Department.objects.filter(cluster=cluster) if cluster else Department.objects.all(),
        'schemes': schemes_list,
        'status_filter': status_filter,
        'total_schemes': schemes_qs.count(),
        'active_count': sum(1 for s in schemes_qs if s.is_currently_active),
        'now_iso': now_iso,
    }
    return render(request, 'dept_admin/schemes.html', context)


def login_view(request):
    """Platform Login: Standard credential authentication for authorized municipal staff."""
    raw_next = request.GET.get('next') or request.POST.get('next')
    if raw_next and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}):
        next_url = raw_next
    else:
        next_url = None

    if request.user.is_authenticated:
        return redirect(next_url or '/')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is None and '@' in username:
            matched_user = User.objects.filter(email__iexact=username).first()
            if matched_user:
                user = authenticate(request, username=matched_user.username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            if not next_url or next_url == '/':
                role = get_user_role(user)
                if role == 'DEPT_ADMIN':
                    return redirect('dept_admin_dashboard')
                elif role == 'SUPERADMIN':
                    return redirect('feature_permission_matrix')
                elif role == 'POLICYMAKER':
                    return redirect('policymaker_dashboard')
                elif role == 'AUDITOR':
                    return redirect('auditor_dashboard')
                elif role in ['WARD_OFFICER', 'FIELD_STAFF', 'ZONAL_OFFICER', 'COMMISSIONER']:
                    return redirect('officer_dashboard')
                return redirect('/')
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password. Please verify your credentials.")

    context = {
        'next': next_url,
    }
    return render(request, 'auth/login.html', context)


def logout_view(request):
    """Log out current user and redirect home."""
    logout(request)
    messages.info(request, "You have been securely logged out.")
    return redirect('home')


def csrf_failure(request, reason=""):
    """Custom CSRF failure handler providing clear diagnostic and recovery actions."""
    context = {
        'reason': reason,
        'next': request.GET.get('next') or request.POST.get('next') or '/admin/',
    }
    return render(request, 'errors/403_csrf.html', context, status=403)


# ==============================================================================
# STATUTORY AUDITOR & COMPLIANCE HUB (Independent Verification & Policy Oversight)
# ==============================================================================

@auditor_required
def auditor_dashboard(request):
    """
    Statutory Auditor & Compliance Intelligence Hub:
    Enables independent oversight to verify:
    1. Cryptographic SHA-256 Merkle chain integrity across grievances.
    2. SLA compliance and statutory escalation turnaround times.
    3. Resolution proof compliance (mandatory photo evidence and inspection notes).
    4. Spatial India Post DIGIPIN & boundary validity.
    5. Audit finding creation, remediation tracking, and statutory reporting.
    """
    cluster = Cluster.objects.filter(is_active=True).first()
    complaints_qs = Complaint.objects.filter(cluster=cluster) if cluster else Complaint.objects.all()

    # Metric computations
    total_complaints = complaints_qs.count()
    resolved_qs = complaints_qs.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED'])
    resolved_count = resolved_qs.count()

    now = timezone.now()
    sla_breached_total = complaints_qs.filter(
        Q(is_sla_breached=True) |
        Q(sla_deadline__lt=now, status__in=['SUBMITTED', 'AI_CLASSIFIED', 'ASSIGNED', 'FIELD_VERIFICATION', 'ESCALATED'])
    ).count()

    sla_compliance_rate = 100.0
    if total_complaints > 0:
        sla_compliant_count = total_complaints - sla_breached_total
        sla_compliance_rate = round(max(0, (sla_compliant_count / total_complaints) * 100), 1)

    with_photo = resolved_qs.exclude(resolution_image='').count()
    proof_compliance_rate = 100.0
    if resolved_count > 0:
        proof_compliance_rate = round((with_photo / resolved_count) * 100, 1)

    audited_count = complaints_qs.exclude(audit_status='NOT_AUDITED').count()
    compliant_count = complaints_qs.filter(audit_status='COMPLIANT').count()
    flagged_count = complaints_qs.filter(audit_status='FLAGGED_NON_COMPLIANT').count()
    under_review_count = complaints_qs.filter(audit_status='UNDER_REVIEW').count()
    findings_count = AuditFinding.objects.filter(complaint__in=complaints_qs, is_resolved=False).count()

    # Filters
    search_q = request.GET.get('q', '').strip()
    dept_code = request.GET.get('dept', 'ALL')
    zone_num = request.GET.get('zone', 'ALL')
    status_filter = request.GET.get('status', 'ALL')
    audit_filter = request.GET.get('audit_status', 'ALL')
    sla_filter = request.GET.get('sla', 'ALL')
    proof_filter = request.GET.get('proof', 'ALL')

    filtered = complaints_qs.select_related('zone', 'ward', 'department', 'current_assignee')

    if search_q:
        filtered = filtered.filter(
            Q(ticket_number__icontains=search_q) |
            Q(title__icontains=search_q) |
            Q(citizen_name__icontains=search_q) |
            Q(digipin__icontains=search_q)
        )
    if dept_code != 'ALL':
        filtered = filtered.filter(department__code=dept_code)
    if zone_num != 'ALL' and zone_num.isdigit():
        filtered = filtered.filter(zone__number=int(zone_num))
    if status_filter != 'ALL':
        filtered = filtered.filter(status=status_filter)
    if audit_filter != 'ALL':
        filtered = filtered.filter(audit_status=audit_filter)
    if sla_filter == 'BREACHED':
        filtered = filtered.filter(
            Q(is_sla_breached=True) |
            Q(sla_deadline__lt=now, status__in=['SUBMITTED', 'AI_CLASSIFIED', 'ASSIGNED', 'FIELD_VERIFICATION', 'ESCALATED'])
        )
    elif sla_filter == 'COMPLIANT':
        filtered = filtered.filter(is_sla_breached=False).exclude(
            sla_deadline__lt=now, status__in=['SUBMITTED', 'AI_CLASSIFIED', 'ASSIGNED', 'FIELD_VERIFICATION', 'ESCALATED']
        )
    if proof_filter == 'MISSING_PHOTO':
        filtered = filtered.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED'], resolution_image='')
    elif proof_filter == 'HAS_PHOTO':
        filtered = filtered.filter(status__in=['RESOLVED', 'CITIZEN_CONFIRMED']).exclude(resolution_image='')

    complaint_list = list(filtered.order_by('-created_at')[:100])
    for c in complaint_list:
        c.crypto_intact = c.is_cryptographically_valid

    context = {
        'complaints': complaint_list,
        'total_complaints': total_complaints,
        'resolved_count': resolved_count,
        'sla_breached_total': sla_breached_total,
        'sla_compliance_rate': sla_compliance_rate,
        'proof_compliance_rate': proof_compliance_rate,
        'with_photo_count': with_photo,
        'audited_count': audited_count,
        'compliant_count': compliant_count,
        'flagged_count': flagged_count,
        'under_review_count': under_review_count,
        'findings_count': findings_count,
        'departments': Department.objects.filter(cluster=cluster) if cluster else Department.objects.all(),
        'zones': Zone.objects.filter(cluster=cluster) if cluster else Zone.objects.all(),
        'search_q': search_q,
        'dept_filter': dept_code,
        'zone_filter': zone_num,
        'status_filter': status_filter,
        'audit_filter': audit_filter,
        'sla_filter': sla_filter,
        'proof_filter': proof_filter,
        'active_cluster': cluster,
    }
    return render(request, 'auditor/dashboard.html', context)


@auditor_required
def auditor_complaint_detail(request, complaint_id):
    """
    Auditor Deep Grievance Inspection View:
    1. Verifies every cryptographic block in the SHA-256 chain.
    2. Runs automated compliance rule checks (SLA, Proofs, Geocoding, Roles).
    3. Renders existing audit findings and allows logging statutory observations.
    """
    complaint = get_object_or_404(
        Complaint.objects.select_related('cluster', 'zone', 'ward', 'department', 'category', 'current_assignee', 'audited_by'),
        id=complaint_id
    )

    # Cryptographic block verification
    blocks = []
    all_blocks_valid = True
    raw_logs = list(complaint.audit_logs.all().order_by('id'))
    for idx, block in enumerate(raw_logs):
        is_valid = block.verify_integrity()
        if not is_valid:
            all_blocks_valid = False
        blocks.append({
            'index': idx + 1,
            'block': block,
            'is_valid': is_valid,
            'details_json': json.dumps(block.details, indent=2) if block.details else "{}"
        })

    # Rule compliance evaluation
    now = timezone.now()
    is_sla_violated = complaint.is_sla_breached or bool(
        complaint.sla_deadline and now > complaint.sla_deadline and
        complaint.status not in ['RESOLVED', 'CITIZEN_CONFIRMED', 'REJECTED', 'DUPLICATE']
    )
    has_photo_proof = bool(complaint.resolution_image)
    has_resolution_notes = bool(complaint.resolution_notes and len(complaint.resolution_notes.strip()) >= 10)
    has_valid_digipin = bool(complaint.digipin and len(complaint.digipin.strip()) >= 10)

    escalations = list(complaint.escalations.all().order_by('created_at'))
    findings = list(complaint.audit_findings.all().order_by('-created_at'))

    context = {
        'complaint': complaint,
        'blocks': blocks,
        'all_blocks_valid': all_blocks_valid,
        'total_blocks': len(blocks),
        'is_sla_violated': is_sla_violated,
        'has_photo_proof': has_photo_proof,
        'has_resolution_notes': has_resolution_notes,
        'has_valid_digipin': has_valid_digipin,
        'escalations': escalations,
        'findings': findings,
        'finding_categories': AuditFinding.FINDING_CATEGORIES,
        'severity_levels': AuditFinding.SEVERITY_LEVELS,
        'audit_status_choices': Complaint.AUDIT_STATUS_CHOICES,
    }
    return render(request, 'auditor/complaint_detail.html', context)


@auditor_required
def auditor_record_action(request, complaint_id):
    """
    Records statutory auditor determination, notes, and compliance findings.
    Appends an immutable block to the complaint's SHA-256 audit log.
    """
    if request.method != 'POST':
        return redirect('auditor_complaint_detail', complaint_id=complaint_id)

    complaint = get_object_or_404(Complaint, id=complaint_id)
    audit_status = request.POST.get('audit_status', 'COMPLIANT').strip()
    audit_notes = request.POST.get('audit_notes', '').strip()
    create_finding = request.POST.get('create_finding') == '1' or audit_status == 'FLAGGED_NON_COMPLIANT'

    finding_category = request.POST.get('finding_category', 'OTHER')
    finding_severity = request.POST.get('finding_severity', 'MEDIUM')
    action_required = request.POST.get('action_required', '').strip()

    if create_finding and audit_notes:
        AuditFinding.objects.create(
            complaint=complaint,
            auditor=request.user,
            category=finding_category,
            severity=finding_severity,
            observation=audit_notes,
            action_required=action_required,
        )

    complaint.audit_status = audit_status
    complaint.audit_notes = audit_notes
    complaint.audited_by = request.user
    complaint.audited_at = timezone.now()
    complaint.save(update_fields=['audit_status', 'audit_notes', 'audited_by', 'audited_at'])

    # Append immutable cryptographic audit block
    complaint.create_audit_block(
        action="AUDIT_INSPECTION_RECORDED",
        performed_by=request.user,
        actor_role="AUDITOR",
        details={
            "audit_status": audit_status,
            "auditor_notes": audit_notes,
            "has_finding": create_finding,
            "finding_category": finding_category if create_finding else None,
            "finding_severity": finding_severity if create_finding else None,
            "action_required": action_required if create_finding else None
        }
    )

    messages.success(request, f"Statutory audit determination [{complaint.get_audit_status_display()}] cryptographically recorded for {complaint.ticket_number}.")
    return redirect('auditor_complaint_detail', complaint_id=complaint_id)


@auditor_required
def auditor_system_integrity_scan(request):
    """
    API/Action: Scans all SHA-256 cryptographic audit chain blocks in the database
    to detect any tampering, broken hashes, or database-level unauthorized edits.
    """
    all_logs = ComplaintAuditLog.objects.select_related('complaint', 'performed_by').all().order_by('id')
    total_blocks = all_logs.count()
    valid_blocks = 0
    tampered_blocks = 0
    tampered_tickets = set()

    for block in all_logs:
        if block.verify_integrity():
            valid_blocks += 1
        else:
            tampered_blocks += 1
            tampered_tickets.add(block.complaint.ticket_number)

    data = {
        "status": "SUCCESS",
        "total_blocks_scanned": total_blocks,
        "valid_blocks": valid_blocks,
        "tampered_blocks": tampered_blocks,
        "is_system_clean": tampered_blocks == 0,
        "tampered_tickets": list(tampered_tickets),
        "timestamp": timezone.now().isoformat()
    }
    return JsonResponse(data)


@auditor_required
def auditor_export_report(request):
    """
    Exports comprehensive statutory compliance audit report as CSV or Excel (.xlsx).
    """
    fmt = request.GET.get('format', 'csv').lower()
    complaints = Complaint.objects.select_related('cluster', 'zone', 'ward', 'department', 'current_assignee', 'audited_by').order_by('-created_at')

    rows = []
    now = timezone.now()
    for c in complaints:
        is_sla_ok = not (c.is_sla_breached or (c.sla_deadline and now > c.sla_deadline and c.status not in ['RESOLVED', 'CITIZEN_CONFIRMED', 'REJECTED', 'DUPLICATE']))
        rows.append({
            'Ticket_ID': c.ticket_number,
            'Title': c.title,
            'Cluster': c.cluster.name if c.cluster else 'Statewide',
            'Zone': f"Zone {c.zone.number} ({c.zone.name})" if c.zone else 'Statewide',
            'Ward': f"Ward {c.ward.number}" if c.ward else 'N/A',
            'Department': c.department.name if c.department else 'N/A',
            'Status': c.status,
            'Current_Level': c.current_level,
            'SLA_Compliance': 'COMPLIANT' if is_sla_ok else 'BREACHED',
            'Resolution_Proof': 'PHOTO_ATTACHED' if c.resolution_image else ('NOTE_ONLY' if c.resolution_notes else 'NO_PROOF'),
            'Crypto_Integrity': 'INTACT' if c.is_cryptographically_valid else 'TAMPERED',
            'Audit_Status': c.get_audit_status_display(),
            'Auditor_Notes': c.audit_notes,
            'Audited_By': c.audited_by.username if c.audited_by else 'UNAUDITED',
            'Audited_At': c.audited_at.strftime('%Y-%m-%d %H:%M:%S') if c.audited_at else '',
            'Registered_At': c.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'Resolved_At': c.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if c.resolved_at else '',
        })

    import pandas as pd
    import io
    df = pd.DataFrame(rows)

    if fmt == 'xlsx':
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Statutory_Audit_Report', index=False)
        response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="DPIG_Statutory_Audit_Report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        return response
    else:
        output = io.StringIO()
        df.to_csv(output, index=False)
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="DPIG_Statutory_Audit_Report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        return response


@csrf_exempt
def api_complaint_ingest(request):
    """
    Automated Machine-to-Machine Grievance Ingestion Endpoint.
    Used by n8n workflows, WhatsApp/Telegram civic bots, and external government aggregators.
    Accepts JSON:
      - message_text / text / description (required)
      - phone / sender_phone (optional)
      - channel (WhatsApp / Telegram / Webhook)
      - latitude / longitude (floats, optional)
      - digipin (optional)
      - title (optional)
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'ERROR', 'message': 'POST method required.'}, status=405)

    # Optional token verification if passed
    internal_token = request.headers.get('X-Internal-Token') or request.GET.get('token')
    expected_token = getattr(settings, 'INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')
    if internal_token and internal_token != expected_token:
        return JsonResponse({'status': 'ERROR', 'message': 'Invalid internal API authentication token.'}, status=401)

    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        data = request.POST.dict()

    message_text = (data.get('message_text') or data.get('text') or data.get('description') or '').strip()
    if not message_text:
        return JsonResponse({'status': 'ERROR', 'message': 'Field message_text or description is required.'}, status=400)

    sender_phone = (data.get('sender_phone') or data.get('phone') or '').strip()
    channel = (data.get('channel') or 'WHATSAPP').upper()
    title = (data.get('title') or (message_text[:80] + ('...' if len(message_text) > 80 else ''))).strip()

    try:
        lat = float(data.get('latitude', 13.0827))
        lon = float(data.get('longitude', 80.2707))
    except (ValueError, TypeError):
        lat, lon = 13.0827, 80.2707

    digipin_input = (data.get('digipin') or '').strip()
    if digipin_input and validate_digipin(digipin_input):
        digipin = format_digipin(digipin_input)
    else:
        digipin = format_digipin(encode_digipin(lat, lon, precision=10))

    cluster = Cluster.objects.filter(is_active=True).first()
    ward, _ = resolve_ward_from_location(lat, lon, cluster=cluster)
    zone = ward.zone if ward else None

    category = GrievanceCategory.objects.filter(cluster=cluster).first()
    department = category.department if category else Department.objects.filter(cluster=cluster).first()

    citizen_user = None
    if sender_phone:
        profile = UserProfile.objects.filter(phone=sender_phone).first()
        if profile:
            citizen_user = profile.user

    complaint = Complaint.objects.create(
        cluster=cluster,
        zone=zone,
        ward=ward,
        department=department,
        category=category,
        title=title,
        description=message_text,
        original_description=message_text,
        script_detected="Latin",
        citizen=citizen_user,
        citizen_name=f"{channel} Citizen" if not citizen_user else (citizen_user.get_full_name() or citizen_user.username),
        citizen_email=(citizen_user.email if citizen_user and citizen_user.email else f"{sender_phone or 'citizen'}@dpig.gov.in"),
        citizen_phone=sender_phone,
        latitude=lat,
        longitude=lon,
        digipin=digipin,
        address_landmark=f"Ingested via {channel} Bot",
        current_level='DL1',
        escalated_to_level=1,
        status='SUBMITTED'
    )

    # Assign to designated Ward Officer (DL1)
    dl1_officer = find_officer_for_workflow_level(cluster, zone, department, 'DL1')
    if dl1_officer and dl1_officer.user:
        complaint.current_assignee = dl1_officer.user
        complaint.status = 'ASSIGNED'
        complaint.save(update_fields=['current_assignee', 'status'])

    # Asynchronously trigger AI triage (with synchronous fallback if Celery/Redis is unavailable)
    try:
        process_complaint_ai_triage_task.delay(complaint.id)
    except Exception:
        process_complaint_ai_triage_task(complaint.id)

    tracking_url = f"/track/{complaint.ticket_number}/"
    base_url = request.build_absolute_uri('/')[:-1]

    return JsonResponse({
        'status': 'REGISTERED',
        'ticket_number': complaint.ticket_number,
        'digipin': complaint.digipin,
        'tracking_url': f"{base_url}{tracking_url}",
        'ward': f"Ward {ward.number}" if ward else "Unmapped",
        'zone': f"Zone {zone.number} ({zone.name})" if zone else "Unmapped",
        'message': f"Thank you! Your grievance #{complaint.ticket_number} has been registered in the DPIG Registry at DIGIPIN: {complaint.digipin}. Tracking link: {base_url}{tracking_url}"
    }, status=201)


@csrf_exempt
def cron_monitor_sla(request):
    """
    Cloud Scheduler / Cron endpoint to trigger periodic SLA breach monitoring.
    Protected by X-DPIG-CRON-KEY header, token query parameter, or Google App Engine cron header.
    """
    cron_key = request.headers.get('X-DPIG-CRON-KEY') or request.GET.get('token')
    gae_cron = request.headers.get('X-Appengine-Cron') == 'true'
    expected_key = getattr(settings, 'INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')

    if not gae_cron and (not cron_key or cron_key != expected_key):
        return JsonResponse({'status': 'UNAUTHORIZED', 'message': 'Invalid cron authorization token.'}, status=401)

    from core.tasks import monitor_sla_deadlines_task
    try:
        monitor_sla_deadlines_task()
        return JsonResponse({'status': 'SUCCESS', 'message': 'SLA deadlines monitoring executed successfully.'}, status=200)
    except Exception as e:
        logger.exception("Error executing cron_monitor_sla: %s", e)
        return JsonResponse({'status': 'ERROR', 'error': str(e)}, status=500)


@csrf_exempt
def cron_refresh_insights(request):
    """
    Cloud Scheduler / Cron endpoint to trigger hourly Civic Digital Twin policymaker AI synthesis.
    Protected by X-DPIG-CRON-KEY header, token query parameter, or Google App Engine cron header.
    """
    cron_key = request.headers.get('X-DPIG-CRON-KEY') or request.GET.get('token')
    gae_cron = request.headers.get('X-Appengine-Cron') == 'true'
    expected_key = getattr(settings, 'INTERNAL_API_KEY', 'dpig-internal-webhook-secret-2026')

    if not gae_cron and (not cron_key or cron_key != expected_key):
        return JsonResponse({'status': 'UNAUTHORIZED', 'message': 'Invalid cron authorization token.'}, status=401)

    from core.tasks import refresh_policymaker_insights_task
    try:
        refresh_policymaker_insights_task()
        return JsonResponse({'status': 'SUCCESS', 'message': 'Policymaker insights refreshed successfully.'}, status=200)
    except Exception as e:
        logger.exception("Error executing cron_refresh_insights: %s", e)
        return JsonResponse({'status': 'ERROR', 'error': str(e)}, status=500)





