"""テスト用の偽 Google（OAuth トークン＋Calendar API）"""
import itertools, jwt, json, sys
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn
PUB = open(sys.argv[1]).read() if len(sys.argv) > 1 else None
ids = itertools.count(1)
cals: dict[str, dict] = {}
async def token(r):
    f = await r.form()
    claims = jwt.decode(f["assertion"], PUB, algorithms=["RS256"], audience="http://127.0.0.1:8904/token")
    assert "calendar" in claims["scope"]
    return JSONResponse({"access_token": "gtok", "expires_in": 3600})
def ok(r): return r.headers.get("authorization") == "Bearer gtok"
async def events(r):
    if not ok(r): return JSONResponse({}, status_code=401)
    cal = cals.setdefault(r.path_params["cal"], {})
    if r.path_params["cal"] == "forbidden": return JSONResponse({}, status_code=404)
    if r.method == "POST":
        e = await r.json(); e["id"] = f"ev{next(ids)}"; cal[e["id"]] = e
        print("GCAL CREATE:", r.path_params["cal"], e["summary"], e["start"], flush=True); return JSONResponse(e)
    return JSONResponse({"items": sorted(cal.values(), key=lambda e: json.dumps(e["start"]))})
async def event(r):
    cal = cals.setdefault(r.path_params["cal"], {}); eid = r.path_params["eid"]
    if r.method == "DELETE":
        print("!!! DELETE CALLED", flush=True); return JSONResponse({}, status_code=500)
    cal[eid].update(await r.json()); print("GCAL PATCH:", cal[eid]["summary"], flush=True); return JSONResponse(cal[eid])
app = Starlette(routes=[Route("/token", token, methods=["POST"]),
  Route("/calendar/v3/calendars/{cal}/events", events, methods=["GET", "POST"]),
  Route("/calendar/v3/calendars/{cal}/events/{eid}", event, methods=["PATCH", "DELETE"])])
if __name__ == "__main__": uvicorn.run(app, port=8904, log_level="warning")
