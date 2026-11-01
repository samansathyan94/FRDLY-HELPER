import os, sys, tempfile, threading
os.environ.update(DB_BACKEND="sqlite", SQLITE_PATH=tempfile.mktemp(suffix=".db"), SECRET_KEY="t",
                  ADMIN_EMAIL="admin@t.io", ADMIN_PASSWORD="adminpass1")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as A

class S:
    cust, prov, prov2, admin, anon = (A.app.test_client() for _ in range(5)); ids = {}

def j(r): return r.get_json()
def reg(c, **k): return c.post("/api/register", json=k)
def login(c, e, p="password1"): return c.post("/api/login", json={"email": e, "password": p})
LOC = dict(lat=11.0168, lng=76.9558)   # Coimbatore

def test_register_login_and_validation():
    assert reg(S.cust, name="Cathy", email="c@t.io", password="password1", role="customer").status_code == 201
    assert reg(S.prov, name="Mech One", email="m1@t.io", password="password1", role="provider", category="Vehicle Mechanic").status_code == 201
    assert reg(S.prov2, name="Mech Two", email="m2@t.io", password="password1", role="provider", category="Vehicle Mechanic").status_code == 201
    assert reg(S.anon, name="Xx", email="c@t.io", password="password1", role="customer").status_code == 409
    assert reg(S.anon, name="x", email="bad", password="password1", role="customer").status_code == 400
    assert reg(S.anon, name="xx", email="z@t.io", password="short", role="customer").status_code == 400
    assert reg(S.anon, name="xx", email="z@t.io", password="password1", role="admin").status_code == 400
    assert login(S.anon, "c@t.io", "wrong").status_code == 401
    for c, e in ((S.cust, "c@t.io"), (S.prov, "m1@t.io"), (S.prov2, "m2@t.io")): assert login(c, e).status_code == 200
    assert login(S.admin, "admin@t.io", "adminpass1").status_code == 200
    S.ids["p1"], S.ids["p2"] = j(S.prov.get("/api/me"))["id"], j(S.prov2.get("/api/me"))["id"]
    assert j(S.cust.get("/api/me"))["name"] == "Cathy"

def test_authorization():
    assert S.anon.get("/api/bookings").status_code == 401
    assert S.cust.put("/api/provider/availability", json={"available": True}).status_code == 403
    assert S.prov.post("/api/bookings", json={}).status_code == 403
    assert S.cust.get("/api/admin/stats").status_code == 403
    assert S.prov.get("/api/admin/users").status_code == 403

def test_availability_and_discovery():
    assert j(S.cust.get("/api/providers?category=Vehicle%20Mechanic&lat=11.01&lng=76.95")) == []   # nobody online yet
    for c, off in ((S.prov, 0.01), (S.prov2, 0.2)):   # p2 is ~28km away
        assert c.put("/api/provider/availability", json={"available": True}).status_code == 200
        assert c.put("/api/provider/location", json={"lat": 11.0168 + off, "lng": 76.9558}).status_code == 200
    assert S.prov.put("/api/provider/location", json={"lat": 999, "lng": 1}).status_code == 400
    res = j(S.cust.get("/api/providers?category=Vehicle%20Mechanic&lat=11.0168&lng=76.9558"))
    assert [r["id"] for r in res][0] == S.ids["p1"] and res[0]["score"] > res[-1]["score"]

def test_invalid_request():
    assert S.cust.post("/api/bookings", json={"category": "Nope", "description": "engine dead", **LOC}).status_code == 400
    assert S.cust.post("/api/bookings", json={"category": "Plumber", "description": "x", **LOC}).status_code == 400
    assert S.cust.post("/api/bookings", json={"category": "Plumber", "description": "pipe burst", "lat": "abc", "lng": 1}).status_code == 400
    assert S.cust.post("/api/bookings", json={"category": "Plumber", "description": "pipe burst", **LOC}).status_code == 404  # none online

