import os
import logging
import mimetypes
import requests
from concurrent.futures import ThreadPoolExecutor

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.db import close_old_connections
from django.contrib.auth import login as auth_login

from .forms import RegistrationForm, PDFUploadForm
from .models import Profile, AnalysisResult
from .services.onemg import search_onemg, _clean_price
from .services.classifier import classify_item
from .services.medicine_matcher import find_medicine_details, search_medicines, get_medicine_by_name

logger = logging.getLogger(__name__)

# Configurable OCR & AI extraction API endpoint
OCR_API_URL = os.getenv("OCR_API_URL", "http://127.0.0.1:8001/extract-from-file")


def home(request):
    """
    Renders the modern MediData application homepage.
    """
    user_recent_scans = []
    if request.user.is_authenticated:
        try:
            user_recent_scans = list(
                AnalysisResult.objects.filter(user=request.user)
                .order_by("-created_at")[:5]
                .values("id", "original_filename", "created_at")
            )
        except Exception:
            user_recent_scans = []

    context = {
        "title": f"MediData • {request.user.first_name}" if request.user.is_authenticated and request.user.first_name else "MediData — Intelligent Medical Bill Analysis",
        "recent_scans": user_recent_scans,
        "is_authenticated": request.user.is_authenticated,
    }

    return render(request, "MediData/home.html", context)


def register(request):
    """
    User registration view.
    """
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])

            names = form.cleaned_data["full_name"].strip().split(" ", 1)
            user.first_name = names[0]
            user.last_name = names[1] if len(names) > 1 else ""
            user.save()

            Profile.objects.create(
                user=user,
                dob=form.cleaned_data.get("dob")
            )

            # Auto log in user on registration
            auth_login(request, user)
            return redirect("home")
    else:
        form = RegistrationForm()

    return render(request, "MediData/register.html", {"form": form})


def process_item(item):
    """
    Processes an individual line item: classifies category, searches 1mg market price,
    and matches clinical dataset information.
    """
    raw_name = str(item.get("item_name", "")).strip()
    item_type = classify_item(raw_name)

    onemg_result = None
    medicine_info = None

    quantity = _clean_price(item.get("item_quantity", 1)) or 1.0
    rate = _clean_price(item.get("item_rate", 0)) or 0.0
    amount = _clean_price(item.get("item_amount", 0)) or round(quantity * rate, 2)

    if item_type == "MEDICINE":
        try:
            onemg_result = search_onemg(raw_name)
        except Exception as e:
            print(f"1mg Error for '{raw_name}': {e}")

        try:
            search_target = raw_name
            if onemg_result and onemg_result.get("name"):
                search_target = onemg_result["name"]

            medicine_info = find_medicine_details(search_target)
        except Exception as e:
            print(f"Matcher Error for '{raw_name}': {e}")

    # Calculate unit price comparison if available
    market_price = onemg_result.get("numeric_price") if onemg_result else None
    savings_per_unit = None
    if market_price is not None and rate > 0:
        savings_per_unit = round(rate - market_price, 2)

    return {
        "item_name": raw_name,
        "category": item_type,
        "quantity": quantity,
        "rate": rate,
        "amount": amount,
        "onemg": onemg_result,
        "medicine_info": medicine_info,
        "savings_per_unit": savings_per_unit,
    }


