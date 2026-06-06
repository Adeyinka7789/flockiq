# CORRECTED: apps/infrastructure/core/helpers.py
# Better tenant context validation helper used across all views

from django.http import Http404
from django.shortcuts import redirect
import structlog

logger = structlog.get_logger(__name__)


def get_org_or_404(request, require_active=True):
    """
    Safely retrieve tenant org from request with validation.
    
    Args:
        request: Django request object
        require_active: If True, checks that org is_active flag is set
        
    Returns:
        Organization instance if valid
        
    Raises:
        Http404: If org is missing, deleted, or inactive (if required)
    """
    org = getattr(request.user, "org", None)
    if org is None:
        logger.warning(
            "get_org_or_404.missing_org",
            user_id=str(request.user.id),
            user_email=request.user.email,
        )
        raise Http404("No organisation found for this user.")
    
    try:
        # Refresh from DB to validate still exists
        org.refresh_from_db()
        
        if require_active and not org.is_active:
            logger.warning(
                "get_org_or_404.inactive_org",
                org_id=str(org.id),
                org_name=org.name,
                user_id=str(request.user.id),
            )
            raise Http404("Your organisation is no longer active.")
        
        return org
    except org.__class__.DoesNotExist:
        logger.warning(
            "get_org_or_404.org_deleted",
            org_id=str(org.id),
            user_id=str(request.user.id),
        )
        raise Http404("Your organisation no longer exists.")


def get_org_or_redirect(request, redirect_to="/", require_active=True):
    """
    Safely retrieve tenant org from request, redirecting if invalid.
    
    Args:
        request: Django request object
        redirect_to: URL to redirect to if org is invalid (default: "/")
        require_active: If True, checks that org is_active flag is set
        
    Returns:
        Organization instance if valid
        None: If org is invalid (caller should return the redirect)
    """
    org = getattr(request.user, "org", None)
    if org is None:
        logger.warning(
            "get_org_or_redirect.missing_org",
            user_id=str(request.user.id),
            redirect_to=redirect_to,
        )
        return None
    
    try:
        org.refresh_from_db()
        
        if require_active and not org.is_active:
            logger.warning(
                "get_org_or_redirect.inactive_org",
                org_id=str(org.id),
                redirect_to=redirect_to,
            )
            return None
        
        return org
    except org.__class__.DoesNotExist:
        logger.warning(
            "get_org_or_redirect.org_deleted",
            org_id=str(org.id),
            redirect_to=redirect_to,
        )
        return None


# Usage in views:
#
# from apps.infrastructure.core.helpers import get_org_or_404, get_org_or_redirect
#
# class MyView(LoginRequiredMixin, View):
#     def get(self, request):
#         org = get_org_or_404(request)
#         # ... rest of view, org guaranteed to exist
#
# class MyViewRedirect(LoginRequiredMixin, View):
#     def get(self, request):
#         org = get_org_or_redirect(request)
#         if not org:
#             return redirect('/')
#         # ... rest of view


# ============================================================================
# IMPROVED TEMPLATES FOR HTMX LOADING STATES
# ============================================================================