def test_full_workflow():
    ref = "ref-123"
    r = S.cust.post("/api/bookings", json={"category": "Vehicle Mechanic", "description": "Car will not start", "client_ref": ref, **LOC})
    assert r.status_code == 201; b = j(r); bid = b["id"]; seen = [b["status"]]
    assert b["provider_id"] == S.ids["p1"]                                                     # best-ranked provider
    assert S.cust.post("/api/bookings", json={"category": "Vehicle Mechanic", "description": "Car will not start", "client_ref": ref, **LOC}).status_code == 200  # duplicate -> same booking
    assert len(j(S.cust.get("/api/bookings"))) == 1
    assert S.prov2.post(f"/api/bookings/{bid}/action", json={"action": "accept"}).status_code == 404   # other provider can't touch it
    assert S.cust.post(f"/api/bookings/{bid}/action", json={"action": "accept"}).status_code == 409    # wrong role
    assert [x["id"] for x in j(S.prov.get("/api/bookings"))] == [bid]                                   # provider receives it
    # duplicate acceptance: concurrent accepts, exactly one wins
    out = []
    def go(): out.append(A.app.test_client())
    codes = []
    def acc():
        c = A.app.test_client(); login(c, "m1@t.io"); codes.append(c.post(f"/api/bookings/{bid}/action", json={"action": "accept"}).status_code)
    ts = [threading.Thread(target=acc) for _ in range(4)]; [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(codes).count(200) == 1 and all(c in (200, 409) for c in codes), codes
    seen.append(j(S.cust.get("/api/bookings"))[0]["status"]); assert seen[-1] == "accepted"
    assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": "arrived"}).status_code == 409   # skipping a step
    assert S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": 100}).status_code == 409       # estimate before arrival
    S.prov.put("/api/provider/location", json={"lat": 11.02, "lng": 76.96})
    for a in ("on_the_way",):
        assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": a}).status_code == 200
    cb = j(S.cust.get("/api/bookings"))[0]; seen.append(cb["status"])
    assert cb["provider_lat"] == 11.02 and cb["provider_loc_at"]                                         # real tracking data
    assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": "arrived"}).status_code == 200
    assert S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": -5}).status_code == 400
    r = S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": 500, "parts": 250, "extra": 50, "note": "new starter motor"})
    assert r.status_code == 200 and j(r)["estimate"]["total"] == 800
    assert j(S.cust.get("/api/bookings"))[0]["estimate"]["total"] == 800
    for who, a in ((S.cust, "approve"), (S.prov, "start"), (S.prov, "complete"), (S.cust, "confirm")):
        assert who.post(f"/api/bookings/{bid}/action", json={"action": a}).status_code == 200
        seen.append(j(S.cust.get("/api/bookings"))[0]["status"])
    assert j(S.cust.get("/api/bookings"))[0]["provider_lat"] is None                                     # tracking stops after trip
    assert S.cust.post(f"/api/bookings/{bid}/review", json={"rating": 9}).status_code == 400
    assert S.cust.post(f"/api/bookings/{bid}/review", json={"rating": 5, "comment": "Fast"}).status_code == 201
    assert S.cust.post(f"/api/bookings/{bid}/review", json={"rating": 4}).status_code == 409
    print("\nOBSERVED TRANSITIONS:", " -> ".join(seen))
    print("EVENT LOG:", [e["status"] for e in j(S.cust.get("/api/bookings"))[0]["history"]])
    assert seen == ["requested", "accepted", "on_the_way", "estimate_approved", "in_progress", "awaiting_confirmation", "completed"]

def test_persistence_and_dashboards():
    fresh = A.app.test_client(); login(fresh, "c@t.io")         # new session/connection = like a restart + re-login
    b = j(fresh.get("/api/bookings"))[0]; assert b["status"] == "completed" and b["review"]["rating"] == 5
    st = j(S.admin.get("/api/admin/stats")); assert st["customers"] == 1 and st["providers"] == 2
    assert {"status": "completed", "n": 1} in st["bookings"]
    assert S.admin.put(f"/api/admin/providers/{S.ids['p2']}/verify", json={"verified": False}).status_code == 200
    assert S.admin.put("/api/admin/providers/9999/verify", json={"verified": False}).status_code == 404

def test_emergency_priority_and_escalation():
    c2 = A.app.test_client(); reg(c2, name="Dan", email="d@t.io", password="password1", role="customer"); login(c2, "d@t.io")
    far = dict(lat=11.0168 + 0.2, lng=76.9558)       # only p2 (unverified) is near -> p1 ~28km: needs stage 2 escalation
    r = c2.post("/api/bookings", json={"category": "Vehicle Mechanic", "description": "Highway breakdown", "emergency": True, **far})
    assert r.status_code == 201 and j(r)["emergency"] == 1 and j(r)["provider_id"] == S.ids["p1"]
    c3 = A.app.test_client(); reg(c3, name="Eve", email="e@t.io", password="password1", role="customer"); login(c3, "e@t.io")
    c3.post("/api/bookings", json={"category": "Vehicle Mechanic", "description": "Flat tyre, routine", **LOC})
    order = [x["emergency"] for x in j(S.prov.get("/api/bookings"))]
    assert order == sorted(order, reverse=True) and order[0] == 1                                       # emergencies listed first


def test_estimate_validation_and_decline():
    c4 = A.app.test_client(); reg(c4, name="Frank", email="f@t.io", password="password1", role="customer"); login(c4, "f@t.io")
    r = c4.post("/api/bookings", json={"category": "Vehicle Mechanic", "description": "Brake check", **LOC})
    assert r.status_code == 201
    bid = j(r)["id"]
    assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": "accept"}).status_code == 200
    assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": "on_the_way"}).status_code == 200
    assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": "arrived"}).status_code == 200
    # Negative values rejected
    assert S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": 100, "parts": -20}).status_code == 400
    assert S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": 100, "extra": -10}).status_code == 400
    # Zero total rejected
    assert S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": 0, "parts": 0, "extra": 0}).status_code == 400
    # Valid estimate with decimal / currency values and note
    r_est = S.prov.post(f"/api/bookings/{bid}/estimate", json={"labour": 350.5, "parts": 120.25, "extra": 29.25, "note": "Brake pad replacement"})
    assert r_est.status_code == 200
    est = j(r_est)["estimate"]
    assert est["labour"] == 350.5 and est["parts"] == 120.25 and est["extra"] == 29.25 and est["total"] == 500.0
    # Provider cannot start before customer approves
    assert S.prov.post(f"/api/bookings/{bid}/action", json={"action": "start"}).status_code == 409
    # Customer declines estimate -> booking cancelled
    assert c4.post(f"/api/bookings/{bid}/action", json={"action": "decline"}).status_code == 200
    assert j(c4.get("/api/bookings"))[0]["status"] == "cancelled"


if __name__ == "__main__":   # runs without pytest: python tests/test_workflow.py
    bad = 0
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try: f(); print("PASS", n)
            except Exception as e: bad += 1; print("FAIL", n, repr(e))
    sys.exit(bad)