@require_POST
def analyse_pdf(request):
    """
    Endpoint accepting medical bill document uploads (PDF or Images),
    forwarding to the OCR/LLM service and augmenting with live medicine & price intelligence.
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": "Authentication required. Please log in or create an account to analyze medical bills.",
                "authenticated": False
            },
            status=401
        )

    form = PDFUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        errors = form.errors.as_text()
        return JsonResponse(
            {"error": f"Invalid upload: {errors}"},
            status=400
        )

    uploaded_file = request.FILES["file"]
    content_type, _ = mimetypes.guess_type(uploaded_file.name)
    if not content_type:
        content_type = "application/pdf" if uploaded_file.name.lower().endswith(".pdf") else "image/jpeg"

    try:
        files = {
            "file": (
                uploaded_file.name,
                uploaded_file.read(),
                content_type,
            )
        }

        response = requests.post(
            OCR_API_URL,
            files=files,
            timeout=180,
        )
        response.raise_for_status()
        raw_json = response.json()

    except requests.Timeout:
        return JsonResponse(
            {
                "error": "The OCR analysis service timed out while processing your document. Please ensure the document is clear and try again."
            },
            status=504
        )
    except requests.ConnectionError:
        logger.warning("OCR service is unavailable at the configured endpoint")
        return JsonResponse(
            {
                "error": "Unable to connect to the OCR extraction service. Please try again later."
            },
            status=503
        )
    except requests.RequestException as e:
        logger.warning("OCR service request failed: %s", e)
        return JsonResponse(
            {
                "error": "The OCR extraction service could not process this request. Please try again later."
            },
            status=502
        )
    except ValueError:
        return JsonResponse(
            {
                "error": "Malformed response received from the analysis server."
            },
            status=502
        )

    if not raw_json.get("is_success"):
        return JsonResponse(
            {
                "error": raw_json.get("error") or "Analysis failed to extract items from the bill."
            },
            status=500
        )

    data = raw_json.get("data", {}) or {}
    items = []

    for page in data.get("pagewise_line_items", []):
        items.extend(page.get("bill_items", []))

    if not items:
        # If pagewise is empty, fallback to raw items if present
        items = data.get("bill_items", [])

    # Process item classification, 1mg search, and rapidfuzz matching concurrently
    with ThreadPoolExecutor(max_workers=6) as executor:
        all_items = list(executor.map(process_item, items))

    # Compute category statistics & price insights
    category_summary = {
        "medicines": 0,
        "lab_tests": 0,
        "devices": 0,
        "services": 0,
    }
    total_bill_amount = 0.0
    total_market_amount = 0.0
    comparisons_count = 0

    for it in all_items:
        cat = it.get("category", "")
        if cat == "MEDICINE":
            category_summary["medicines"] += 1
        elif cat == "LAB_TEST":
            category_summary["lab_tests"] += 1
        elif cat == "MEDICAL_DEVICE":
            category_summary["devices"] += 1
        else:
            category_summary["services"] += 1

        total_bill_amount += float(it.get("amount", 0) or 0)

        onemg = it.get("onemg")
        if onemg and onemg.get("numeric_price"):
            qty = float(it.get("quantity", 1) or 1)
            total_market_amount += onemg["numeric_price"] * qty
            comparisons_count += 1

    grand_total = data.get("grand_total")
    if grand_total is None or float(grand_total or 0) == 0:
        grand_total = round(total_bill_amount, 2)
    else:
        grand_total = round(float(grand_total), 2)

    result_payload = {
        "line_items": all_items,
        "final_total": grand_total,
        "item_count": data.get("total_item_count", len(all_items)),
        "summary": category_summary,
        "financials": {
            "bill_total": grand_total,
            "calculated_total": round(total_bill_amount, 2),
            "market_compared_total": round(total_market_amount, 2),
            "comparisons_count": comparisons_count,
        },
        "error_flag": raw_json.get("error"),
    }

    uploaded_file.seek(0)
    close_old_connections()

    try:
        record = AnalysisResult.objects.create(
            user=request.user,
            pdf_file=uploaded_file,
            original_filename=uploaded_file.name,
            result=result_payload,
        )
        record_id = record.id
    except Exception as e:
        print(f"Failed to persist AnalysisResult: {e}")
        record_id = None

    return JsonResponse({
        "success": True,
        "id": record_id,
        "filename": uploaded_file.name,
        "data": result_payload
    })


@require_GET
def api_search_medicines(request):
    """
    Fast autocomplete & live search API for the 11,800+ medicine dataset.
    """
    query = request.GET.get("q", "").strip()
    limit = int(request.GET.get("limit", 12))
    limit = max(1, min(limit, 50))

    results = search_medicines(query=query, limit=limit)
    return JsonResponse({
        "success": True,
        "query": query,
        "count": len(results),
        "results": results
    })


@require_GET
def api_medicine_detail(request):
    """
    Fetches full clinical details and live 1mg market price for a selected medicine.
    """
    name = request.GET.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "Medicine name is required."}, status=400)

    med = get_medicine_by_name(name)
    if not med:
        return JsonResponse({"error": f"Medicine '{name}' not found in database."}, status=404)

    # Optional live 1mg lookup
    onemg_data = None
    try:
        onemg_data = search_onemg(name)
    except Exception as e:
        print(f"1mg lookup exception in detail API: {e}")

    return JsonResponse({
        "success": True,
        "medicine": med,
        "onemg": onemg_data
    })


@require_GET
def api_analysis_history(request):
    """
    Returns previous bill analysis records for the authenticated user.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        records = AnalysisResult.objects.filter(user=request.user).order_by("-created_at")[:20]
        data = []
        for r in records:
            res = r.result or {}
            data.append({
                "id": r.id,
                "filename": r.original_filename or os.path.basename(r.pdf_file.name if r.pdf_file else "Invoice"),
                "created_at": r.created_at.strftime("%b %d, %Y • %H:%M"),
                "item_count": res.get("item_count", 0),
                "total": res.get("final_total", 0),
                "summary": res.get("summary", {}),
            })
        return JsonResponse({"success": True, "history": data})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)