"""
collect_stop_times.py — 서울 실시간 도착 API로 trips.txt / stop_times.txt 구축
                        (동대문구 파일럿 4노선, 300초 주기)

방법 (jparkgeo/GTFS_realtime_Korea · collect_stop_times_273 계승):
  - getArrInfoByRouteAll(busRouteId) 를 4노선에 대해 매 INTERVAL 폴링
  - 도착 확정: kals1==0 & '곧' in arrmsg1 (또는 isArrive1==1) → 그 호출시각 = 실제 도착시각
  - 미확정 상태에서 (trip,stop)이 다음 호출에 사라지면 last_time + kals1(초)로 추정
  - trip 분할: (busRouteId, vehId) 스트림에서 staOrd가 노선 max 부근→저순번 리셋 시 새 trip
  - direction_id: staOrd <= turn_seq → 0(상행), > turn_seq → 1(하행)

호출 예산: 4노선 × (20h/300s=240 cycle) = 960회/일  (도착정보 서비스 1,000/일 한도 내)

산출:
  raw_log_pilot.csv                     원본 관측 로그(재처리용)
  gtfs_output/stop_times.txt            trip_id,arrival_time,departure_time,stop_id,stop_sequence,timepoint
  gtfs_output/trips.txt                 route_id,service_id,trip_id,direction_id
  gtfs_output/calendar_dates.txt        service_id,date,exception_type
  gtfs_output/feed_info.txt

실행:
  python scripts/collect_stop_times.py                 # 오늘 서비스일, 현재~종료시각까지 수집
  python scripts/collect_stop_times.py --end 24:00     # 종료시각 지정(다음날 넘기면 25:00 등)
  python scripts/collect_stop_times.py reprocess        # raw_log 재처리만
"""
import os, sys, json, time, argparse
from pathlib import Path
from datetime import datetime, timedelta
import shutil, zipfile
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

# ── 설정 ──────────────────────────────────────────────────────────────
META=json.loads((ROOT/"data/pilot_route_meta.json").read_text())  # rid -> {rtNm,max_seq,n_stops,turn_seq}
ROUTES=list(META.keys())
INTERVAL=240
URL="http://ws.bus.go.kr/api/rest/arrive/getArrInfoByRouteAll"
GBASE=ROOT/"gtfs_output"          # 정적 파일(agency/stops/routes) 위치
STATIC_FILES=["agency.txt","stops.txt","routes.txt"]

def raw_path(service_date):
    return ROOT/f"data/raw_log_{service_date}.csv"

def out_dir(service_date):
    d=GBASE/service_date; d.mkdir(parents=True,exist_ok=True); return d

# traTime1 = 표출 도착예정시간(초, arrmsg1과 일치) = 실제 ETA. kals1은 칼만추정치(참고용 보존).
NEEDED=["stId","stNm","arsId","busRouteId","rtNm","staOrd","mkTm",
        "vehId1","plainNo1","isLast1","isArrive1","traTime1","kals1","arrmsg1"]