HTMX_TEMPLATE_SNIPPETS = """
<!-- Base HTMX button with loading indicator -->
<button hx-post="{% url 'view_name' %}"
        hx-indicator="#loading-spinner"
        hx-disabled-elt="this"
        class="btn btn-primary"
        type="submit">
  <span hx-indicator="none">
    Send Request
  </span>
  <span hx-indicator="this" class="hidden">
    <svg class="inline animate-spin h-4 w-4 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
    Processing...
  </span>
</button>

<div id="loading-spinner" class="htmx-indicator hidden">
  Loading...
</div>

<!-- Skeleton loader for data tables -->
<div id="table-skeleton" class="htmx-indicator">
  <div class="animate-pulse space-y-2">
    <div class="h-4 bg-gray-200 rounded"></div>
    <div class="h-4 bg-gray-200 rounded w-5/6"></div>
    <div class="h-4 bg-gray-200 rounded w-4/6"></div>
  </div>
</div>

<!-- Form with validation error handling -->
<form hx-post="{% url 'form_submit' %}"
      hx-target="#form-result"
      hx-swap="innerHTML"
      hx-indicator="#form-loader"
      hx-on="htmx:responseError: showErrorToast(event)">
  
  <div class="mb-4">
    <label for="input1" class="block text-sm font-medium">Field 1</label>
    <input type="text" id="input1" name="field1" required class="mt-1 form-input" />
  </div>
  
  <div class="flex gap-2">
    <button type="submit" class="btn btn-primary">
      <span hx-indicator="none">Submit</span>
      <span hx-indicator="this" class="hidden">
        <svg class="inline animate-spin h-4 w-4 mr-2"></svg>
      </span>
    </button>
  </div>
  
  <div id="form-loader" class="htmx-indicator">
    <svg class="inline animate-spin h-4 w-4"></svg>
  </div>
</form>

<div id="form-result"></div>

<!-- Heavy report export with timeout indicator -->
<div class="space-y-2">
  <button hx-get="{% url 'export_pdf' batch.pk %}"
          hx-target="#export-result"
          hx-swap="innerHTML"
          hx-indicator="#pdf-spinner"
          hx-disabled-elt="this"
          class="btn btn-sm btn-outline">
    {% if plan_features.pdf_export %}
      📄 Export as PDF
    {% else %}
      🔒 PDF Export (Upgrade required)
    {% endif %}
  </button>
  
  <div id="pdf-spinner" class="htmx-indicator text-sm text-gray-600">
    <svg class="inline animate-spin h-4 w-4 mr-2"></svg>
    Generating PDF (this may take 10-30 seconds)...
  </div>
</div>

<div id="export-result"></div>

<!-- Table refresh with pagination -->
<div hx-target="this"
     hx-swap="innerHTML"
     hx-indicator="#table-loader">
  
  <table class="w-full">
    <thead>
      <tr>
        <th>Name</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
        {% include "partial_row.html" %}
      {% endfor %}
    </tbody>
  </table>
  
  <!-- Pagination with HTMX triggers -->
  <div class="flex gap-2 mt-4">
    <button hx-get="{% url 'list_view' %}?page=1"
            class="btn btn-sm">First</button>
    <button hx-get="{% url 'list_view' %}?page={{ page_obj.previous_page_number }}"
            {% if not page_obj.has_previous %}disabled{% endif %}
            class="btn btn-sm">Previous</button>
    
    <span class="text-sm">Page {{ page_obj.number }} of {{ page_obj.paginator.num_pages }}</span>
    
    <button hx-get="{% url 'list_view' %}?page={{ page_obj.next_page_number }}"
            {% if not page_obj.has_next %}disabled{% endif %}
            class="btn btn-sm">Next</button>
    <button hx-get="{% url 'list_view' %}?page={{ page_obj.paginator.num_pages }}"
            class="btn btn-sm">Last</button>
  </div>
  
  <div id="table-loader" class="htmx-indicator">
    <svg class="inline animate-spin h-4 w-4"></svg> Loading...
  </div>
</div>

<!-- Debounced search with clear indicator -->
<input type="text"
       name="q"
       placeholder="Search..."
       hx-get="{% url 'search_view' %}"
       hx-target="#search-results"
       hx-swap="innerHTML"
       hx-indicator="#search-spinner"
       hx-trigger="keyup delay:500ms"
       class="form-input" />

<div id="search-spinner" class="htmx-indicator inline-block ml-2">
  <svg class="inline animate-spin h-4 w-4"></svg>
</div>

<div id="search-results" class="mt-4"></div>

<!-- Modal form submission with error handling -->
<div id="modal" class="fixed inset-0 bg-black/50 hidden">
  <div class="bg-white rounded-lg p-6 max-w-md mx-auto mt-20">
    <h2 class="text-lg font-bold mb-4">Add Item</h2>
    
    <form hx-post="{% url 'add_item' %}"
          hx-target="#modal"
          hx-swap="outerHTML swap:1s"
          hx-on="htmx:responseError: handleError(event)">
      
      <div class="mb-4">
        <input type="text" name="name" required class="form-input" />
      </div>
      
      <div class="flex gap-2 justify-end">
        <button type="button"
                hx-on="click: closeModal()"
                class="btn btn-outline">Cancel</button>
        <button type="submit"
                hx-disabled-elt="this"
                class="btn btn-primary">
          <span hx-indicator="none">Submit</span>
          <span hx-indicator="this" class="hidden">Loading...</span>
        </button>
      </div>
      
      <div class="htmx-indicator text-center mt-2">
        <svg class="inline animate-spin h-4 w-4"></svg>
      </div>
    </form>
  </div>
</div>
"""
