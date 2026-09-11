# Truckfully — Live System QA Report

**Target:** `https://truckfully.com` (production)
**Method:** 58 scenarios driven against the real public API, using the same
endpoints and payloads the mobile apps send. No mocks, no test-only shortcuts —
a suite that avoided the real routes would pass while the app was broken.
**Result:** **58 / 58 passing** after one defect was found and fixed.

Harness: `scratchpad/qa/suite.py` (re-runnable).

---

## 1. Defect found and fixed

### PII leak — any logged-in user could dump the entire user table

| | |
|---|---|
| **Severity** | High — personal data exposure |
| **Endpoints** | `GET /api/admin/users`, `GET /api/admin/users/<id>` |
| **Cause** | Guarded with `@jwt_required_with_user` (any authenticated user) instead of `@admin_required` |
| **Impact** | A plain customer token returned **397 accounts** with emails, phone numbers, user types and profile fields |
| **Status** | **Fixed and verified in production** |

Reproduction before the fix, using an ordinary customer account:

```
GET /api/admin/users   (Bearer = customerx@gmail.com)
→ HTTP 200, total: 397
  13070  drivery@gmail.com   +2346666666666  Driver
  13069  313416229@qq.com    +2560709955552  Customer
```

After:

```
GET /api/admin/users   (customer token) → HTTP 403 "Admin access required"
GET /api/admin/users   (admin token)    → HTTP 200, total: 397   (unchanged)
```

An audit of **every** `/api/admin/*` route confirmed these were the only two
carrying the wrong decorator.

---

## 2. Coverage

### A. Authentication — 7/7
Customer login · driver login · wrong password rejected · unknown account
rejected · missing password rejected · protected route requires a token ·
malformed token rejected.

### B. Authorisation — 5/5
Customer blocked from admin user list · customer cannot mint impersonation
tokens · driver cannot god-mode another user's GPS · **the legacy `user_id`
body parameter cannot bypass admin auth** · admin negotiations requires auth.

### C. Driver approval gate — 6/6
Tested by *revoking* approval and restoring it, so the gate itself is proven
rather than the current state:

- Admin can revoke approval
- Unapproved driver blocked from going online (403, `requires_approval: true`)
- Admin can approve for a named service group
- Approved driver can go online
- Driver approved for Boda is refused Truck
- Invalid service group rejected

### D. Quote & validation — 4/4
Quote returns an estimate · missing pickup coordinates rejected · unknown
category rejected · absurd distance rejected (the guard against the fare
overflow that previously produced HTTP 500s).

### E. Dispatch, offer & trip lifecycle — 12/12
Ride created and offered with a ranked candidate · duplicate active ride refused
· driver's app sees the pending offer with a countdown · **customer cannot
accept their own ride as the driver** · driver accepts · accept settles
`agreed_price` · fare reads back in major units while cents are stored
(`fare 1200` / `agreed_price 120000`) · arrived · **customer cannot start the
trip** · driver starts · driver completes · completion clears `busy_until`.

### F. Ratings — 2/2
Customer can rate after completion · duplicate rating for the same ride refused.

### G. Cancellation releases the driver — 2/2
Responding "negotiate" marks the driver busy · customer cancellation frees them.
This is the regression test for the defect where a driver stayed invisible to
dispatch for 90 minutes after a customer cancelled.

### H. No-match & retry — 4/4
No driver online yields `no_match` · retry works and still reports none · retry
finds a driver once one comes online · only the ride's own customer can retry.

### I. Decline — 2/2
Driver can decline · decline with no other candidate ends in `no_match`.

### J. Scheduled rides — 3/3
Ride can be booked for later (`dispatch: scheduled`) · a scheduled ride can be
started immediately · a too-soon schedule is rejected.

### K. Admin & god-mode — 10/10
Dashboard, users, negotiations, vehicle categories, subscriptions and system
health all respond · god-mode set GPS · out-of-range coordinates rejected ·
force online · impersonation issues a working token.

---

## 3. State after the run

The suite creates real rides, so the tables were cleared afterwards:

```
negotiations 0 · negotiation_records 0 · ride_dispatches 0 · driver_ratings 0
next ride id: 1000 · drivers left busy: 0
```

`negotiations.AUTO_INCREMENT` is held at 1000 because 45 historical wallet
transactions still reference `negotiation_id` 1–158; restarting at 1 would make
new rides collide with those references.

---

## 4. Notes and residual risk

- **`driverx@gmail.com` is approved for Boda.** It was approved during testing
  of the new gate. `drivery@gmail.com` and `safari1@gmail.com` remain unapproved
  and cannot go online until an admin approves them.
- **The legacy `user_id` auth fallback still exists** in `get_current_user()`.
  It can no longer reach admin endpoints (god-mode uses `admin_required_strict`,
  and the two leaking routes are fixed), but it remains a bypass for ordinary
  authenticated routes. Removing it needs a coordinated release because the
  mobile app still sends `user_id` alongside its Bearer token.
- **Payments are untested.** `payments` is empty and Flutterwave was not
  exercised; card/mobile-money flows need a separate pass against sandbox
  credentials.
- **Not covered here:** courier batches, trip bookings (the Truckfully
  scheduled-trip module), payout requests, and in-app calling. These are
  separate subsystems from the instant-ride engine tested above.
