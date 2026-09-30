"""
Django Admin Configuration for DPIG
"""
from django.contrib import admin
from core.models import (
    Cluster, Zone, Ward, Department, GrievanceCategory, UserProfile,
    Complaint, ComplaintAuditLog, AIDecisionLog, SLAEscalationLog,
    GovernmentBroadcast, CapitalProjectRecommendation
)


class ZoneInline(admin.TabularInline):
    model = Zone
    extra = 0


class WardInline(admin.TabularInline):
    model = Ward
    extra = 0


class ComplaintAuditLogInline(admin.TabularInline):
    model = ComplaintAuditLog
    extra = 0
    readonly_fields = ('action', 'performed_by', 'actor_role', 'previous_hash', 'current_hash', 'created_at')
    can_delete = False


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'cluster_type', 'state', 'commissioner_name', 'emergency_helpline', 'is_active')
    search_fields = ('name', 'code', 'commissioner_name')
    list_filter = ('cluster_type', 'state', 'is_active')
    inlines = [ZoneInline]


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'cluster', 'zonal_officer_name', 'zonal_officer_phone')
    list_filter = ('cluster',)
    search_fields = ('name', 'zonal_officer_name')
    inlines = [WardInline]


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'zone', 'centroid_lat', 'centroid_lng', 'digipin_prefix')
    list_filter = ('zone__cluster', 'zone')
    search_fields = ('name', 'number', 'digipin_prefix')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'cluster', 'head_officer', 'standard_sla_hours')
    list_filter = ('cluster',)
    search_fields = ('name', 'code', 'head_officer')


@admin.register(GrievanceCategory)
class GrievanceCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'department', 'default_severity', 'sla_hours')
    list_filter = ('cluster', 'department', 'default_severity')
    search_fields = ('name', 'code')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'cluster', 'zone', 'ward', 'department', 'phone')
    list_filter = ('role', 'cluster')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'phone')


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'title', 'status', 'severity', 'digipin', 'ward', 'current_assignee', 'sla_deadline', 'is_sla_breached', 'created_at')
    list_filter = ('status', 'severity', 'is_sla_breached', 'cluster', 'department')
    search_fields = ('ticket_number', 'title', 'digipin', 'citizen_name', 'citizen_phone')
    readonly_fields = ('ticket_number', 'digipin', 'created_at', 'updated_at')
    inlines = [ComplaintAuditLogInline]


@admin.register(ComplaintAuditLog)
class ComplaintAuditLogAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'action', 'actor_role', 'current_hash', 'created_at')
    search_fields = ('complaint__ticket_number', 'action', 'current_hash')
    readonly_fields = ('complaint', 'action', 'performed_by', 'actor_role', 'details', 'previous_hash', 'current_hash', 'created_at')


@admin.register(AIDecisionLog)
class AIDecisionLogAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'model_name', 'confidence_score', 'sentiment', 'execution_time_ms', 'created_at')
    list_filter = ('model_name', 'sentiment')
    search_fields = ('complaint__ticket_number',)


@admin.register(GovernmentBroadcast)
class GovernmentBroadcastAdmin(admin.ModelAdmin):
    list_display = ('title', 'broadcast_type', 'department', 'priority', 'is_active', 'valid_from', 'valid_until', 'created_at')
    list_filter = ('broadcast_type', 'department', 'priority', 'is_active', 'cluster')
    search_fields = ('title', 'content', 'eligibility_criteria', 'benefits')


@admin.register(CapitalProjectRecommendation)
class CapitalProjectRecommendationAdmin(admin.ModelAdmin):
    list_display = ('title', 'cluster', 'sector', 'priority_score', 'estimated_budget_inr', 'status', 'created_at')
    list_filter = ('sector', 'status', 'cluster')
    search_fields = ('title', 'problem_statement')
