# Seoul_Bus_GTFS — 실시간 도착 API 기반 서울 버스 GTFS (동대문구 파일럿)

시간표가 아니라 **버스 도착정보 API로 관측한 실제 도착시각**으로 GTFS를 구축한다.
참고: [`jparkgeo/GTFS_realtime_Korea`](https://github.com/jparkgeo/GTFS_realtime_Korea) (대경권)의
"실시간 위치·도착 관측 → 야간 재구성" 방법론을 서울에 적용.

핵심 아이디어: API 호출 시 "3분 뒤 도착 예정"이면 **호출시각 + 3분 = 실제 도착시각**으로 기록.

## 파일럿 범위
- **동대문구를 지나는 버스 노선만** (일일 API 트래픽 한도 때문에 공간 범위 제한).
- 정류소 = 서울시 버스정류소 위치정보 CSV를 동대문구 시군구 경계로 클립.

## GTFS 산출 대상
| 파일 | 소스 | 상태 |
|---|---|---|
| `stops.txt` | 서울시 버스정류소 위치정보 CSV ∩ 동대문구 경계 | ✅ **완료 (321개)** |
| `routes.txt` | 서울 TOPIS `getRouteByStation` (arsId별) | 스크립트 준비 — 키 대기 |
| `trips.txt` / `stop_times.txt` | 서울 TOPIS 실시간 도착 관측 → trip 재구성 | 설계 완료 — 키 대기 |

## 디렉터리
```
Seoul_Bus_GTFS/
├── data/
│   ├── raw/seoul_bus_stops_raw.csv        # 원천 (cp949, gitignore)
│   ├── boundary/BND_SIGUNGU_PG.*          # 시군구 경계 EPSG:5186 (gitignore)
│   ├── dongdaemun_stops.geojson           # 클립 결과(검수용)
│   └── stop_route_membership.csv          # arsId×노선 (routes 단계 산출)
├── gtfs_output/
│   ├── stops.txt                          # ✅
│   ├── routes.txt                         # (예정)
│   ├── trips.txt / stop_times.txt         # (예정)
├── scripts/
│   ├── build_stops.py                     # ✅ 동대문구 클립 → stops.txt
│   ├── build_routes.py                    # getRouteByStation → routes.txt
│   └── collect_stop_times.py              # (예정) 실시간 도착 수집 → stop_times
├── .env                                   # API 키 (gitignore)
└── .env.example
```

## 데이터 컬럼 매핑 (stops)
원천 CSV: `노드 ID`(5자리=**ARS ID**) · `정류소번호`(9자리=정류소 고유ID) · `정류소명` · `X좌표`(경도) · `Y좌표`(위도) · `정류소 타입`.
→ `stop_id`=ARS ID, `ars_id`(API 요청변수), `stop_uid`(9자리) 병기.

## API 상태 (2026-09-09 검증 완료)
data.go.kr 키(`c255a6…`)가 서울 TOPIS 3개 서비스 모두에서 **정상 작동**(활용신청 승인·전파 완료):
`getRouteByStation`·`getStationByUid`(15000303) / `getStaionByRoute`(15000193) / `getArrInfoByRouteAll`(15000314).
트래픽 한도 = **서비스별 각 1,000회/일**.

**파일럿 확정:** 동대문구 통과 **96개 노선** 중, 정류소 최다경유 **4노선**(2233·2112·3216·2211)을
**300초 주기**로 종일 관측 → 4×240 = **960회/일** (도착정보 1,000 한도 내). 전 96노선 관측은
~38,400회/일 필요 → 트래픽 상향 시 확장.

<details><summary>과거 진단 메모(참고)</summary>
- 제공된 data.go.kr 키(`c255a6…`)는 **국토부 TAGO에서 유효**(resultCode 00). 그러나
  **TAGO `BusLcInfoInqireService`는 서울을 커버하지 않음** (도시코드 138개 중 서울 없음 —
  세종·부산·대구·인천·광주·대전·울산·제주·경기 시군만). → 계획의
  `getRouteAcctoSpcifySttnAccesBusLcInfo`로는 **서울 trips/stop_times 생성 불가.**
- 서울 실시간 버스는 **서울 TOPIS(`ws.bus.go.kr`) 전용**이며 **별도 서울 키**가 필요.
  현재 data.go.kr 키·참고 스크립트의 옛 TOPIS 키 모두 `ws.bus.go.kr`에서 401.

### 필요한 것
서울열린데이터광장(data.seoul.go.kr) 또는 data.go.kr 서울 서비스(15000303 정류소·노선,
서울 버스도착정보) **승인 인증키**를 `.env`의 `SEOUL_TOPIS_API_KEY`에 설정.
그러면 routes / trips / stop_times 전 단계가 서울 TOPIS로 일관되게 구축됨:
- routes: `getRouteByStation`(arsId)
- 도착 관측: `getArrInfoByRouteAll`(busRouteId) — "곧도착/n분 후" → 실제 도착시각 환산
  (참고 스크립트 `collect_stop_times_273.py`의 방식).

</details>

## 트래픽·시간 추정 (서울 TOPIS 기준)
표기: R = 동대문구 통과 노선 수(추정 100–200, routes.txt 실행 시 확정), 서비스일 05–익01시 ≈ 20h.

| 단계 | 호출 방식 | 호출량 | 소요(벽시계) |
|---|---|---|---|
| stops.txt | 로컬 클립 | 0 | 완료(초 단위) |
| routes.txt | `getRouteByStation` × 정류소 321 | **321회 (1회성)** | ~2–3분 |
| stop_times (노선 폴링) | `getArrInfoByRouteAll` × R × cycle | 아래 표 | **관측 = 1일 20h/일** |

노선 폴링 호출량 = R × (72,000초 / 주기):
| 주기 | cycle/일 | R=100 | R=150 | R=200 |
|---|---|---|---|---|
| 60s | 1,200 | 120,000 | 180,000 | 240,000 |
| 120s | 600 | 60,000 | 90,000 | 120,000 |
| 180s | 400 | 40,000 | 60,000 | 80,000 |
| 300s | 240 | 24,000 | 36,000 | 48,000 |

**판단:**
- data.go.kr 개발계정/서울 기본 인증키는 흔히 **1,000회/일** → 동대문구 전체(R≈150) 불가.
  1,000/일이면 180s로 **약 2노선/일**만 가능.
- 전 노선 하루 관측(180s)에는 **≈6만 회/일** 필요 → **운영계정 트래픽 상향 신청** 필수.
- 상향이 어려우면 완화안: ① 주기 300s + 첨두시간대만(예 07–10,17–20시 6h) → R150×72=~10,800/일,
  ② 대표 노선 표본만, ③ 며칠에 걸쳐 노선 로테이션 수집.
- 도착시각 변동(요일효과) 확보를 위해 참고 연구처럼 **평일·주말 포함 1–2주 반복 수집** 권장.

## 서버(SLURM) 실행
```bash
# 1) 서버에 clone 후, 루트에 .env 생성:  SEOUL_TOPIS_API_KEY=<키>
pip install -r requirements.txt          # 또는 conda env
# 2) 하루 수집 제출
sbatch scripts/collect_daily.sbatch      # 05:00~00:30 → gtfs_output/YYYYMMDD/
# 3) 평일 자동화: (A) cron  0 5 * * 1-5 sbatch scripts/collect_daily.sbatch
#                 (B) 자기재제출  AUTO_RESUBMIT=1 sbatch scripts/collect_daily.sbatch
```
sbatch 상단의 conda env·partition·account를 클러스터에 맞게 수정. 산출은 날짜별 `gtfs_output/YYYYMMDD/`(완결 피드+zip). 검증 `python scripts/validate_gtfs.py [날짜]`, 요약 `summarize_gtfs.py [날짜]`, 원본 재처리 `collect_stop_times.py reprocess [날짜]`.

## 로컬 실행
```bash
python scripts/build_stops.py     # ✅ 완료
# .env 에 SEOUL_TOPIS_API_KEY 설정 후:
python scripts/build_routes.py    # routes.txt + 통과 노선 수 확정 → 트래픽 최종 산정
```
