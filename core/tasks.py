"""
Celery Asynchronous Tasks for DPIG:
- AI Complaint Triage (Gemini 3.8 Flash)
- Spatial Duplicate Detection (350m / 14-day clustering)
- SLA Breach Watchdog & Automated Escalation
- Periodic Policymaker Capital Project Synthesis
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.db.models import Q
from core.models import (
    Complaint, GrievanceCategory, Department, UserProfile,
    AIDecisionLog, SLAEscalationLog, Cluster, CapitalProjectRecommendation,
    find_officer_for_workflow_level
)
from core.digipin import haversine_distance_meters
from core import gemini_service
from core import notifications
from core.feature_matrix import is_feature_enabled

logger = logging.getLogger(__name__)


@shared_task(name='core.tasks.process_complaint_ai_triage_task')
def process_complaint_ai_triage_task(complaint_id: int):
    """
    Executes asynchronous AI triage using Google Gemini 3.8 Flash:
    - Analyzes language, script, category, urgency, and severity
    - Assigns to appropriate Ward/Zonal Officer
    - Dispatches email notifications to Citizen and Assignee
    """
    try:
        complaint = Complaint.objects.get(id=complaint_id)
    except Complaint.DoesNotExist:
        logger.error("Complaint ID %s does not exist for AI triage.", complaint_id)
        return

    # Check if AI Auto-Triage feature is enabled via SuperAdmin Feature Matrix
    if not is_feature_enabled('ai_auto_triage'):
        logger.info("AI Auto-Triage is disabled via Feature Matrix. Skipping AI processing for complaint #%s", complaint_id)
        detect_spatial_duplicates(complaint)
        return

    # Prepare available categories
    cats = GrievanceCategory.objects.filter(cluster=complaint.cluster).select_related('department')
    categories_payload = [
        {
            'code': c.code,
            'name': c.name,
            'dept_code': c.department.code,
            'dept_name': c.department.name
        } for c in cats
    ]

    # Read image bytes if present
    img_bytes = None
    img_mime = "image/jpeg"
    if complaint.image and hasattr(complaint.image, 'file'):
        try:
            complaint.image.open('rb')
            img_bytes = complaint.image.read()
            if complaint.image.name.lower().endswith('.png'):
                img_mime = "image/png"
        except Exception as e:
            logger.warning("Could not read image for AI triage: %s", e)

    # Call Gemini Service
    ai_result = gemini_service.triage_complaint(
        title=complaint.title,
        description=complaint.description,
        available_categories=categories_payload,
        image_bytes=img_bytes,
        image_mime_type=img_mime
    )

    # Update Complaint fields
    complaint.language_detected = ai_result.get('language_detected', 'en')
    complaint.script_detected = ai_result.get('script_detected', 'Latin')
    complaint.unicode_script_range = ai_result.get('unicode_script_range', 'U+0020–U+007F')
    complaint.translation_header = ai_result.get('translation_header', '')
    complaint.translated_title = ai_result.get('translated_title_en', complaint.title)
    complaint.translated_description = ai_result.get('translated_description_en', complaint.description)
    if not complaint.original_description:
        complaint.original_description = complaint.description
    complaint.severity = ai_result.get('severity', complaint.severity or 'MEDIUM')
    complaint.urgency_score = float(ai_result.get('urgency_score', 0.5))

    # Match Category & Department if not already matched
    rec_cat_code = ai_result.get('recommended_category_code')
    matched_cat = cats.filter(code=rec_cat_code).first()
    if matched_cat:
        complaint.category = matched_cat
        complaint.department = matched_cat.department

    # Auto-assign to DL1 Officer of that department in the selected zone
    dl1_profile = find_officer_for_workflow_level(
        complaint.cluster, complaint.zone, complaint.department, 'DL1'
    )
    assignee = dl1_profile.user if dl1_profile else None

    # Fallback to existing assignee if already assigned or zone officer
    if not assignee and complaint.current_assignee:
        assignee = complaint.current_assignee

    old_status = complaint.status
    complaint.current_assignee = assignee
    complaint.current_level = 'DL1'
    complaint.escalated_to_level = 1
    complaint.status = 'ASSIGNED' if assignee else 'AI_CLASSIFIED'
    complaint.save()

    # Create AI Decision Log
    AIDecisionLog.objects.create(
        complaint=complaint,
        model_name=ai_result.get('model_used', 'gemini-3.8-flash'),
        input_prompt=f"Title: {complaint.title}\nDescription: {complaint.description}",
        raw_response=ai_result.get('raw_response', ''),
        classified_category=complaint.category.name if complaint.category else "",
        classified_department=complaint.department.name if complaint.department else "",
        confidence_score=ai_result.get('confidence_score', 0.9),
        sentiment=ai_result.get('sentiment', 'neutral'),
        extracted_entities=ai_result.get('extracted_entities', {}),
        execution_time_ms=ai_result.get('execution_time_ms', 0)
    )

    # Immutable SHA-256 Audit Log
    complaint.create_audit_block(
        action="AI_TRIAGED_AND_ASSIGNED",
        actor_role="AI_ENGINE",
        details={
            "model": "gemini-3.8-flash",
            "language": complaint.language_detected,
            "severity": complaint.severity,
            "urgency": complaint.urgency_score,
            "assignee": assignee.username if assignee else "UNASSIGNED",
            "status": complaint.status
        }
    )

    # Check for spatial duplicates
    detect_spatial_duplicates(complaint)

    # Dispatch email notifications
    notifications.notify_complaint_status_changed(complaint, old_status, complaint.status, notes="AI triage completed and routed to department.")
    if assignee:
        notifications.notify_complaint_assigned(complaint, assignee)


def detect_spatial_duplicates(complaint: Complaint):
    """
    Checks for duplicate grievances within 350 meters and 14 days
    as defined in the system flowchart spatial intelligence specifications.
    Optimized with SQL bounding-box pre-filtering (~400m box) before Haversine calculation.
    """
    if not is_feature_enabled('duplicate_clustering'):
        logger.info("Spatial Duplicate Clustering is disabled via Feature Matrix. Skipping for complaint #%s", complaint.id)
        return

    cutoff = complaint.created_at - timedelta(days=14)
    # 0.004 degrees is ~444m at equator, ~400m at Chennai latitude (13 deg N)
    lat_delta = 0.004
    lon_delta = 0.004

    nearby_candidates = Complaint.objects.filter(
        cluster=complaint.cluster,
        department=complaint.department,
        created_at__gte=cutoff,
        status__in=['SUBMITTED', 'AI_CLASSIFIED', 'ASSIGNED', 'FIELD_VERIFICATION'],
        latitude__range=(complaint.latitude - lat_delta, complaint.latitude + lat_delta),
        longitude__range=(complaint.longitude - lon_delta, complaint.longitude + lon_delta)
    ).exclude(id=complaint.id)

    for candidate in nearby_candidates:
        dist = haversine_distance_meters(
            complaint.latitude, complaint.longitude,
            candidate.latitude, candidate.longitude
        )
        if dist <= 350.0:  # Within 350 meters
            complaint.is_duplicate_of = candidate
            complaint.save(update_fields=['is_duplicate_of'])
            complaint.create_audit_block(
                action="DUPLICATE_FLAGGED",
                actor_role="SPATIAL_ENGINE",
                details={
                    "parent_ticket": candidate.ticket_number,
                    "distance_meters": round(dist, 1),
                    "rule": "350m_14day_spatial_clustering"
                }
            )
            break


@shared_task(name='core.tasks.monitor_sla_deadlines_task')
def monitor_sla_deadlines_task():
    """
    Periodic watchdog (every 5 minutes) inspecting active tickets.
    Escalates breached tickets sequentially through:
    DL1 -> DL2 -> DL3 -> CL1 -> CL2 -> CL3 -> Escalated to CM Office.
    """
    if not is_feature_enabled('sla_escalation_watchdog'):
        logger.info("SLA Escalation Watchdog is disabled via Feature Matrix. Skipping execution.")
        return

    now = timezone.now()
    overdue_complaints = Complaint.objects.filter(
        sla_deadline__lt=now,
        status__in=['SUBMITTED', 'AI_CLASSIFIED', 'ASSIGNED', 'FIELD_VERIFICATION', 'ESCALATED', 'REOPENED']
    ).select_related('cluster', 'zone', 'ward', 'department', 'current_assignee')

    for c in overdue_complaints:
        if c.current_level == 'CM_OFFICE' and c.is_sla_breached:
            # Already at apex level and already marked/notified as breached; skip to prevent notification spam
            continue

        escalated = c.escalate_to_next_level(
            reason=f"SLA deadline breached at {c.current_level} ({c.sla_deadline.strftime('%Y-%m-%d %H:%M') if c.sla_deadline else 'Expired'})",
            auto=True
        )
        if not escalated:
            if not c.is_sla_breached:
                c.is_sla_breached = True
                c.save(update_fields=['is_sla_breached', 'updated_at'])
                if c.current_assignee:
                    notifications.notify_sla_escalation(c, c.sla_escalation_tier, c.current_assignee)


@shared_task(name='core.tasks.refresh_policymaker_insights_task')
def refresh_policymaker_insights_task(cluster_id=None):
    """
    Synthesizes Civic Digital Twin recommendations from citizen feedback
    and stores versioned CapitalProjectRecommendation records.
    """
    if not is_feature_enabled('ai_capital_projects'):
        logger.info("Civic Digital Twin AI Synthesis is disabled via Feature Matrix. Skipping execution.")
        return

    clusters = Cluster.objects.filter(id=cluster_id) if cluster_id else Cluster.objects.filter(is_active=True)
    for cl in clusters:
        recent_complaints = Complaint.objects.filter(
            cluster=cl,
            created_at__gte=timezone.now() - timedelta(days=60)
        ).values('title', 'category__name', 'department__name', 'zone__number', 'ward__number', 'severity', 'status')[:50]

        recommendations = gemini_service.synthesize_policymaker_insights(
            cluster_name=cl.name,
            complaints_data=list(recent_complaints)
        )

        for rec in recommendations:
            CapitalProjectRecommendation.objects.update_or_create(
                cluster=cl,
                title=rec['title'],
                defaults={
                    'sector': rec.get('sector', 'Civic Infrastructure'),
                    'affected_zones': rec.get('affected_zones', []),
                    'affected_wards': rec.get('affected_wards', []),
                    'complaint_cluster_count': rec.get('complaint_cluster_count', 1),
                    'problem_statement': rec.get('problem_statement', ''),
                    'proposed_solution': rec.get('proposed_solution', ''),
                    'estimated_budget_inr': rec.get('estimated_budget_inr', 10000000.00),
                    'priority_score': rec.get('priority_score', 80.0),
                    'ai_rationale': rec.get('ai_rationale', ''),
                    'status': 'PROPOSED'
                }
            )
