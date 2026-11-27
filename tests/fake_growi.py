"""テスト用の偽 Growi API"""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn, itertools
TOKEN = "growitoken"
ids = itertools.count(100)
pages = {"/Miku's Origin/MO17/MO会議/20261028 第24回": {"_id": "p1", "body": "# 次回やること\n- 照明の配線図（フォルテ）11/6\n" + "x"*300, "rev": "r1"}}
def auth(r): return r.headers.get("authorization") == f"Bearer {TOKEN}"
def pj(path, p): return {"_id": p["_id"], "path": path, "updatedAt": "2026-10-28T13:00:00Z", "revision": {"_id": p["rev"], "body": p["body"]}}
async def page(r):
    if not auth(r): return JSONResponse({}, status_code=401)
    if r.method == "GET":
        path, pid = r.query_params.get("path"), r.query_params.get("pageId")
        for k, v in pages.items():
            if k == path or v["_id"] == pid: return JSONResponse({"page": pj(k, v)})
        return JSONResponse({}, status_code=404)
    j = await r.json()
    if r.method == "POST":
        pages[j["path"]] = {"_id": f"p{next(ids)}", "body": j["body"], "rev": "r0"}; return JSONResponse({"page": pj(j["path"], pages[j["path"]])})
    for k, v in pages.items():
        if v["_id"] == j["pageId"]:
            assert j["revisionId"] == v["rev"]; v["body"] = j["body"]; v["rev"] = v["rev"] + "'"; return JSONResponse({"page": pj(k, v)})
async def lst(r):
    pre = r.query_params["path"]; ps = [pj(k, v) for k, v in pages.items() if k.startswith(pre)]
    return JSONResponse({"pages": ps, "totalCount": len(ps)})
async def recent(r): return JSONResponse({"pages": [pj(k, v) for k, v in pages.items()]})
async def search(r):
    q = r.query_params["q"]; hits = [{"data": pj(k, v), "meta": {"elasticSearchResult": {"snippet": f"…<em class='highlighted-keyword'>{q}</em>…"}}} for k, v in pages.items() if q in v["body"] or q in k]
    return JSONResponse({"ok": True, "data": hits, "meta": {"total": len(hits)}})
app = Starlette(routes=[Route("/_api/v3/page", page, methods=["GET","POST","PUT"]), Route("/_api/v3/pages/list", lst), Route("/_api/v3/pages/recent", recent), Route("/_api/search", search)])
if __name__ == "__main__": uvicorn.run(app, port=8903, log_level="warning")
