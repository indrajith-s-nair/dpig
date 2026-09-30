"""
Email Notification Service for Citizens and Assignees.
- Citizen receives email when new complaint is raised and during every status change till closure.
- Assignees receive email when complaint is assigned, transferred, or closed.
"""
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _send_email_safe(subject: str, text_content: str, html_content: str, recipient_list: list):
    """Safely dispatches email to recipients and fallback email without raising unhandled errors."""
    try:
        from core.feature_matrix import is_feature_enabled
        if not is_feature_enabled('citizen_notifications'):
            logger.info("Email notifications disabled via Feature Matrix. Skipping: %s", subject)
            return False

        from_email = settings.DEFAULT_FROM_EMAIL
        clean_recipients = [r for r in recipient_list if r and '@' in r]

        # Send fallback notification email as BCC to protect citizen and administrative privacy
        fallback = getattr(settings, 'NOTIFICATION_FALLBACK_EMAIL', None)
        bcc_recipients = []
        if fallback and fallback not in clean_recipients:
            bcc_recipients.append(fallback)

        if not clean_recipients and not bcc_recipients:
            logger.warning("No valid recipients for email: %s", subject)
            return False

        # If primary recipients exist, keep fallback in BCC; otherwise fallback is the sole recipient
        to_recipients = clean_recipients if clean_recipients else bcc_recipients
        bcc = bcc_recipients if clean_recipients else []

        msg = EmailMultiAlternatives(
            subject=f"[{settings.DEFAULT_FROM_EMAIL.split('<')[0].strip()}] {subject}",
            body=text_content,
            from_email=from_email,
            to=to_recipients,
            bcc=bcc
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info("Successfully sent email '%s' to %s", subject, clean_recipients)
        return True
    except Exception as e:
        logger.error("Failed to send email '%s' to %s: %s", subject, recipient_list, e)
        return False


def get_base_email_html(title: str, subtitle: str, badge: str, badge_color: str, rows: list, button_text: str = "", button_url: str = "") -> str:
    """Renders a clean, accessible government portal email template."""
    rows_html = "".join([
        f"""
        <tr>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #475569; width: 35%;">{label}</td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; color: #0f172a;">{val}</td>
        </tr>
        """ for label, val in rows
    ])

    btn_html = ""
    if button_text and button_url:
        btn_html = f"""
        <div style="text-align: center; margin: 28px 0 10px 0;">
            <a href="{button_url}" style="background-color: #0284c7; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 15px; display: inline-block;">
                {button_text}
            </a>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
        <div style="max-width: 620px; margin: 0 auto; background-color: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border: 1px solid #e2e8f0;">
            <div style="background-color: #0f172a; padding: 24px; text-align: center; color: #ffffff;">
                <div style="font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px; opacity: 0.8; margin-bottom: 6px;">DPIG - App • Digital Public Infrastructure</div>
                <h1 style="margin: 0; font-size: 20px; font-weight: 700;">Digital Public Infrastructure Governance</h1>
            </div>
            
            <div style="padding: 28px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px;">
                    <div>
                        <h2 style="margin: 0 0 4px 0; font-size: 18px; color: #0f172a;">{title}</h2>
                        <div style="font-size: 14px; color: #64748b;">{subtitle}</div>
                    </div>
                    <span style="background-color: {badge_color}; color: #ffffff; padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase;">{badge}</span>
                </div>

                <table style="width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; background: #fcfcfd; border-radius: 8px; border: 1px solid #e2e8f0;">
                    {rows_html}
                </table>

                {btn_html}

                <div style="margin-top: 30px; padding-top: 18px; border-top: 1px solid #f1f5f9; font-size: 12px; color: #94a3b8; text-align: center; line-height: 1.5;">
                    This is an automated communication from the state-wide Digital Public Infrastructure Governance (DPIG) Portal.<br>
                    For emergency civic assistance, please dial the 24x7 Municipal Helpline: <strong>1234</strong>.
                </div>
            </div>
        </div>
    </body>
    </html>
    """


def notify_complaint_created(complaint, base_url: str = "http://localhost:8000"):
    """Triggered when a citizen raises a new complaint."""
    tracking_url = f"{base_url}/track/{complaint.ticket_number}/"
    subject = f"Complaint Registered: {complaint.ticket_number} - {complaint.title[:40]}"

    rows = [
        ("Ticket Number", f"<strong>{complaint.ticket_number}</strong>"),
        ("Issue Title", complaint.title),
        ("DIGIPIN", f"<code>{complaint.digipin}</code>" if complaint.digipin else "N/A"),
        ("Zone / Ward", f"Zone {complaint.zone.number if complaint.zone else '-'} / Ward {complaint.ward.number if complaint.ward else '-'}"),
        ("Department", complaint.department.name if complaint.department else "Auto-Assigning..."),
        ("Current Status", f"<strong>{complaint.get_status_display()}</strong>"),
        ("SLA Resolution Target", complaint.sla_deadline.strftime("%d %b %Y, %I:%M %p") if complaint.sla_deadline else "24 Hours"),
    ]

    html_content = get_base_email_html(
        title="Grievance Successfully Registered",
        subtitle=f"Thank you, {complaint.citizen_name}. Your grievance has been recorded in the state registry.",
        badge="REGISTERED",
        badge_color="#2563eb",
        rows=rows,
        button_text="Track Live Status & SLA Countdown",
        button_url=tracking_url
    )
    text_content = f"Your grievance {complaint.ticket_number} has been registered. Track it here: {tracking_url}"

    return _send_email_safe(subject, text_content, html_content, [complaint.citizen_email])


def notify_complaint_status_changed(complaint, old_status: str, new_status: str, notes: str = "", base_url: str = "http://localhost:8000"):
    """Triggered during every status change until final closure."""
    tracking_url = f"{base_url}/track/{complaint.ticket_number}/"
    subject = f"Status Update: {complaint.ticket_number} is now {complaint.get_status_display()}"

    badge_colors = {
        'AI_CLASSIFIED': '#8b5cf6',
        'ASSIGNED': '#0284c7',
        'FIELD_VERIFICATION': '#d97706',
        'RESOLVED': '#16a34a',
        'CITIZEN_CONFIRMED': '#059669',
        'REOPENED': '#dc2626',
        'ESCALATED': '#e11d48',
    }
    badge_color = badge_colors.get(new_status, '#475569')

    rows = [
        ("Ticket Number", f"<strong>{complaint.ticket_number}</strong>"),
        ("Previous Status", dict(complaint.STATUS_CHOICES).get(old_status, old_status)),
        ("New Status", f"<strong>{complaint.get_status_display()}</strong>"),
        ("DIGIPIN", f"<code>{complaint.digipin}</code>" if complaint.digipin else "N/A"),
        ("Assigned Officer", complaint.current_assignee.get_full_name() or complaint.current_assignee.username if complaint.current_assignee else "Municipal Triage Desk"),
    ]

    if notes:
        rows.append(("Officer Remarks", notes))

    if complaint.sla_deadline:
        rows.append(("SLA Target", complaint.sla_deadline.strftime("%d %b %Y, %I:%M %p")))

    html_content = get_base_email_html(
        title=f"Grievance Progress Update",
        subtitle=f"Status for ticket {complaint.ticket_number} has progressed.",
        badge=complaint.get_status_display().upper(),
        badge_color=badge_color,
        rows=rows,
        button_text="View Updates & Proof",
        button_url=tracking_url
    )
    text_content = f"Update on {complaint.ticket_number}: Status changed to {complaint.get_status_display()}. Details: {tracking_url}"

    return _send_email_safe(subject, text_content, html_content, [complaint.citizen_email])


def notify_complaint_assigned(complaint, assignee, assigner=None, base_url: str = "http://localhost:8000"):
    """Triggered when a grievance is assigned to an officer or field engineer."""
    portal_url = f"{base_url}/officer/complaint/{complaint.id}/"
    subject = f"ACTION REQUIRED: Grievance Assigned {complaint.ticket_number} [{complaint.severity}]"

    rows = [
        ("Ticket Number", f"<strong>{complaint.ticket_number}</strong>"),
        ("Issue Title", complaint.title),
        ("Severity", f"<strong>{complaint.get_severity_display()}</strong>"),
        ("Zone / Ward", f"Zone {complaint.zone.number if complaint.zone else '-'} / Ward {complaint.ward.number if complaint.ward else '-'}"),
        ("Location / DIGIPIN", f"<code>{complaint.digipin}</code> ({complaint.latitude}, {complaint.longitude})"),
        ("Citizen", f"{complaint.citizen_name} ({complaint.citizen_phone or complaint.citizen_email})"),
        ("SLA Deadline", complaint.sla_deadline.strftime("%d %b %Y, %I:%M %p") if complaint.sla_deadline else "Immediate"),
        ("Assigned By", assigner.get_full_name() if assigner else "Automated AI Router"),
    ]

    html_content = get_base_email_html(
        title="New Grievance Assignment",
        subtitle=f"You have been assigned as the primary resolution officer for ticket {complaint.ticket_number}.",
        badge="ASSIGNED TO YOU",
        badge_color="#0284c7",
        rows=rows,
        button_text="Open Officer Resolution Console",
        button_url=portal_url
    )
    text_content = f"You have been assigned grievance {complaint.ticket_number}. Resolve at: {portal_url}"

    return _send_email_safe(subject, text_content, html_content, [assignee.email])


def notify_complaint_transferred(complaint, old_assignee, new_assignee, base_url: str = "http://localhost:8000"):
    """Triggered when a grievance is transferred between officers/departments."""
    portal_url = f"{base_url}/officer/complaint/{complaint.id}/"
    subject = f"Grievance Transferred: {complaint.ticket_number}"

    # Notify new assignee
    if new_assignee:
        notify_complaint_assigned(complaint, new_assignee, assigner=old_assignee, base_url=base_url)

    # Notify old assignee of transfer off their queue
    if old_assignee and old_assignee.email:
        rows = [
            ("Ticket Number", complaint.ticket_number),
            ("Transferred To", new_assignee.get_full_name() if new_assignee else "General Pool"),
            ("Status", complaint.get_status_display()),
        ]
        html_content = get_base_email_html(
            title="Grievance Reassigned",
            subtitle=f"Ticket {complaint.ticket_number} has been transferred off your active queue.",
            badge="TRANSFERRED",
            badge_color="#64748b",
            rows=rows,
            button_text="View Ticket",
            button_url=portal_url
        )
        _send_email_safe(subject, f"Ticket {complaint.ticket_number} transferred.", html_content, [old_assignee.email])


def notify_complaint_closed(complaint, closed_by_citizen: bool = True, base_url: str = "http://localhost:8000"):
    """Triggered when a grievance is confirmed closed by citizen or finalized."""
    tracking_url = f"{base_url}/track/{complaint.ticket_number}/"
    subject = f"Grievance Closed: {complaint.ticket_number}"

    # Email to Citizen
    rows_citizen = [
        ("Ticket Number", complaint.ticket_number),
        ("Status", "Closed & Confirmed"),
        ("Resolved By", complaint.current_assignee.get_full_name() if complaint.current_assignee else "Municipal Team"),
        ("Your Rating", f"{'★' * (complaint.citizen_rating or 5)} ({complaint.citizen_rating or 5}/5)"),
    ]
    html_citizen = get_base_email_html(
        title="Grievance Successfully Closed",
        subtitle=f"Thank you for validating the field resolution, {complaint.citizen_name}.",
        badge="CLOSED",
        badge_color="#059669",
        rows=rows_citizen,
        button_text="View Archival Record",
        button_url=tracking_url
    )
    res1 = _send_email_safe(subject, f"Grievance {complaint.ticket_number} is closed.", html_citizen, [complaint.citizen_email])

    # Email to Assignee
    res2 = True
    if complaint.current_assignee and complaint.current_assignee.email:
        rows_officer = [
            ("Ticket Number", complaint.ticket_number),
            ("Citizen", complaint.citizen_name),
            ("Citizen Rating", f"{'★' * (complaint.citizen_rating or 5)} ({complaint.citizen_rating or 5}/5)"),
            ("Citizen Feedback", complaint.citizen_feedback or "Resolution confirmed without additional comments."),
        ]
        html_officer = get_base_email_html(
            title="Citizen Confirmed Resolution",
            subtitle=f"The citizen has accepted the resolution for {complaint.ticket_number}.",
            badge="RESOLVED & RATED",
            badge_color="#059669",
            rows=rows_officer,
            button_text="View Ticket Record",
            button_url=tracking_url
        )
        res2 = _send_email_safe(f"Closed: {complaint.ticket_number} Rated {complaint.citizen_rating or 5}/5", "Citizen confirmed resolution.", html_officer, [complaint.current_assignee.email])

    return res1 and res2


def notify_sla_escalation(complaint, tier: int, target_officer, base_url: str = "http://localhost:8000"):
    """Triggered when SLA is breached and ticket is escalated."""
    portal_url = f"{base_url}/officer/complaint/{complaint.id}/"
    subject = f"URGENT SLA ESCALATION: Tier {tier} - {complaint.ticket_number}"

    rows = [
        ("Ticket Number", f"<strong style='color: #dc2626;'>{complaint.ticket_number}</strong>"),
        ("Issue Title", complaint.title),
        ("Escalation Tier", f"<strong>Tier {tier}</strong>"),
        ("Original SLA Deadline", complaint.sla_deadline.strftime("%d %b %Y, %I:%M %p") if complaint.sla_deadline else "Expired"),
        ("Zone / Ward", f"Zone {complaint.zone.number if complaint.zone else '-'} / Ward {complaint.ward.number if complaint.ward else '-'}"),
        ("Previous Assignee", complaint.current_assignee.get_full_name() if complaint.current_assignee else "None"),
    ]

    html_content = get_base_email_html(
        title="Critical SLA Breach Escalation",
        subtitle=f"This complaint has breached SLA deadlines and has been escalated to Tier {tier} review.",
        badge="SLA BREACH",
        badge_color="#dc2626",
        rows=rows,
        button_text="Intervene & Reassign",
        button_url=portal_url
    )
    recipient = target_officer.email if target_officer else None
    if recipient:
        _send_email_safe(subject, f"SLA Breach on {complaint.ticket_number}.", html_content, [recipient])
