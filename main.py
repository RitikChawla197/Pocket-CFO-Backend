import os
import json
import httpx
import sqlite3
import hashlib
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(db_url)
    else:
        return sqlite3.connect("cfo_dashboard.db")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_financial_data (
                user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_financial_data (
                user_id INTEGER PRIMARY KEY,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
    conn.commit()
    conn.close()

app = FastAPI(title="Personal CFO AI Insights API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_db_init():
    try:
        init_db()
    except Exception as e:
        print(f"Startup DB init log: {e}")

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class SaveUserDataRequest(BaseModel):
    user_id: int
    data: Dict[str, Any]

EMPTY_USER_FINANCIAL_DATA = {
    "incomeItems": [],
    "expenseItems": [],
    "assetItems": [],
    "liabilityItems": [],
    "snapshots": [],
    "aiInsight": None
}

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Personal CFO AI Backend Endpoint"}

@app.post("/api/auth/register")
def register_user(req: RegisterRequest):
    email = req.email.strip().lower()
    name = req.name.strip()
    if not email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    else:
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))

    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="User with this email already exists")

    pw_hash = hash_password(req.password)
    now = datetime.now().isoformat()

    if DATABASE_URL:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
            (name, email, pw_hash, now)
        )
        user_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO user_financial_data (user_id, data_json, updated_at) VALUES (%s, %s, %s)",
            (user_id, json.dumps(EMPTY_USER_FINANCIAL_DATA), now)
        )
    else:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email, pw_hash, now)
        )
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO user_financial_data (user_id, data_json, updated_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(EMPTY_USER_FINANCIAL_DATA), now)
        )

    conn.commit()
    conn.close()

    return {
        "user": {"id": user_id, "name": name, "email": email},
        "token": f"token_{user_id}_{hash_password(email)[:8]}",
        "data": EMPTY_USER_FINANCIAL_DATA
    }

