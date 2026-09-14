"""
build_routes.py — 동대문구 정류소를 지나는 노선으로 routes.txt 생성

방법: stops.txt의 각 arsId에 대해 서울 TOPIS getRouteByStation 호출 →
      정류소를 지나는 노선(busRouteId, 노선명, 노선유형) 수집 → 중복 제거 → routes.txt

필요: .env 의 SEOUL_TOPIS_API_KEY  (ws.bus.go.kr 인증키)
서비스: http://ws.bus.go.kr/api/rest/stationinfo/getRouteByStation  (요청변수 arsId)

호출 예산: 정류소 수(≈321)회 1회성. (일일 트래픽 한도와 무관하게 소량)

산출:
  - gtfs_output/routes.txt              (route_id, route_short_name, route_long_name, route_type)
  - data/stop_route_membership.csv      (arsId × busRouteId — trips/stop_times 범위 산정용)
"""
import os, time
from pathlib import Path
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

def load_env(path: Path):
    """의존성 없는 최소 .env 로더."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env(ROOT / ".env")
KEY = os.environ.get("SEOUL_TOPIS_API_KEY", "").strip()

STOPS_TXT = ROOT / "gtfs_output/stops.txt"
ROUTES_TXT = ROOT / "gtfs_output/routes.txt"
MEMBERSHIP = ROOT / "data/stop_route_membership.csv"
URL = "http://ws.bus.go.kr/api/rest/stationinfo/getRouteByStation"

# 서울 노선 유형 코드 → GTFS route_type (버스=3)
ROUTE_TYPE_GTFS = 3

def fetch_routes_for_stop(ars_id: str):
    r = requests.get(URL, params={"serviceKey": KEY, "arsId": ars_id,
                                  "resultType": "json"}, timeout=15)
    r.raise_for_status()
    body = r.json().get("msgBody") or {}
    items = body.get("itemList") or []
    if isinstance(items, dict):
        items = [items]
    return items

def main():
    assert KEY, "SEOUL_TOPIS_API_KEY 가 .env 에 없습니다 (서울 TOPIS 키 필요)"
    stops = pd.read_csv(STOPS_TXT, dtype=str)
    ars_ids = stops["ars_id"].tolist()

    routes = {}          # busRouteId -> dict
    membership = []      # (ars_id, busRouteId, rtNm)
    for i, ars in enumerate(ars_ids, 1):
        try:
            for it in fetch_routes_for_stop(ars):
                rid = str(it.get("busRouteId") or it.get("busRouteAbrv") or "").strip()
                rnm = str(it.get("busRouteNm") or it.get("rtNm") or "").strip()
                rtp = str(it.get("busRouteType") or it.get("routeType") or "").strip()
                if not rid:
                    continue
                routes[rid] = {"route_id": rid, "route_short_name": rnm,
                               "route_long_name": rnm, "route_type": ROUTE_TYPE_GTFS,
                               "seoul_route_type": rtp}
                membership.append((ars, rid, rnm))
        except Exception as e:
            print(f"  [ERR] arsId={ars}: {e}")
        if i % 25 == 0:
            print(f"  {i}/{len(ars_ids)} 정류소 처리, 누적 노선 {len(routes)}")
        time.sleep(0.2)   # 예의상 페이싱

    rdf = pd.DataFrame(routes.values()).sort_values("route_id")
    rdf[["route_id","route_short_name","route_long_name","route_type"]] \
        .to_csv(ROUTES_TXT, index=False, encoding="utf-8")
    pd.DataFrame(membership, columns=["ars_id","busRouteId","rtNm"]) \
        .drop_duplicates().to_csv(MEMBERSHIP, index=False, encoding="utf-8")

    print(f"\n저장: {ROUTES_TXT}  (고유 노선 {len(rdf)}개)")
    print(f"저장: {MEMBERSHIP}")
    print(f"\n>>> trips/stop_times 수집 대상 노선 수 = {len(rdf)}  <<<")

if __name__ == "__main__":
    main()
