"""
Expense Categorization Service (Gov → Citizen Transparency)
- Expense ingestion and categorization
- Anomaly detection in spending
- Monthly summary generation for citizens
"""
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4
from datetime import datetime, date
from collections import defaultdict

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY
from services.expense_ocr import extract_receipt_info
from services.audit_service import log_ai_decision

# Initialize Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Expense categories
EXPENSE_CATEGORIES = {
    "infrastructure": ["road", "bridge", "construction", "repair", "maintenance"],
    "salaries": ["salary", "wage", "compensation", "payroll", "bonus"],
    "utilities": ["electricity", "water", "internet", "telephone", "gas"],
    "supplies": ["office", "stationery", "equipment", "furniture", "IT", "mart", "store", "supermarket"],
    "transport": ["vehicle", "fuel", "travel", "transport", "logistics", "petrol", "shell", "oil"],
    "welfare": ["pension", "healthcare", "subsidy", "grant", "aid", "pharmacy", "clinic"],
    "food": ["restaurant", "cafe", "coffee", "bistro", "food", "kitchen"]
}

async def process_receipt(image_bytes: bytes) -> Dict[str, Any]:
    """
    Process receipt image -> OCR -> categorize -> ingest.
    """
    # 1. OCR Extraction
    info = extract_receipt_info(image_bytes)
    
    if "error" in info:
        return {"error": info["error"], "success": False}
        
    merchant = info.get("merchant", "Unknown Merchant")
    total_amount = info.get("total", 0.0)
    date_str = info.get("date", datetime.utcnow().date().isoformat())
    raw_text = info.get("raw_text", "")
    items = info.get("items", [])
    
    # 2. Categorize based on Merchant + Items
    description = f"{merchant} " + " ".join([i['name'] for i in items])
    category, subcategory, confidence = await categorize_expense(description)
    
    # 3. Detect Anomaly
    department = "finance" # Default department
    anomaly_score, is_anomaly = await detect_anomaly(department, total_amount, category)
    
    # 4. Log Decision and Ingest
    decision_id = await log_ai_decision(
        model_name="expense-ocr-v1",
        model_version="1.0.0",
        module="expense",
        input_data={"merchant": merchant, "items": len(items)},
        output={"category": category, "amount": total_amount},
        confidence=confidence,
        explanation=f"Detected merchant {merchant}, categorized as {category}"
    )
    
    expense_id = uuid4()
    expense_record = {
        "id": str(expense_id),
        "department": department,
        "amount": total_amount,
        "category": category,
        "subcategory": subcategory,
        "description": f"Receipt from {merchant}",
        "merchant": merchant,
        "items": items,
        "receipt_date": date_str,
        "confidence": confidence,
        "anomaly_score": anomaly_score,
        "is_anomaly": is_anomaly,
        "raw_text": raw_text[:2000],
        "decision_id": str(decision_id),
        "created_at": datetime.utcnow().isoformat()
    }
    
    supabase.table("expenses").insert(expense_record).execute()
    return {"success": True, "expense": expense_record}


