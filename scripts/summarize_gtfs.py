"""summarize_gtfs.py — 생성된 GTFS 요약 리포트
사용: python scripts/summarize_gtfs.py [YYYYMMDD]  (생략 시 최신 날짜 폴더)"""
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parent.parent
def feed_dir():
    if len(sys.argv)>1: return ROOT/"gtfs_output"/sys.argv[1]
    dated=sorted(p for p in (ROOT/"gtfs_output").glob("2*") if p.is_dir())
    return dated[-1] if dated else ROOT/"gtfs_output"
G=feed_dir()

def main():
    st=pd.read_csv(G/"stop_times.txt",dtype=str)
    tr=pd.read_csv(G/"trips.txt",dtype=str)
    rt=pd.read_csv(G/"routes.txt",dtype=str)
    cal=pd.read_csv(G/"calendar_dates.txt",dtype=str)
    st["_seq"]=pd.to_numeric(st["stop_sequence"])
    date=cal["date"].iloc[0]
    print(f"■ 서비스일: {date}")
    print(f"■ 총 trips: {tr['trip_id'].nunique()}  |  stop_times: {len(st)}")
    print(f"■ 도착시각 범위: {st['arrival_time'].min()} ~ {st['arrival_time'].max()}")
    # 노선별
    m=st.merge(tr[["trip_id","route_id","direction_id"]],on="trip_id")
    m=m.merge(rt[["route_id","route_short_name"]],on="route_id",how="left")
    g=m.groupby("route_short_name").agg(trips=("trip_id","nunique"),
        stop_times=("trip_id","size"),
        방향=("direction_id","nunique")).reset_index().sort_values("stop_times",ascending=False)
    print("\n■ 노선별:")
    print(g.to_string(index=False))
    # 방향별 trip
    print("\n■ 방향(direction_id)별 trip:", m.groupby("direction_id")["trip_id"].nunique().to_dict())
    # trip당 정류장수 분포
    sz=st.groupby("trip_id")["_seq"].nunique()
    print(f"■ trip당 정류장 수: 중앙값 {int(sz.median())} · 최소 {sz.min()} · 최대 {sz.max()}")

if __name__=="__main__":
    main()
