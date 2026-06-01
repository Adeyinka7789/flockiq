from django.contrib import admin

from .models import ExpenseRecord


@admin.register(ExpenseRecord)
class ExpenseRecordAdmin(admin.ModelAdmin):
    list_display = ["expense_date", "category", "amount_kobo", "description", "farm", "batch"]
    list_filter = ["category", "expense_date"]
    search_fields = ["description", "receipt_ref"]
    date_hierarchy = "expense_date"