async def ingest_expense(
    department: str,
    amount: float,
    description: str,
    timestamp: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Ingest and categorize an expense.
    """
    expense_id = uuid4()
    
    # Categorize expense
    category, subcategory, confidence = await categorize_expense(description)
    
    # Detect anomaly
    anomaly_score, is_anomaly = await detect_anomaly(department, amount, category)
    
    # Log AI decision
    decision_id = await log_ai_decision(
        model_name="expense-cat-v1",
        model_version="1.0.0",
        module="expense",
        input_data={"department": department, "amount": amount, "description": description[:200]},
        output={"category": category, "anomaly_score": anomaly_score, "is_anomaly": is_anomaly},
        confidence=confidence,
        explanation=f"Categorized as {category}, anomaly score: {anomaly_score:.2f}"
    )
    
    # Create expense record
    expense_record = {
        "id": str(expense_id),
        "department": department,
        "amount": amount,
        "category": category,
        "subcategory": subcategory,
        "description": description,
        "confidence": confidence,
        "anomaly_score": anomaly_score,
        "is_anomaly": is_anomaly,
        "decision_id": str(decision_id),
        "created_at": (timestamp or datetime.utcnow()).isoformat()
    }
    
    supabase.table("expenses").insert(expense_record).execute()
    
    return expense_record


async def categorize_expense(description: str) -> tuple[str, Optional[str], float]:
    """
    Categorize expense based on description.
    Returns (category, subcategory, confidence)
    """
    description_lower = description.lower()
    
    best_category = "other"
    best_subcategory = None
    best_score = 0
    
    for category, keywords in EXPENSE_CATEGORIES.items():
        for keyword in keywords:
            if keyword in description_lower:
                score = len(keyword) / len(description)
                if score > best_score:
                    best_score = score
                    best_category = category
                    best_subcategory = keyword
    
    confidence = min(0.6 + best_score * 2, 0.95)
    return best_category, best_subcategory, confidence


async def detect_anomaly(
    department: str,
    amount: float,
    category: str
) -> tuple[float, bool]:
    """
    Detect if expense is anomalous based on historical patterns.
    Returns (anomaly_score, is_anomaly)
    """
    # Get historical expenses for department
    history = supabase.table("expenses").select("amount, category").eq(
        "department", department
    ).limit(100).execute()
    
    if not history.data or len(history.data) < 5:
        # Not enough history
        return 0.0, False
    
    # Calculate statistics
    amounts = [e["amount"] for e in history.data]
    mean_amount = sum(amounts) / len(amounts)
    variance = sum((a - mean_amount) ** 2 for a in amounts) / len(amounts)
    std_dev = variance ** 0.5 if variance > 0 else 1
    
    # Calculate z-score
    z_score = abs(amount - mean_amount) / max(std_dev, 1)
    
    # Convert to 0-1 score
    anomaly_score = min(z_score / 3, 1.0)
    
    # Flag as anomaly if z-score > 2
    is_anomaly = z_score > 2
    
    return anomaly_score, is_anomaly


async def generate_monthly_summary(
    department: str,
    year: int,
    month: int
) -> Dict[str, Any]:
    """
    Generate monthly expense summary for citizen transparency.
    """
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    # Get expenses for the period
    expenses = supabase.table("expenses").select("*").eq(
        "department", department
    ).gte("created_at", start_date.isoformat()).lt(
        "created_at", end_date.isoformat()
    ).execute()
    
    if not expenses.data:
        return {
            "department": department,
            "period": f"{year}-{month:02d}",
            "total_amount": 0,
            "by_category": {},
            "anomaly_count": 0
        }
    
    # Aggregate by category
    by_category = defaultdict(float)
    total_amount = 0
    anomaly_count = 0
    
    for expense in expenses.data:
        category = expense.get("category", "other")
        amount = expense.get("amount", 0)
        by_category[category] += amount
        total_amount += amount
        if expense.get("is_anomaly"):
            anomaly_count += 1
    
    # Create summary record
    summary_id = uuid4()
    summary_record = {
        "id": str(summary_id),
        "department": department,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "total_amount": total_amount,
        "by_category": dict(by_category),
        "anomaly_count": anomaly_count,
        "created_at": datetime.utcnow().isoformat()
    }
    
    supabase.table("expense_summaries").insert(summary_record).execute()
    
    return {
        "department": department,
        "period": f"{year}-{month:02d}",
        "total_amount": total_amount,
        "by_category": dict(by_category),
        "anomaly_count": anomaly_count,
        "expense_count": len(expenses.data)
    }


async def get_citizen_transparency_view(
    department: Optional[str] = None,
    year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get aggregated expense view for citizen transparency portal.
    """
    year = year or date.today().year
    
    query = supabase.table("expense_summaries").select("*")
    
    if department:
        query = query.eq("department", department)
    
    # Get current year summaries
    start_of_year = date(year, 1, 1).isoformat()
    query = query.gte("period_start", start_of_year)
    
    summaries = query.execute()
    
    if not summaries.data:
        return {
            "year": year,
            "total_spending": 0,
            "by_department": {},
            "by_category": {}
        }
    
    # Aggregate
    by_department = defaultdict(float)
    by_category = defaultdict(float)
    total_spending = 0
    
    for summary in summaries.data:
        dept = summary.get("department", "other")
        by_department[dept] += summary.get("total_amount", 0)
        total_spending += summary.get("total_amount", 0)
        
        for cat, amount in summary.get("by_category", {}).items():
            by_category[cat] += amount
    
    return {
        "year": year,
        "total_spending": total_spending,
        "by_department": dict(by_department),
        "by_category": dict(by_category),
        "summary_count": len(summaries.data)
    }


async def list_anomalies(department: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """List flagged anomalous expenses"""
    query = supabase.table("expenses").select("*").eq("is_anomaly", True)
    
    if department:
        query = query.eq("department", department)
    
    results = query.order("created_at", desc=True).limit(limit).execute()
    return results.data if results.data else []