def fetch(rid):
    try:
        r=requests.get(URL, params={"serviceKey":KEY,"busRouteId":rid,"resultType":"json"}, timeout=15)
        r.raise_for_status()
        items=r.json().get("msgBody",{}).get("itemList") or []
        if isinstance(items,dict): items=[items]
        df=pd.DataFrame(items)
        for c in NEEDED:
            if c not in df.columns: df[c]=None
        df=df[NEEDED].copy()
        df["staOrd"]=pd.to_numeric(df["staOrd"],errors="coerce").fillna(0).astype(int)
        df["traTime1"]=pd.to_numeric(df["traTime1"],errors="coerce").fillna(-1).astype(int)
        df["kals1"]=pd.to_numeric(df["kals1"],errors="coerce").fillna(-1).astype(int)
        df["isArrive1"]=pd.to_numeric(df["isArrive1"],errors="coerce").fillna(0).astype(int)
        df["vehId1"]=df["vehId1"].astype(str).str.strip()
        df["collected_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return df
    except Exception as e:
        print(f"  [ERR] {rid}: {e}"); return None

def hms(dt): return dt.strftime("%H:%M:%S")
def add_s(s,sec): return (datetime.strptime(s,"%H:%M:%S")+timedelta(seconds=sec)).strftime("%H:%M:%S")

class TripTracker:
    """(route,veh) 별 trip_id. staOrd가 노선 max-5 이상에서 <=10 으로 리셋되면 새 trip."""
    def __init__(self,meta): self.meta=meta; self.n=0; self.t={}; self.last={}
    def get(self,rid,veh,ord_):
        key=(rid,veh); mx=self.meta[rid]["max_seq"]; lo=self.last.get(key,0)
        if key not in self.t or (lo>=mx-5 and ord_<=10):
            self.n+=1; self.t[key]=f"{rid}_{veh}_{self.n}"
        self.last[key]=ord_; return self.t[key]

class Recorder:
    def __init__(self,meta,interval=INTERVAL):
        self.meta=meta; self.interval=interval; self.pending={}; self.recs=[]
    def _dir(self,rid,ord_):
        t=self.meta[rid].get("turn_seq");
        return 0 if (t is None or ord_<=t) else 1
    def _emit(self,trip,rid,row,arr_str,src,tp):
        self.recs.append({"trip_id":trip,"route_id":rid,
            "direction_id":self._dir(rid,int(row["staOrd"])),
            "arrival_time":arr_str,"departure_time":add_s(arr_str,20),
            "stop_id":row["arsId"],"stop_sequence":int(row["staOrd"]),
            "stop_name":row["stNm"],"vehicle_id":row["vehId1"],
            "is_last":row["isLast1"],"source":src,"timepoint":tp})
    def update(self,trip,rid,row,now):
        # eta = traTime1 (표출 도착예정시간, arrmsg1과 일치하는 실제 ETA)
        stop=str(row["arsId"]); k=(trip,stop); eta=int(row["traTime1"])
        # 확정: isArrive1==1 = 버스가 정류소에 실제 도착 → 호출시각이 곧 도착시각
        if int(row["isArrive1"])==1:
            self._emit(trip,rid,row,hms(now),"exact",1); self.pending.pop(k,None); return
        self.pending[k]={"t":now,"eta":eta,"row":row.to_dict(),"trip":trip,"rid":rid}
    def flush_gone(self,cur):
        # (trip,stop)이 다음 호출에 사라짐 = 버스가 그 정류소 통과 → 직전관측시각+ETA를 도착시각으로
        for k in set(self.pending)-cur:
            p=self.pending.pop(k); eta=p["eta"]
            if 0<eta<=self.interval+60:
                arr=hms(p["t"]+timedelta(seconds=eta))
                self._emit(p["trip"],p["rid"],pd.Series(p["row"]),arr,"estimated",0)
    def flush_all(self):
        for k,p in list(self.pending.items()):
            if p["eta"]>0:
                arr=hms(p["t"]+timedelta(seconds=p["eta"]))
                self._emit(p["trip"],p["rid"],pd.Series(p["row"]),arr,"estimated_eod",0)
        self.pending.clear()
    def df(self): return pd.DataFrame(self.recs)

def write_gtfs(result, service_date):
    if result.empty: print("도착 기록 없음."); return
    # 참조 무결성: stops.txt에 없는 stop_id(가상정류소 등) 제외
    valid=set(pd.read_csv(ROOT/"gtfs_output/stops.txt",dtype=str)["stop_id"])
    before=len(result); result=result[result["stop_id"].astype(str).isin(valid)]
    dropped=before-len(result)
    if dropped: print(f"  [정리] stops.txt 미등록 stop_id {dropped}건 제외(가상정류소 등)")
    # 왕복 1회분(staOrd 1→N)을 회차지점 기준 방향별 trip으로 분리 → 각 trip = 단일 방향
    result=result.copy()
    result["trip_id"]=result["trip_id"].astype(str)+"_d"+result["direction_id"].astype(str)
    # trip은 최소 2정류장 이상만 유지
    good=result.groupby("trip_id")["stop_sequence"].nunique()
    result=result[result["trip_id"].isin(good[good>=2].index)]
    result=result.sort_values(["trip_id","stop_sequence"]).reset_index(drop=True)
    d=out_dir(service_date)                       # 날짜별 디렉터리 gtfs_output/YYYYMMDD/
    result[["trip_id","arrival_time","departure_time","stop_id","stop_sequence","timepoint"]]\
        .to_csv(d/"stop_times.txt",index=False,encoding="utf-8")
    sid=f"SER_{service_date}"
    trips=result[["route_id","trip_id","direction_id"]].drop_duplicates("trip_id").copy()
    trips["service_id"]=sid
    trips[["route_id","service_id","trip_id","direction_id"]].to_csv(d/"trips.txt",index=False,encoding="utf-8")
    pd.DataFrame([{"service_id":sid,"date":service_date,"exception_type":1}]).to_csv(d/"calendar_dates.txt",index=False,encoding="utf-8")
    pd.DataFrame([{"feed_publisher_name":"Seoul_Bus_GTFS (Dongdaemun pilot)",
                   "feed_publisher_url":"https://github.com/chaelynlee1201/Seoul_Bus_GTFS",
                   "feed_lang":"ko","feed_version":service_date}]).to_csv(d/"feed_info.txt",index=False,encoding="utf-8")
    # 정적 파일(agency/stops/routes) 복사 → 각 날짜가 완결된 GTFS
    for f in STATIC_FILES:
        if (GBASE/f).exists(): shutil.copy(GBASE/f, d/f)
    # zip 패키징
    zpath=d/f"seoul_dongdaemun_gtfs_{service_date}.zip"
    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
        for f in STATIC_FILES+["stop_times.txt","trips.txt","calendar_dates.txt","feed_info.txt"]:
            if (d/f).exists(): z.write(d/f, f)
    print(f"\n=== GTFS 완료 (service_date={service_date}) ===")
    print(f"trip: {result['trip_id'].nunique()} | stop_times: {len(result)}")
    print(f"  exact {sum(result.source=='exact')} · estimated {sum(result.source=='estimated')} · eod {sum(result.source=='estimated_eod')}")
    print(f"저장: {d}/  (+ {zpath.name})")

def collect(start_str, end_str):
    now0=datetime.now(); service_date=now0.strftime("%Y%m%d")
    base=now0.replace(hour=0,minute=0,second=0,microsecond=0)
    def parse(s): h,m=map(int,s.split(":")); return base+timedelta(hours=h,minutes=m)
    start=parse(start_str); end=parse(end_str)
    if datetime.now()<start:   # 시작시각 전이면 대기
        wait=(start-datetime.now()).total_seconds()
        print(f"시작시각 {start_str} 까지 {wait/3600:.1f}h 대기…")
        time.sleep(max(0,wait))
    print(f"수집 시작 {datetime.now():%H:%M} → 종료 {end_str} | 노선 {[META[r]['rtNm'] for r in ROUTES]} | 주기 {INTERVAL}s")
    RAW_LOG=raw_path(service_date)                # 날짜별 원본로그
    tr=TripTracker(META); rec=Recorder(META); call=0; raw=[]
    while datetime.now()<=end:
        t0=time.time(); call+=1; now=datetime.now(); cur=set(); frames=[]
        for rid in ROUTES:
            df=fetch(rid)
            if df is None: continue
            for _,row in df.iterrows():
                trip=tr.get(rid,str(row["vehId1"]).strip(),int(row["staOrd"]))
                cur.add((trip,str(row["arsId"]))); rec.update(trip,rid,row,now)
            df["call_no"]=call; frames.append(df)
        rec.flush_gone(cur)
        if frames: raw.append(pd.concat(frames,ignore_index=True))
        conf=len(rec.recs); pend=len(rec.pending)
        print(f"  #{call:04d} {now:%H:%M:%S} | 도착확정 {conf} | 추적중 {pend} | trip {tr.n}")
        if call%10==0 and raw:
            pd.concat(raw,ignore_index=True).to_csv(RAW_LOG,index=False,encoding="utf-8-sig")
        time.sleep(max(0,INTERVAL-(time.time()-t0)))
    rec.flush_all()
    if raw: pd.concat(raw,ignore_index=True).to_csv(RAW_LOG,index=False,encoding="utf-8-sig")
    write_gtfs(rec.df(), service_date)

def reprocess(date=None):
    if date is None:   # 최신 raw_log 자동 선택
        cands=sorted(ROOT.glob("data/raw_log_*.csv"))
        assert cands, "재처리할 raw_log가 없습니다"
        RAW_LOG=cands[-1]
    else:
        RAW_LOG=raw_path(date)
    print(f"재처리 대상: {RAW_LOG.name}")
    raw=pd.read_csv(RAW_LOG,dtype=str)
    raw["staOrd"]=pd.to_numeric(raw["staOrd"],errors="coerce").fillna(0).astype(int)
    if "traTime1" not in raw.columns: raw["traTime1"]=-1   # 구버전 raw 호환
    raw["traTime1"]=pd.to_numeric(raw["traTime1"],errors="coerce").fillna(-1).astype(int)
    raw["kals1"]=pd.to_numeric(raw["kals1"],errors="coerce").fillna(-1).astype(int)
    raw["isArrive1"]=pd.to_numeric(raw["isArrive1"],errors="coerce").fillna(0).astype(int)
    raw["vehId1"]=raw["vehId1"].astype(str).str.strip()
    service_date=pd.to_datetime(raw["collected_at"].iloc[0]).strftime("%Y%m%d")
    tr=TripTracker(META); rec=Recorder(META)
    for call,grp in raw.groupby("call_no"):
        now=datetime.strptime(grp["collected_at"].iloc[0],"%Y-%m-%d %H:%M:%S"); cur=set()
        for _,row in grp.iterrows():
            rid=str(row["busRouteId"])
            if rid not in META: continue
            trip=tr.get(rid,str(row["vehId1"]).strip(),int(row["staOrd"]))
            cur.add((trip,str(row["arsId"]))); rec.update(trip,rid,row,now)
        rec.flush_gone(cur)
    rec.flush_all(); write_gtfs(rec.df(), service_date)

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="reprocess":
        reprocess(sys.argv[2] if len(sys.argv)>2 else None)   # 선택: 날짜(YYYYMMDD)
    else:
        ap=argparse.ArgumentParser()
        ap.add_argument("--start",default="05:00")
        ap.add_argument("--end",default="24:30")
        a=ap.parse_args(); collect(a.start,a.end)
