"""
Core URL routing for DPIG platform.
"""
from django.urls import path
from core import views

urlpatterns = [
    # Health and liveness probe
    path('healthz/', views.health_check, name='health_check'),

    # Citizen channels
    path('', views.home, name='home'),
    path('citizen/', views.citizen_hub, name='citizen_hub'),
    path('complaint/new/', views.file_complaint, name='file_complaint'),
    path('track/', views.track_complaint, name='track_complaint_search'),
    path('track/<str:ticket_number>/', views.track_complaint, name='track_complaint'),

    # Aadhaar Authentication & Citizen Identity Services
    path('citizen/register/', views.citizen_register, name='citizen_register'),
    path('citizen/login/', views.citizen_login, name='citizen_login'),
    path('citizen/forgot-password/', views.citizen_forgot_password, name='citizen_forgot_password'),
    path('api/aadhaar/send-otp/', views.api_aadhaar_send_otp, name='api_aadhaar_send_otp'),
    path('api/aadhaar/verify-otp/', views.api_aadhaar_verify_otp, name='api_aadhaar_verify_otp'),

    # Government / Officer Console
    path('officer/', views.officer_dashboard, name='officer_dashboard'),
    path('officer/complaint/<int:complaint_id>/', views.officer_complaint_detail, name='officer_complaint_detail'),

    # Policymaker Intelligence Hub & Planned Work
    path('policymaker/', views.policymaker_dashboard, name='policymaker_dashboard'),
    path('policymaker/trigger-ai/', views.trigger_ai_insights, name='trigger_ai_insights'),
    path('policymaker/project/<int:project_id>/plan/', views.toggle_planned_work, name='toggle_planned_work'),
    path('policymaker/planned-work/download/', views.download_planned_work, name='download_planned_work'),

    # Departmental Administration Console (Staff, Time-based Alerts & Welfare Schemes)
    path('dept-admin/', views.dept_admin_dashboard, name='dept_admin_dashboard'),
    path('dept-admin/staff/', views.dept_admin_staff, name='dept_admin_staff'),
    path('dept-admin/alerts/', views.dept_admin_alerts, name='dept_admin_alerts'),
    path('dept-admin/schemes/', views.dept_admin_schemes, name='dept_admin_schemes'),

    # Statutory Auditor & Compliance Hub
    path('auditor/', views.auditor_dashboard, name='auditor_dashboard'),
    path('auditor/complaint/<int:complaint_id>/', views.auditor_complaint_detail, name='auditor_complaint_detail'),
    path('auditor/complaint/<int:complaint_id>/action/', views.auditor_record_action, name='auditor_record_action'),
    path('auditor/integrity-scan/', views.auditor_system_integrity_scan, name='auditor_system_integrity_scan'),
    path('auditor/export/', views.auditor_export_report, name='auditor_export_report'),

    # SuperAdmin Control Center, Staff Management & 1-Click Cluster Onboarding
    path('superadmin/staff/', views.superadmin_staff_management, name='superadmin_staff_management'),
    path('superadmin/staff/download-template/', views.download_officer_template, name='download_officer_template'),
    path('superadmin/staff/bulk-upload/', views.bulk_upload_officers, name='bulk_upload_officers'),
    path('superadmin/staff/export/', views.export_officer_roster_view, name='export_officer_roster'),
    path('superadmin/matrix/', views.feature_permission_matrix, name='feature_permission_matrix'),
    path('superadmin/seed-demo-data/', views.seed_demo_data_view, name='seed_demo_data'),
    path('superadmin/purge-demo-data/', views.purge_demo_data_view, name='purge_demo_data'),
    path('superadmin/clusters/', views.cluster_onboard, name='cluster_onboard'),
    path('superadmin/clusters/<int:cluster_id>/toggle/', views.toggle_cluster_status, name='toggle_cluster_status'),
    path('superadmin/download-template/', views.download_template, name='download_template'),

    # REST / JSON APIs
    path('api/digipin/encode/', views.api_digipin_encode, name='api_digipin_encode'),
    path('api/digipin/decode/', views.api_digipin_decode, name='api_digipin_decode'),
    path('api/resolve-ward/', views.api_resolve_ward, name='api_resolve_ward'),
    path('api/complaints/geojson/', views.api_complaints_geojson, name='api_complaints_geojson'),
    path('api/complaints/ingest/', views.api_complaint_ingest, name='api_complaint_ingest'),
    path('api/verify-audit/<str:ticket_number>/', views.api_verify_audit_chain, name='api_verify_audit_chain'),
    path('api/detect-script/', views.api_detect_script, name='api_detect_script'),

    # Serverless Cron Triggers (Google Cloud Scheduler)
    path('api/cron/monitor-sla/', views.cron_monitor_sla, name='cron_monitor_sla'),
    path('api/cron/refresh-insights/', views.cron_refresh_insights, name='cron_refresh_insights'),

    # Demo role switcher
    path('switch-role/<str:role>/', views.switch_demo_role, name='switch_demo_role'),

    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
