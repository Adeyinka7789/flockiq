from django.contrib import admin

from .models import MedicationRecord, OutbreakAlert, SymptomLog, VaccinationSchedule


@admin.register(VaccinationSchedule)
class VaccinationScheduleAdmin(admin.ModelAdmin):
    list_display = ["vaccine_name", "batch", "farm", "due_date", "status", "reminder_sent"]
    list_filter = ["status", "route"]
    search_fields = ["vaccine_name", "batch__batch_name"]
    date_hierarchy = "due_date"


@admin.register(MedicationRecord)
class MedicationRecordAdmin(admin.ModelAdmin):
    list_display = ["drug_name", "batch", "farm", "start_date", "end_date", "withdrawal_cleared_date"]
    list_filter = ["drug_type", "reason"]
    search_fields = ["drug_name", "batch__batch_name"]
    date_hierarchy = "start_date"


@admin.register(SymptomLog)
class SymptomLogAdmin(admin.ModelAdmin):
    list_display = ["batch", "farm", "record_date", "affected_count", "severity"]
    list_filter = ["severity"]
    date_hierarchy = "record_date"


@admin.register(OutbreakAlert)
class OutbreakAlertAdmin(admin.ModelAdmin):
    list_display = ["disease_name", "farm", "source", "severity", "is_active", "created_at"]
    list_filter = ["source", "severity", "is_active"]
