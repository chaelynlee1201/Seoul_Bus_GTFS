#!/bin/zsh
# 오늘 밤 수집 종료 후(00:35) launchd가 1회 실행: 재처리→검증→요약→zip. 실행 후 자기 자신(launchagent) 제거.
cd /Users/chaelyn/Seoul_Bus_GTFS || exit 1
source /Users/chaelyn/miniforge3/etc/profile.d/conda.sh 2>/dev/null
REPORT="logs/finalize_report.txt"
{
  echo "=== finalize 시작 $(date '+%F %T') ==="
  # 수집 프로세스가 아직 살아있으면 최대 10분 대기
  for i in {1..20}; do pgrep -f "collect_stop_times.py --start" >/dev/null 2>&1 || break; sleep 30; done
  echo "[수집 종료 확인] $(date '+%T')"
  echo; echo "=== reprocess (가상정류소 제외 수정본) ==="
  python3 scripts/collect_stop_times.py reprocess
  echo; echo "=== 형식 검증 ==="
  python3 scripts/validate_gtfs.py
  echo; echo "=== 요약 ==="
  python3 scripts/summarize_gtfs.py
  echo; echo "=== zip 패키징 ==="
  ( cd gtfs_output && zip -q seoul_dongdaemun_gtfs_pilot.zip agency.txt stops.txt routes.txt trips.txt stop_times.txt calendar_dates.txt feed_info.txt && ls -la seoul_dongdaemun_gtfs_pilot.zip )
  echo; echo "=== finalize 완료 $(date '+%F %T') ==="
} > "$REPORT" 2>&1
# 자기 자신 제거(1회성)
launchctl bootout gui/$(id -u)/com.seoulbus.finalize 2>/dev/null
launchctl unload -w /Users/chaelyn/Library/LaunchAgents/com.seoulbus.finalize.plist 2>/dev/null
rm -f /Users/chaelyn/Library/LaunchAgents/com.seoulbus.finalize.plist
