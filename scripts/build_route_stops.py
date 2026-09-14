"""
build_route_stops.py — 파일럿 4노선의 경유 정류소(순서·좌표) 확보 + stops.txt 보강

- getStaionByRoute(busRouteId) 로 노선별 정류소 순서(seq)·좌표(gpsX/Y)·회차지(trnstnid) 수집
- 산출:
    data/pilot_routes_stops.csv   : 노선별 정류소 순서 테이블(권위 소스, stop_sequence·reset·direction용)
    data/pilot_route_meta.json    : 노선별 최대 seq(=MAX_STOP_ORD), 회차 seq
    gtfs_output/stops.txt (갱신)   : 동대문구 321 ∪ 파일럿노선 전 정류소 (in_dongdaemun 플래그)

호출: 노선정보조회 서비스에서 4회(1회성).
"""
import os, json, time
from pathlib import Path
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

def load_env(path):
    if path.exists():
        for line in path.read_text().splitlines():
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
load_env(ROOT/".env")
KEY=os.environ["SEOUL_TOPIS_API_KEY"].strip()

# 파일럿 노선 — 동대문구 통과 96노선 중 2026-08 실측 승차량 상위 3개
# (271·272·130 — data/route_ridership_ranking.csv 근거)
PILOT = {
    "100100047":"271", "100100048":"272", "100100018":"130",
}
URL="http://ws.bus.go.kr/api/rest/busRouteInfo/getStaionByRoute"
STOPS_TXT=ROOT/"gtfs_output/stops.txt"

def fetch_route_stops(rid):
    r=requests.get(URL, params={"serviceKey":KEY,"busRouteId":rid,"resultType":"json"}, timeout=15)
    r.raise_for_status()
    items=r.json().get("msgBody",{}).get("itemList") or []
    if isinstance(items,dict): items=[items]
    return items

def main():
    rows=[]; meta={}
    for rid,rnm in PILOT.items():
        items=fetch_route_stops(rid)
        seqs=[int(it["seq"]) for it in items]
        # 회차 정류소(트런스테이션) seq 추정: trnstnid == station 인 지점
        trn_seq=None
        for it in items:
            if str(it.get("trnstnid")) == str(it.get("station")):
                trn_seq=int(it["seq"]); break
        meta[rid]={"rtNm":rnm,"max_seq":max(seqs),"n_stops":len(items),"turn_seq":trn_seq}
        for it in items:
            rows.append({
                "busRouteId":rid,"rtNm":rnm,"seq":int(it["seq"]),
                "stId":it["station"],"arsId":it["arsId"],"stationNm":it["stationNm"],
                "stop_lon":float(it["gpsX"]),"stop_lat":float(it["gpsY"]),
                "direction":it.get("direction","").strip(),"trnstnid":it.get("trnstnid"),
            })
        print(f"  {rnm}({rid}): {len(items)}개, 회차 seq={trn_seq}")
        time.sleep(0.2)

    rs=pd.DataFrame(rows)
    rs.to_csv(ROOT/"data/pilot_routes_stops.csv", index=False, encoding="utf-8")
    (ROOT/"data/pilot_route_meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2))

    # ── stops.txt 보강: 동대문구 stops ∪ 파일럿노선 stops ────────────────
    ddm=pd.read_csv(STOPS_TXT, dtype=str)
    ddm_ars=set(ddm["ars_id"])
    # 파일럿 노선 정류소(arsId 단위 유니크)
    pr=rs.drop_duplicates("arsId")[["arsId","stId","stationNm","stop_lon","stop_lat"]].copy()
    merged={}
    for _,r in ddm.iterrows():
        merged[r["ars_id"]]={"stop_id":r["ars_id"],"stop_code":r["ars_id"],
            "stop_name":r["stop_name"],"stop_lat":r["stop_lat"],"stop_lon":r["stop_lon"],
            "ars_id":r["ars_id"],"stop_uid":r.get("stop_uid",""),
            "stop_type":r.get("stop_type",""),"in_dongdaemun":"1"}
    for _,r in pr.iterrows():
        a=r["arsId"]
        if a in merged: continue
        merged[a]={"stop_id":a,"stop_code":a,"stop_name":r["stationNm"],
            "stop_lat":round(r["stop_lat"],7),"stop_lon":round(r["stop_lon"],7),
            "ars_id":a,"stop_uid":r["stId"],"stop_type":"","in_dongdaemun":"0"}
    out=pd.DataFrame(merged.values()).sort_values("stop_id")
    out.to_csv(STOPS_TXT, index=False, encoding="utf-8")

    n_ddm=(out["in_dongdaemun"]=="1").sum(); n_ext=(out["in_dongdaemun"]=="0").sum()
    print(f"\nstops.txt 갱신: 총 {len(out)}개 (동대문구 {n_ddm} + 파일럿노선 외곽 {n_ext})")
    print(f"저장: data/pilot_routes_stops.csv, data/pilot_route_meta.json")

if __name__=="__main__":
    main()
