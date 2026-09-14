"""
build_stops.py — 서울 버스 GTFS stops.txt 생성 (동대문구 파일럿)

입력:
  - data/raw/seoul_bus_stops_raw.csv  (서울시 버스정류소 위치정보, cp949)
      컬럼: 노드 ID(5자리=ARS ID) · 정류소번호(9자리=정류소 고유ID) · 정류소명 · X좌표(lon) · Y좌표(lat) · 정류소 타입
  - data/boundary/BND_SIGUNGU_PG.shp  (전국 시군구 경계, EPSG:5186)

처리:
  1) CSV → WGS84 포인트 GeoDataFrame
  2) 시군구 경계에서 동대문구(SIGUNGU_CD=11060) 폴리곤 추출
  3) 동대문구 폴리곤 내부 정류소만 공간 클립
  4) GTFS stops.txt (+ 참조용 ars_id/stop_code/stop_type) 저장

출력:
  - gtfs_output/stops.txt
  - data/dongdaemun_stops.geojson  (검수·후속 API용)
"""
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV   = ROOT / "data/raw/seoul_bus_stops_raw.csv"
BND_SHP   = ROOT / "data/boundary/BND_SIGUNGU_PG.shp"
OUT_TXT   = ROOT / "gtfs_output/stops.txt"
OUT_GJSON = ROOT / "data/dongdaemun_stops.geojson"

TARGET_SIGUNGU_CD = "11060"   # 동대문구
TARGET_NAME       = "동대문구"

def main():
    # ── 1) 정류소 CSV 로드 ────────────────────────────────────────────
    df = pd.read_csv(RAW_CSV, encoding="cp949", dtype=str)
    df = df.rename(columns={
        "노드 ID": "ars_id",        # 5자리 ARS ID (API 요청 변수 arsId)
        "정류소번호": "stop_uid",     # 9자리 정류소 고유 ID
        "정류소명": "stop_name",
        "X좌표": "stop_lon",
        "Y좌표": "stop_lat",
        "정류소 타입": "stop_type",
    })
    df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
    df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
    df = df.dropna(subset=["stop_lon", "stop_lat"]).reset_index(drop=True)
    print(f"전체 정류소: {len(df)}")

    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df["stop_lon"], df["stop_lat"])],
        crs="EPSG:4326",
    )

    # ── 2) 동대문구 경계 추출 ─────────────────────────────────────────
    bnd = gpd.read_file(BND_SHP)
    ddm = bnd[bnd["SIGUNGU_CD"] == TARGET_SIGUNGU_CD]
    if ddm.empty:  # 코드 미스매치 대비 이름으로 폴백
        ddm = bnd[bnd["SIGUNGU_NM"] == TARGET_NAME]
    assert not ddm.empty, "동대문구 경계를 찾지 못함"
    ddm = ddm.to_crs("EPSG:4326")
    print(f"동대문구 경계: {ddm['SIGUNGU_NM'].iloc[0]} ({ddm['SIGUNGU_CD'].iloc[0]})")

    # ── 3) 공간 클립 (동대문구 내부 정류소) ───────────────────────────
    clipped = gpd.sjoin(gdf, ddm[["SIGUNGU_CD", "SIGUNGU_NM", "geometry"]],
                        predicate="within", how="inner")
    clipped = clipped.drop_duplicates(subset=["ars_id"]).reset_index(drop=True)
    print(f"동대문구 내 정류소: {len(clipped)}")
    print("타입 분포:\n", clipped["stop_type"].value_counts().to_string())

    # ── 4) GTFS stops.txt 작성 ────────────────────────────────────────
    stops = pd.DataFrame({
        "stop_id":   clipped["ars_id"],          # ARS ID를 stop_id로
        "stop_code": clipped["ars_id"],          # 표출번호
        "stop_name": clipped["stop_name"],
        "stop_lat":  clipped["stop_lat"].round(7),
        "stop_lon":  clipped["stop_lon"].round(7),
        # ── 참조용(비표준) 컬럼: 후속 routes/stop_times API 호출에 사용 ──
        "ars_id":    clipped["ars_id"],          # getRouteByStation 요청 변수
        "stop_uid":  clipped["stop_uid"],        # 9자리 정류소 고유 ID
        "stop_type": clipped["stop_type"],
    }).sort_values("stop_id").reset_index(drop=True)

    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    stops.to_csv(OUT_TXT, index=False, encoding="utf-8")
    clipped[["ars_id", "stop_uid", "stop_name", "stop_type", "geometry"]] \
        .to_file(OUT_GJSON, driver="GeoJSON")

    print(f"\n저장: {OUT_TXT}  ({len(stops)}개 정류소)")
    print(f"저장: {OUT_GJSON}")
    print("\n=== stops.txt 미리보기 ===")
    print(stops.head(10).to_string())

if __name__ == "__main__":
    main()
