#!/bin/zsh
# 매 평일 05:00 launchd가 실행. caffeinate로 수집 종료(00:30)까지 슬립 방지.
cd /Users/chaelyn/Seoul_Bus_GTFS || exit 1
source /Users/chaelyn/miniforge3/etc/profile.d/conda.sh 2>/dev/null
mkdir -p logs
LOG="logs/collect_$(date +%Y%m%d).log"
echo "=== launchd 시작 $(date '+%F %T') ===" >> "$LOG"
# -i idle -m disksleep -s system(AC 전원 시) 슬립 방지. 수집기는 05:00 시작~00:30 종료.
# launchd 비대화형 환경에선 conda base가 활성화 안 되므로 miniforge 파이썬 절대경로 사용
exec caffeinate -ims /Users/chaelyn/miniforge3/bin/python -u scripts/collect_stop_times.py --start 05:00 --end 24:30 >> "$LOG" 2>&1