@app.post("/api/auth/login")
def login_user(req: LoginRequest):
    email = req.email.strip().lower()
    pw_hash = hash_password(req.password)

    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("SELECT id, name, email, password_hash FROM users WHERE email = %s", (email,))
    else:
        cursor.execute("SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,))

    row = cursor.fetchone()
    if not row or row[3] != pw_hash:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id, name, user_email, _ = row
    if DATABASE_URL:
        cursor.execute("SELECT data_json FROM user_financial_data WHERE user_id = %s", (user_id,))
    else:
        cursor.execute("SELECT data_json FROM user_financial_data WHERE user_id = ?", (user_id,))

    data_row = cursor.fetchone()
    user_data = json.loads(data_row[0]) if data_row else EMPTY_USER_FINANCIAL_DATA
    conn.close()

    return {
        "user": {"id": user_id, "name": name, "email": user_email},
        "token": f"token_{user_id}_{hash_password(user_email)[:8]}",
        "data": user_data
    }

@app.get("/api/user/{user_id}/data")
def get_user_data(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("SELECT data_json FROM user_financial_data WHERE user_id = %s", (user_id,))
    else:
        cursor.execute("SELECT data_json FROM user_financial_data WHERE user_id = ?", (user_id,))

    row = cursor.fetchone()
    conn.close()
    if not row:
        return EMPTY_USER_FINANCIAL_DATA
    return json.loads(row[0])

@app.post("/api/user/data")
def save_user_data(req: SaveUserDataRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    if DATABASE_URL:
        cursor.execute("""
            INSERT INTO user_financial_data (user_id, data_json, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET data_json=EXCLUDED.data_json, updated_at=EXCLUDED.updated_at
        """, (req.user_id, json.dumps(req.data), now))
    else:
        cursor.execute("""
            INSERT INTO user_financial_data (user_id, data_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at
        """, (req.user_id, json.dumps(req.data), now))

    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Financial data saved to database"}

class SnapshotRequest(BaseModel):
    net_worth: float
    monthly_income: float
    monthly_expenses: float
    monthly_surplus: float
    savings_rate: float
    burn_rate: float
    emergency_runway_months: float
    dti_ratio: float
    wealth_health_score: float
    liquid_cash: float
    lifestyle_expenses: float
    investment_expenses: float
    essential_expenses: float
    total_assets: float
    total_liabilities: float
    red_flags: List[str] = []
    income_items: List[Dict[str, Any]] = []
    expense_items: List[Dict[str, Any]] = []
    asset_items: List[Dict[str, Any]] = []
    liability_items: List[Dict[str, Any]] = []
    trend_history: Optional[List[Dict[str, Any]]] = None
    provider: Optional[str] = "gemini"
    api_key: Optional[str] = None

class CFOInsightResponse(BaseModel):
    verdict: str
    summary: str
    recommendations: List[str]

def generate_heuristic_cfo_insight(data: SnapshotRequest) -> Dict[str, Any]:
    verdict = "WEALTH_BUILDING"
    if data.burn_rate > 85 or data.monthly_surplus <= 0 or data.emergency_runway_months < 1.5:
        verdict = "SALARY_ROTATING"
    elif data.lifestyle_expenses > data.investment_expenses or data.dti_ratio > 40 or (data.burn_rate > 65 and data.savings_rate < 25):
        verdict = "WEALTH_LEAKING"
    elif data.savings_rate >= 30 and data.emergency_runway_months >= 3 and data.dti_ratio <= 35:
        verdict = "WEALTH_BUILDING"

    inc_k = round(data.monthly_income / 1000, 1)
    exp_k = round(data.monthly_expenses / 1000, 1)
    sur_k = round(data.monthly_surplus / 1000, 1)
    nw_l = round(data.net_worth / 100000, 2)

    if verdict == "WEALTH_LEAKING":
        summary = f"Bhai, monthly income ₹{inc_k:.1f}k mast hai, lekin saara paisa lifestyle inflation aur leaks me ja raha hai! ₹{exp_k:.1f}k kharch ho raha hai jisse surplus bas ₹{sur_k:.1f}k bachta hai."
        recommendations = [
            f"Lifestyle expenses ko immediately cap karo — filhaal ₹{round(data.lifestyle_expenses/1000,1)}k kharch ho raha hai.",
            f"Monthly investment boost karo taaki investment spending lifestyle spending se aage nikal sake.",
            f"High-interest credit/personal loans pay off karke DTI ko below 35% lao."
        ]
    elif verdict == "SALARY_ROTATING":
        summary = f"Alert boss! Tera burn rate {data.burn_rate:.1f}% hai aur surplus bas ₹{sur_k:.1f}k hai — matlab salary aati hai aur seedha rotate ho kar chali jaati hai!"
        recommendations = [
            f"Non-essential discretionary expenses par turant 30-day freeze lagao.",
            f"Monthly surplus ko kam se kam 20% tak push karo.",
            f"Emergency liquid cash baseline ₹{round(data.essential_expenses*3/1000,1)}k create karo ASAP."
        ]
    else:
        summary = f"Shabaash! Teri financial direction solid hai — Savings rate {data.savings_rate:.1f}% hai aur net worth ₹{nw_l:.2f} Lakhs hit ho rhi hai."
        recommendations = [
            f"SIP monthly allocation 10-15% step-up karo har salary hike ke sath.",
            f"High-yield equity mutual funds aur asset diversification review karo har quarter."
        ]

    return {
        "verdict": verdict,
        "summary": summary,
        "recommendations": recommendations
    }

@app.post("/api/ai/insights", response_model=CFOInsightResponse)
async def get_ai_insights(snapshot: SnapshotRequest):
    prompt_text = f"""
You are a sharp, no-nonsense Personal CFO & Financial Coach for Indian professionals.
Analyze the following financial snapshot:
- Net Worth: ₹{snapshot.net_worth:,.0f}
- Monthly Income: ₹{snapshot.monthly_income:,.0f}
- Monthly Expenses: ₹{snapshot.monthly_expenses:,.0f}
- Surplus: ₹{snapshot.monthly_surplus:,.0f}
- Savings Rate: {snapshot.savings_rate:.1f}%
- Burn Rate: {snapshot.burn_rate:.1f}%
- Emergency Runway: {snapshot.emergency_runway_months:.1f} months
- Debt-to-Income (DTI): {snapshot.dti_ratio:.1f}%
- Wealth Health Score: {snapshot.wealth_health_score:.0f}/100
- Liquid Cash: ₹{snapshot.liquid_cash:,.0f}
- Lifestyle Expenses: ₹{snapshot.lifestyle_expenses:,.0f}
- Investment Expenses: ₹{snapshot.investment_expenses:,.0f}
- Red Flags: {json.dumps(snapshot.red_flags)}

Provide strict JSON output with:
1. "verdict": strictly one of "WEALTH_BUILDING", "WEALTH_LEAKING", "SALARY_ROTATING".
2. "summary": 2-3 punchy, engaging Hinglish sentences in an Indian financial mentor tone (friendly, sharp, direct).
3. "recommendations": array of 3 to 5 crisp imperative action items in Hinglish (each strictly under 20 words).

Respond ONLY with valid JSON inside a ```json block or raw JSON object.
"""
    selected_provider = (snapshot.provider or "gemini").lower()
    custom_key = snapshot.api_key.strip() if snapshot.api_key else None

    if not custom_key:
        raise HTTPException(
            status_code=400,
            detail="API Key Required: Every user must provide their own Google Gemini or Anthropic Claude API key."
        )

    # Handle Anthropic Claude API
    if selected_provider == "anthropic" or custom_key.startswith("sk-ant-"):
        try:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": custom_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt_text}]
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                res_data = resp.json()
                if resp.status_code == 200:
                    raw_text = res_data["content"][0]["text"]
                    cleaned_text = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    parsed = json.loads(cleaned_text)
                    return CFOInsightResponse(
                        verdict=parsed.get("verdict", "WEALTH_BUILDING"),
                        summary=parsed.get("summary", ""),
                        recommendations=parsed.get("recommendations", [])
                    )
                else:
                    err_msg = res_data.get("error", {}).get("message", f"Anthropic HTTP {resp.status_code}")
                    print(f"Anthropic API Error ({resp.status_code}): {err_msg}")
                    raise HTTPException(
                        status_code=resp.status_code if resp.status_code in [400, 401, 403, 429] else 400,
                        detail=f"Anthropic API Error: {err_msg}"
                    )
        except HTTPException:
            raise
        except Exception as e:
            print(f"Anthropic Exception: {e}")
            raise HTTPException(status_code=500, detail=f"Anthropic API request failed: {str(e)}")

    # Handle Google Gemini API
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={custom_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json"
            }
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 404:
                url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={custom_key}"
                resp = await client.post(url, json=payload)

            res_data = resp.json()
            if resp.status_code == 200:
                raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                cleaned_text = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = json.loads(cleaned_text)
                return CFOInsightResponse(
                    verdict=parsed.get("verdict", "WEALTH_BUILDING"),
                    summary=parsed.get("summary", ""),
                    recommendations=parsed.get("recommendations", [])
                )
            else:
                err_msg = res_data.get("error", {}).get("message", f"Gemini HTTP {resp.status_code}")
                print(f"Gemini API Error ({resp.status_code}): {err_msg}")
                raise HTTPException(
                    status_code=resp.status_code if resp.status_code in [400, 401, 403, 429] else 400,
                    detail=f"Gemini API Error: {err_msg}"
                )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Gemini Exception: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini API request failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
