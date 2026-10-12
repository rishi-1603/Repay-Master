#!/usr/bin/env python3
"""Day-10 local API workflow for RepayMaster, using the built FastAPI app."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8011"
out = Path("/home/user/evidence/RepayMaster/local-api-e2e.txt")
out.parent.mkdir(parents=True, exist_ok=True)
lines=[]
def log(text): print(text); lines.append(text)

def check(label, response, expected):
    ok=response.status_code == expected
    log(f"{'PASS' if ok else 'FAIL'} {label}: HTTP {response.status_code} (expected {expected}) body={response.text[:500]}")
    if not ok: raise SystemExit(1)

with httpx.Client(timeout=30) as c:
    r=c.get(BASE+"/health"); check("health",r,200)
    payload={"loan_amount":250000,"interest_rate":8.5,"monthly_income":15000,"monthly_expenses":6000,"start_date":"2026-01-01"}
    r=c.post(BASE+"/loan/calculate",json=payload); check("calculate standard loan",r,200)
    data=r.json(); log("calculation options="+json.dumps(data["options"],sort_keys=True))
    assert data["options"]["Recommended"]["monthly_payment"] == 3598.03
    r=c.post(BASE+"/loan/prepayment",json={**payload,"months":60,"extra_monthly":5000}); check("prepayment simulation",r,200)
    log("prepayment="+r.text)
    assert r.json()["new_months"] == 28
    r=c.post(BASE+"/risk/predict",json={"loan_amount":250000,"interest_rate":8.5,"monthly_income":15000,"monthly_expenses":6000,"monthly_payment":5129.13}); check("risk prediction",r,200)
    log("risk="+r.text[:800]); assert len(r.json()["top_factors"]) == 5
    r=c.post(BASE+"/loan/calculate",content=b'{"loan_amount": Infinity, "interest_rate": 8.5, "monthly_income": 15000, "monthly_expenses": 6000}',headers={"Content-Type":"application/json"}); check("non-finite input rejected",r,422)
    r=c.post(BASE+"/loan/calculate",json={**payload,"interest_rate":-1}); check("negative rate rejected",r,422)
    stamp=str(int(time.time())); user={"username":"qa-"+stamp,"password":"QA-password-123"}
    r=c.post(BASE+"/auth/register",json=user); check("register",r,201)
    r=c.post(BASE+"/auth/login",json=user); check("login",r,200); token=r.json()["access_token"]
    h={"Authorization":"Bearer "+token}
    r=c.post(BASE+"/history",json={"label":"QA standard loan","params":payload},headers=h); check("save history",r,201)
    r=c.get(BASE+"/history",headers=h); check("list history",r,200); log("history="+r.text)
log("PASS local RepayMaster API workflow")
out.write_text("\n".join(lines)+"\n")
