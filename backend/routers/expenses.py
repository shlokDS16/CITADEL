"""
Expenses Router - Expense Categorization API endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from datetime import date

from services.expense_service import (
    ingest_expense, generate_monthly_summary,
    get_citizen_transparency_view, list_anomalies,
    process_receipt
)

router = APIRouter()

@router.post("/upload")
async def upload_receipt(file: UploadFile = File(...)):
    """Upload and process a receipt image"""
    try:
        content = await file.read()
        result = await process_receipt(content)
        if "error" in result: # Handle error from service
             raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ExpenseCreate(BaseModel):
    department: str
    amount: float
    description: str


@router.post("/")
async def add_expense(expense: ExpenseCreate):
    """Add and categorize an expense"""
    try:
        result = await ingest_expense(
            department=expense.department,
            amount=expense.amount,
            description=expense.description
        )
        return {"success": True, "expense": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{department}")
async def get_summary(
    department: str,
    year: Optional[int] = None,
    month: Optional[int] = None
):
    """Get monthly expense summary"""
    today = date.today()
    year = year or today.year
    month = month or today.month
    
    summary = await generate_monthly_summary(department, year, month)
    return summary


@router.get("/transparency")
async def citizen_transparency(
    department: Optional[str] = None,
    year: Optional[int] = None
):
    """Get citizen transparency view of government spending"""
    view = await get_citizen_transparency_view(department, year)
    return view


@router.get("/anomalies")
async def get_anomalies(department: Optional[str] = None, limit: int = 50):
    """List flagged anomalous expenses"""
    anomalies = await list_anomalies(department, limit)
    return {"anomalies": anomalies}
