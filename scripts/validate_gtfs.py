"""
validate_gtfs.py — 생성된 GTFS(stop_times.txt·trips.txt 등) 형식 검증
사용: python scripts/validate_gtfs.py [YYYYMMDD]   (생략 시 최신 날짜 폴더)
"""
import re, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
def feed_dir():
    if len(sys.argv)>1: return ROOT/"gtfs_output"/sys.argv[1]
    dated=sorted(p for p in (ROOT/"gtfs_output").glob("2*") if p.is_dir())
    return dated[-1] if dated else ROOT/"gtfs_output"
G = feed_dir()
print(f"[검증 대상: {G}]")
HMS = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")

def ok(c): return "✅" if c else "❌"

def main():
    errs=[]; warn=[]
    stops=pd.read_csv(G/"stops.txt",dtype=str)
    routes=pd.read_csv(G/"routes.txt",dtype=str)
    trips=pd.read_csv(G/"trips.txt",dtype=str)
    st=pd.read_csv(G/"stop_times.txt",dtype=str)

    # ── trips.txt ──
    print("── trips.txt ──")
    need_tr=["route_id","service_id","trip_id","direction_id"]
    c=list(trips.columns)==need_tr; print(f"{ok(c)} 컬럼 {c and '정상' or trips.columns.tolist()}")
    if not c: errs.append("trips 컬럼")
    c=trips["trip_id"].is_unique; print(f"{ok(c)} trip_id 유일 ({trips['trip_id'].nunique()}개)")
    if not c: errs.append("trip_id 중복")
    c=trips["direction_id"].isin(["0","1"]).all(); print(f"{ok(c)} direction_id ∈ {{0,1}}")
    if not c: errs.append("direction_id")
    c=trips["route_id"].isin(set(routes["route_id"])).all(); print(f"{ok(c)} route_id → routes.txt 참조")
    if not c: errs.append("route_id 미참조")

    # ── stop_times.txt ──
    print("\n── stop_times.txt ──")
    need_st=["trip_id","arrival_time","departure_time","stop_id","stop_sequence","timepoint"]
    c=list(st.columns)==need_st; print(f"{ok(c)} 컬럼 {c and '정상' or st.columns.tolist()}")
    if not c: errs.append("stop_times 컬럼")
    c=st["arrival_time"].apply(lambda x:bool(HMS.match(str(x)))).all()
    print(f"{ok(c)} arrival_time HH:MM:SS 형식")
    if not c: errs.append("arrival_time 형식")
    c=st["departure_time"].apply(lambda x:bool(HMS.match(str(x)))).all()
    print(f"{ok(c)} departure_time HH:MM:SS 형식")
    c=pd.to_numeric(st["stop_sequence"],errors="coerce").notna().all()
    print(f"{ok(c)} stop_sequence 정수")
    c=st["timepoint"].isin(["0","1"]).all(); print(f"{ok(c)} timepoint ∈ {{0,1}}")
    # 참조 무결성
    orphan=set(st["stop_id"])-set(stops["stop_id"])
    c=len(orphan)==0; print(f"{ok(c)} stop_id → stops.txt 참조 (orphan {len(orphan)})")
    if not c: errs.append(f"orphan stop_id {list(orphan)[:5]}")
    miss=set(st["trip_id"])-set(trips["trip_id"])
    c=len(miss)==0; print(f"{ok(c)} stop_times.trip_id → trips.txt 참조 (누락 {len(miss)})")
    if not c: errs.append("trip_id 미참조")
    # trip 내 stop_sequence 단조 증가 & 최소 2정류장
    st["_seq"]=pd.to_numeric(st["stop_sequence"])
    mono=st.sort_values(["trip_id","_seq"]).groupby("trip_id")["_seq"].apply(lambda s:s.is_monotonic_increasing).all()
    print(f"{ok(mono)} trip별 stop_sequence 단조증가")
    sizes=st.groupby("trip_id")["_seq"].nunique()
    c=(sizes>=2).all(); print(f"{ok(c)} 모든 trip ≥2 정류장 (최소 {sizes.min()})")

    # ── 요약 ──
    print(f"\n=== 규모 ===")
    print(f"trips {len(trips)} | stop_times {len(st)} | stops {len(stops)} | routes {len(routes)}")
    if "source" not in st.columns:
        pass
    print(f"\n=== 샘플 (한 trip) ===")
    t0=st.sort_values(["trip_id","_seq"]).iloc[0]["trip_id"]
    print(st[st["trip_id"]==t0].sort_values("_seq")[need_st].head(8).to_string(index=False))

    print(f"\n{'🟥 오류: '+'; '.join(errs) if errs else '🟩 형식 검증 통과 (오류 없음)'}")

if __name__=="__main__":
    main()
