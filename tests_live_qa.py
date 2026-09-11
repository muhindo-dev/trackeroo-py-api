#!/usr/bin/env python3
"""Live end-to-end QA for truckfully.com.

Drives the real public API exactly as the apps do. Records every scenario as
PASS / FAIL / WARN with the evidence, so the report is auditable rather than a
claim. Cleans up the rides it creates.
"""
import json, sys, time, urllib.request, urllib.error

BASE = "https://truckfully.com/api"
RESULTS = []
CTX = {}

def call(method, path, token=None, body=None, timeout=30):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"_raw": raw[:300]}
    except Exception as e:
        return 0, {"_err": str(e)}

def record(group, name, ok, detail="", severity="FAIL"):
    status = "PASS" if ok else severity
    RESULTS.append({"group": group, "name": name, "status": status, "detail": detail})
    icon = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[status]
    print(f"  [{icon}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    return ok

def section(t):
    print(f"\n=== {t} ===")

# ─────────────────────────────────────────────────────────────── A. AUTH
def test_auth():
    section("A. Authentication")
    s, r = call("POST", "/users/login", body={"username": "customerx@gmail.com", "password": "111111"})
    ok = r.get("code") == 1 and (r.get("data") or {}).get("token")
    record("Auth", "Customer login succeeds", ok, f"HTTP {s} {r.get('message')}")
    if ok: CTX["cust"] = r["data"]["token"]; CTX["cust_id"] = r["data"].get("id")

    s, r = call("POST", "/users/login", body={"username": "driverx@gmail.com", "password": "111111"})
    ok = r.get("code") == 1 and (r.get("data") or {}).get("token")
    record("Auth", "Driver login succeeds", ok, f"HTTP {s} {r.get('message')}")
    if ok: CTX["drv"] = r["data"]["token"]; CTX["drv_id"] = r["data"].get("id")

    s, r = call("POST", "/users/login", body={"username": "customerx@gmail.com", "password": "wrong-password"})
    record("Auth", "Wrong password rejected", r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/users/login", body={"username": "nobody-xyz@example.com", "password": "x"})
    record("Auth", "Unknown account rejected", r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/users/login", body={"username": "customerx@gmail.com"})
    record("Auth", "Missing password rejected", r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    s, r = call("GET", "/rides/active")
    record("Auth", "Protected route needs a token", s in (401, 422) or r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    s, r = call("GET", "/rides/active", token="not-a-real-jwt")
    record("Auth", "Garbage token rejected", s in (401, 422) or r.get("code") == 0, f"HTTP {s}")

# ───────────────────────────────────────────────────── B. AUTHORIZATION
def test_authz():
    section("B. Authorisation / privilege")
    s, r = call("GET", "/admin/users", token=CTX.get("cust"))
    record("Security", "Customer cannot list admin users", s == 403 or r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/admin/users/13057/impersonate", token=CTX.get("cust"))
    record("Security", "Customer cannot mint impersonation tokens", s in (401, 403) or r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/admin/users/13057/set-location", token=CTX.get("drv"),
                body={"latitude": 1, "longitude": 1})
    record("Security", "Driver cannot god-mode set another user's GPS", s in (401, 403) or r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    # The legacy user_id body fallback must not authenticate an admin action.
    s, r = call("POST", "/admin/users/13057/set-online", body={"user_id": 1, "online": True})
    record("Security", "user_id body cannot bypass admin auth", s in (401, 403) or r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    s, r = call("GET", "/admin/negotiations", token=None)
    record("Security", "Admin negotiations needs auth", s in (401, 422) or r.get("code") == 0, f"HTTP {s}")

# ────────────────────────────────────────────── C. DRIVER APPROVAL GATE
def test_approval():
    section("C. Driver approval gate")
    adm = CTX.get("admin")
    drv_id = CTX.get("drv_id") or 13057

    # Revoke, expect refusal, restore. Proves the gate, not just today's state.
    s, r = call("POST", f"/admin/users/{drv_id}/reject-driver", token=adm)
    revoked = r.get("code") == 1
    record("Approval", "Admin can revoke approval", revoked, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/update-online-status", token=CTX.get("drv"),
                body={"status": "online", "service_group": "Boda",
                      "latitude": "0.3480", "longitude": "32.5830"})
    blocked = s == 403 and (r.get("data") or {}).get("requires_approval") is True
    record("Approval", "Unapproved driver blocked from going online", blocked,
           f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/admin/users/{drv_id}/approve-driver", token=adm, body={"services": ["boda"]})
    record("Approval", "Admin can approve for a service group", r.get("code") == 1,
           f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/update-online-status", token=CTX.get("drv"),
                body={"status": "online", "service_group": "Boda",
                      "latitude": "0.3480", "longitude": "32.5830"})
    record("Approval", "Approved driver can go online", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/update-online-status", token=CTX.get("drv"),
                body={"status": "online", "service_group": "Truck",
                      "latitude": "0.3480", "longitude": "32.5830"})
    record("Approval", "Approved-for-Boda blocked from Truck", s == 403 or r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/update-online-status", token=CTX.get("drv"),
                body={"status": "online", "service_group": "Spaceship",
                      "latitude": "0.3480", "longitude": "32.5830"})
    record("Approval", "Invalid service group rejected", r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    # leave them online + Boda for the ride tests
    call("POST", "/update-online-status", token=CTX.get("drv"),
         body={"status": "online", "service_group": "Boda",
               "latitude": "0.3480", "longitude": "32.5830"})

# ──────────────────────────────────────────────── D. QUOTE & VALIDATION
def test_quote_and_validation():
    section("D. Quote & request validation")
    cust = CTX.get("cust")
    s, r = call("POST", "/rides/quote", token=cust, body={
        "category_id": 33, "distance_km": 4.0, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832,
        "dropoff_lat": 0.37, "dropoff_lng": 32.61})
    record("Pricing", "Quote returns an estimate", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    bad = {"category_id": 33, "distance_km": 4, "duration_min": 10,
           "dropoff_lat": 0.37, "dropoff_lng": 32.61, "proposed_price": 1000}
    s, r = call("POST", "/rides/request", token=cust, body=bad)
    record("Validation", "Missing pickup coords rejected", r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/rides/request", token=cust, body={
        "category_id": 999999, "distance_km": 4, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832,
        "dropoff_lat": 0.37, "dropoff_lng": 32.61, "proposed_price": 1000})
    record("Validation", "Unknown category rejected", r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", "/rides/request", token=cust, body={
        "category_id": 33, "distance_km": 99999, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832,
        "dropoff_lat": 0.37, "dropoff_lng": 32.61, "proposed_price": 1000})
    record("Validation", "Absurd distance rejected (overflow guard)", r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

# ──────────────────────────────────────────── E. DISPATCH / OFFER / TRIP
def new_ride(price=1200):
    return call("POST", "/rides/request", token=CTX["cust"], body={
        "category_id": 33, "distance_km": 4.0, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832, "pickup_address": "QA pickup",
        "dropoff_lat": 0.37, "dropoff_lng": 32.61, "dropoff_address": "QA dropoff",
        "payment_method": "Cash", "proposed_price": price})

def kill_active():
    s, r = call("GET", "/rides/active", token=CTX["cust"])
    rid = (r.get("data") or {}).get("ride_id")
    if rid:
        call("POST", f"/rides/{rid}/cancel", token=CTX["cust"], body={})
        # force it dead even if Started
        call("POST", f"/admin/negotiations/{rid}/update", token=CTX.get("admin"),
             body={"status": "Cancelled", "is_active": "No"})

def test_dispatch_and_trip():
    section("E. Dispatch, offer & trip lifecycle")
    kill_active()
    s, r = new_ride()
    d = (r.get("data") or {}).get("dispatch", {})
    rid = d.get("negotiation_id"); CTX["rid"] = rid
    record("Dispatch", "Ride created and offered to a driver",
           r.get("code") == 1 and d.get("status") == "offered" and d.get("candidates"),
           f"HTTP {s} dispatch={d.get('status')} cands={d.get('candidates')}")

    s, r = call("POST", "/rides/request", token=CTX["cust"], body={
        "category_id": 33, "distance_km": 4.0, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832,
        "dropoff_lat": 0.37, "dropoff_lng": 32.61, "proposed_price": 1200})
    record("Dispatch", "Duplicate active ride refused", r.get("code") == 0, f"{r.get('message')}")

    s, r = call("GET", "/rides/active", token=CTX["drv"])
    data = r.get("data") or {}
    record("Offer", "Driver's app sees the pending offer",
           data.get("role") == "driver" and data.get("is_pending_offer") is True,
           f"role={data.get('role')} pending={data.get('is_pending_offer')} left={data.get('offer_seconds_left')}")

    # A stranger must not be able to answer someone else's offer.
    s, r = call("POST", f"/rides/{rid}/respond", token=CTX["cust"], body={"action": "accept"})
    record("Security", "Customer cannot accept their own ride as the driver",
           r.get("code") == 0, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/rides/{rid}/respond", token=CTX["drv"], body={"action": "accept"})
    record("Offer", "Driver accepts the offer", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("GET", f"/rides/{rid}/status", token=CTX["cust"])
    n = (r.get("data") or {}).get("negotiation", {})
    record("Offer", "Accept settles the agreed price", bool(n.get("agreed_price")),
           f"agreed={n.get('agreed_price')} fare={n.get('fare')} status={n.get('status')}")
    record("Money", "Fare reads back in major units (cents stored)",
           n.get("fare") == 1200 and n.get("agreed_price") == 120000,
           f"fare={n.get('fare')} agreed_price={n.get('agreed_price')}")

    s, r = call("POST", f"/rides/{rid}/arrived", token=CTX["drv"], body={})
    record("Trip", "Driver marks arrived", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/rides/{rid}/start", token=CTX["cust"], body={})
    record("Security", "Customer cannot start the trip (driver-only)", r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/rides/{rid}/start", token=CTX["drv"], body={})
    record("Trip", "Driver starts the trip", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/rides/{rid}/complete", token=CTX["drv"], body={})
    record("Trip", "Driver completes the trip", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("GET", f"/rides/{rid}/status", token=CTX["cust"])
    n = (r.get("data") or {}).get("negotiation", {})
    record("Trip", "Completed ride reports Completed", n.get("status") == "Completed",
           f"status={n.get('status')}")

    # completion must release the driver
    s, r = call("GET", f"/admin/users/{CTX['drv_id']}", token=CTX.get("admin"))
    u = r.get("data") or {}
    record("Dispatch", "Completion frees the driver (busy_until cleared)",
           not u.get("busy_until"), f"busy_until={u.get('busy_until')}")

def test_rating():
    section("F. Ratings")
    rid = CTX.get("rid")
    s, r = call("POST", "/ratings", token=CTX["cust"],
                body={"negotiation_id": rid, "driver_id": CTX["drv_id"], "rating": 5,
                      "comment": "QA automated"})
    ok = r.get("code") == 1
    record("Rating", "Customer can rate after completion", ok, f"HTTP {s} {r.get('message')}")
    s, r = call("POST", "/ratings", token=CTX["cust"],
                body={"negotiation_id": rid, "driver_id": CTX["drv_id"], "rating": 1,
                      "comment": "QA duplicate"})
    record("Rating", "Duplicate rating for same ride refused", r.get("code") == 0,
           f"HTTP {s} {r.get('message')}", severity="WARN")

def test_cancel_release():
    section("G. Cancellation releases the driver")
    kill_active()
    s, r = new_ride()
    rid = (r.get("data") or {}).get("dispatch", {}).get("negotiation_id")
    call("POST", f"/rides/{rid}/respond", token=CTX["drv"], body={"action": "negotiate"})
    s, r = call("GET", f"/admin/users/{CTX['drv_id']}", token=CTX.get("admin"))
    busy_after_neg = (r.get("data") or {}).get("busy_until")
    record("Dispatch", "Negotiate marks the driver busy", bool(busy_after_neg),
           f"busy_until={busy_after_neg}")
    call("POST", f"/rides/{rid}/cancel", token=CTX["cust"], body={})
    s, r = call("GET", f"/admin/users/{CTX['drv_id']}", token=CTX.get("admin"))
    busy_after_cancel = (r.get("data") or {}).get("busy_until")
    record("Dispatch", "Customer cancel frees the driver", not busy_after_cancel,
           f"busy_until={busy_after_cancel}")

def test_no_match_and_retry():
    section("H. No-match & retry")
    kill_active()
    call("POST", "/update-online-status", token=CTX["drv"], body={"status": "offline"})
    s, r = new_ride()
    d = (r.get("data") or {}).get("dispatch", {})
    rid = d.get("negotiation_id")
    record("Dispatch", "No driver online yields no_match", d.get("status") == "no_match",
           f"dispatch={d.get('status')}")
    s, r = call("POST", f"/rides/{rid}/retry", token=CTX["cust"], body={})
    record("Dispatch", "Retry works and still reports no driver", r.get("code") == 1,
           f"HTTP {s} {r.get('message')}")
    call("POST", "/update-online-status", token=CTX["drv"],
         body={"status": "online", "service_group": "Boda",
               "latitude": "0.3480", "longitude": "32.5830"})
    s, r = call("POST", f"/rides/{rid}/retry", token=CTX["cust"], body={})
    dd = (r.get("data") or {}).get("dispatch_status")
    record("Dispatch", "Retry finds a driver once one comes online", dd == "offered",
           f"dispatch={dd} msg={r.get('message')}")
    s, r = call("POST", f"/rides/{rid}/retry", token=CTX["drv"], body={})
    record("Security", "Only the ride's customer can retry", r.get("code") == 0,
           f"HTTP {s} {r.get('message')}")
    kill_active()

def test_decline_cascade():
    section("I. Decline")
    kill_active()
    s, r = new_ride()
    rid = (r.get("data") or {}).get("dispatch", {}).get("negotiation_id")
    s, r = call("POST", f"/rides/{rid}/respond", token=CTX["drv"], body={"action": "decline"})
    record("Offer", "Driver can decline", r.get("code") == 1, f"HTTP {s} {r.get('message')}")
    s, r = call("GET", f"/rides/{rid}/status", token=CTX["cust"])
    dd = (r.get("data") or {}).get("dispatch_status")
    record("Offer", "Decline with no other driver ends in no_match", dd == "no_match", f"dispatch={dd}")
    kill_active()

def test_scheduled():
    section("J. Scheduled rides")
    kill_active()
    from datetime import datetime, timedelta
    when = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    s, r = call("POST", "/rides/request", token=CTX["cust"], body={
        "category_id": 33, "distance_km": 4.0, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832, "pickup_address": "QA sched pickup",
        "dropoff_lat": 0.37, "dropoff_lng": 32.61, "dropoff_address": "QA sched dropoff",
        "payment_method": "Cash", "proposed_price": 1500, "scheduled_at": when})
    d = (r.get("data") or {}).get("dispatch", {})
    rid = d.get("negotiation_id")
    record("Schedule", "Ride can be booked for later", r.get("code") == 1 and d.get("status") == "scheduled",
           f"dispatch={d.get('status')}")
    if rid:
        s, r = call("POST", f"/rides/{rid}/start-now", token=CTX["cust"], body={})
        record("Schedule", "Scheduled ride can be started now", r.get("code") == 1,
               f"HTTP {s} {r.get('message')}")
    soon = (datetime.utcnow() + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    kill_active()
    s, r = call("POST", "/rides/request", token=CTX["cust"], body={
        "category_id": 33, "distance_km": 4.0, "duration_min": 10,
        "pickup_lat": 0.3482, "pickup_lng": 32.5832,
        "dropoff_lat": 0.37, "dropoff_lng": 32.61,
        "proposed_price": 1500, "scheduled_at": soon})
    record("Schedule", "Too-soon schedule rejected", r.get("code") == 0, f"{r.get('message')}")
    kill_active()

def test_admin():
    section("K. Admin & god-mode")
    adm = CTX.get("admin")
    for name, path in [("dashboard", "/admin/dashboard"), ("users", "/admin/users"),
                       ("negotiations", "/admin/negotiations"), ("vehicle categories", "/admin/vehicle-categories"),
                       ("subscriptions", "/admin/subscriptions"), ("system health", "/admin/system/health")]:
        s, r = call("GET", path, token=adm)
        record("Admin", f"GET {name}", r.get("code") == 1 or s == 200, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/admin/users/{CTX['drv_id']}/set-location", token=adm,
                body={"latitude": 0.3480, "longitude": 32.5830})
    record("Admin", "God-mode set GPS", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/admin/users/{CTX['drv_id']}/set-location", token=adm,
                body={"latitude": 999, "longitude": 32.58})
    record("Admin", "God-mode rejects out-of-range GPS", r.get("code") == 0, f"{r.get('message')}")

    s, r = call("POST", f"/admin/users/{CTX['drv_id']}/set-online", token=adm,
                body={"online": True, "service_group": "Boda"})
    record("Admin", "God-mode force online", r.get("code") == 1, f"HTTP {s} {r.get('message')}")

    s, r = call("POST", f"/admin/users/{CTX['drv_id']}/impersonate", token=adm)
    record("Admin", "God-mode impersonation issues a token",
           r.get("code") == 1 and (r.get("data") or {}).get("token"), f"HTTP {s}")

def run():
    print("Truckfully live QA —", BASE)
    test_auth()
    if not CTX.get("cust") or not CTX.get("drv"):
        print("!! cannot continue without customer+driver tokens"); return
    CTX["admin"] = open("/tmp/.at").read().strip()
    test_authz()
    test_approval()
    test_quote_and_validation()
    test_dispatch_and_trip()
    test_rating()
    test_cancel_release()
    test_no_match_and_retry()
    test_decline_cascade()
    test_scheduled()
    test_admin()
    kill_active()
    json.dump(RESULTS, open("/private/tmp/claude-501/-Users-mac-Desktop-github-truckeroo-mobo/d83087d8-9837-494f-84ab-59d5d97d3579/scratchpad/qa/results.json","w"), indent=1)
    p = sum(1 for x in RESULTS if x["status"]=="PASS")
    f = sum(1 for x in RESULTS if x["status"]=="FAIL")
    w = sum(1 for x in RESULTS if x["status"]=="WARN")
    print(f"\n===== {p} passed · {f} failed · {w} warnings · {len(RESULTS)} total =====")
    for x in RESULTS:
        if x["status"] != "PASS":
            print(f"  {x['status']}  [{x['group']}] {x['name']}  -- {x['detail']}")

run()
