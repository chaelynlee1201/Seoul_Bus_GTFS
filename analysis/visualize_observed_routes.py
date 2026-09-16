"""
관측형 GTFS 노선 경로 시각화 (folium)
─────────────────────────────────────────────────────────────────────────────
gtfs_output/YYYYMMDD/ 의 stops·routes·trips·stop_times 로부터, 노선별 '대표 운행'
(관측 정류장이 가장 많은 trip)의 실제 경로를 지도에 그리고, 각 정류장에 관측된
실도착시각을 표시한다. r5r_route_map.ipynb의 지도 스타일(노선 색·정류장·범례)을
참고하되, 라우팅 엔진 없이 관측 GTFS만으로 동작한다.

포스터용: 생성된 HTML을 브라우저로 열어 캡처 → "관측형 GTFS 활용 예" 그림으로 사용.

사용:
  python analysis/visualize_observed_routes.py 20260915      # 날짜 지정
  python analysis/visualize_observed_routes.py               # 최신 날짜 자동
필요: pip install folium
"""
import sys, io, zipfile
from pathlib import Path
import pandas as pd
import folium

ROOT = Path(__file__).resolve().parent.parent

def feed_dir(date=None):
    base = ROOT / "gtfs_output"
    if date:
        return base / date
    dated = sorted(p for p in base.glob("2*") if p.is_dir())
    assert dated, "gtfs_output/YYYYMMDD 폴더가 없습니다"
    return dated[-1]

# 노선별 색 (구분 잘 되는 팔레트)
PALETTE = ["#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
           "#42d4f4", "#f032e6", "#bfef45", "#469990", "#9A6324"]

def load_gtfs(d):
    def rd(name):
        return pd.read_csv(d / name, dtype=str)
    stops = rd("stops.txt"); routes = rd("routes.txt")
    trips = rd("trips.txt"); st = rd("stop_times.txt")
    stops["stop_lat"] = stops["stop_lat"].astype(float)
    stops["stop_lon"] = stops["stop_lon"].astype(float)
    st["stop_sequence"] = pd.to_numeric(st["stop_sequence"])
    return stops, routes, trips, st

def _sec(t):
    h, m, s = map(int, str(t).split(":")); return h*3600 + m*60 + s

def pick_rep_trips(trips, st, dur_lo=20, dur_hi=150):
    """노선별 대표 trip = '현실적 소요시간(기본 20~150분)' 내에서 정류장이 가장 많은 단일 운행.
    (소요시간 필터로 여러 운행이 병합된 비정상 trip 배제 → 깔끔한 단일 궤적 선택)"""
    g = st.groupby("trip_id")["arrival_time"]
    agg = pd.DataFrame({
        "n": st.groupby("trip_id")["stop_sequence"].nunique(),
        "dur_min": g.apply(lambda s: (max(map(_sec, s)) - min(map(_sec, s))) / 60.0),
    })
    tj = trips.merge(agg, left_on="trip_id", right_index=True, how="inner")
    ok = tj[(tj.dur_min >= dur_lo) & (tj.dur_min <= dur_hi)]
    base = ok if not ok.empty else tj              # 조건 맞는 게 없으면 전체에서
    rep = base.sort_values("n", ascending=False).drop_duplicates("route_id")
    return rep.sort_values("route_id")

def main():
    date = sys.argv[1] if len(sys.argv) > 1 else None
    d = feed_dir(date); service_date = d.name
    stops, routes, trips, st = load_gtfs(d)
    coord = stops.set_index("stop_id")[["stop_lat", "stop_lon", "stop_name"]]
    rname = dict(zip(routes.route_id, routes.route_short_name))

    rep = pick_rep_trips(trips, st)
    center = [stops.stop_lat.mean(), stops.stop_lon.mean()]
    m = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap")

    summary = []
    for i, (_, r) in enumerate(rep.iterrows()):
        rid, tid = r["route_id"], r["trip_id"]
        color = PALETTE[i % len(PALETTE)]
        rn = rname.get(rid, rid)
        seq = st[st.trip_id == tid].sort_values("stop_sequence").merge(
            coord, left_on="stop_id", right_index=True, how="left").dropna(subset=["stop_lat"])
        pts = seq[["stop_lat", "stop_lon"]].values.tolist()
        fg = folium.FeatureGroup(name=f"{rn} ({len(seq)}정류장)")
        folium.PolyLine(pts, color=color, weight=4, opacity=0.8).add_to(fg)
        for _, s in seq.iterrows():
            folium.CircleMarker(
                [s.stop_lat, s.stop_lon], radius=3, color=color, fill=True,
                fill_opacity=0.9,
                popup=folium.Popup(f"[{rn}] {s.stop_name}<br>실도착 {s.arrival_time} "
                                   f"(순번 {int(s.stop_sequence)})", max_width=240),
                tooltip=f"{rn} · {s.arrival_time}").add_to(fg)
        fg.add_to(m)
        summary.append((rn, len(seq), seq.arrival_time.min(), seq.arrival_time.max()))

    folium.LayerControl(collapsed=False).add_to(m)
    # 제목·범례 박스
    legend = ("<div style='position:fixed;top:12px;left:60px;z-index:9999;"
              "background:white;padding:10px 14px;border:1px solid #999;border-radius:6px;"
              "font-family:sans-serif;font-size:13px;box-shadow:2px 2px 6px rgba(0,0,0,.2)'>"
              f"<b>관측형 GTFS 경로 · 서울 동대문구</b><br>"
              f"<span style='color:#666'>서비스일 {service_date} · 정류장별 실도착시각 관측</span><hr style='margin:6px 0'>")
    for i, (rn, n, t0, t1) in enumerate(summary):
        c = PALETTE[i % len(PALETTE)]
        legend += (f"<div><span style='display:inline-block;width:12px;height:12px;"
                   f"background:{c};margin-right:6px'></span>{rn} — {n}정류장 "
                   f"({t0}~{t1})</div>")
    legend += "</div>"
    m.get_root().html.add_child(folium.Element(legend))

    out = d / f"route_map_{service_date}.html"
    m.save(str(out))
    print(f"서비스일 {service_date} | 노선 {len(summary)}개 시각화")
    for rn, n, t0, t1 in summary:
        print(f"  {rn}: {n}정류장, 실도착 {t0}~{t1}")
    print(f"저장: {out}  ← 브라우저로 열어 캡처(포스터용)")

if __name__ == "__main__":
    main()
