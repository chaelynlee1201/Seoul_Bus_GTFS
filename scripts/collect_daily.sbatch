#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SLURM 배치: 서울 버스 실시간 도착 수집 (동대문구 파일럿 5노선)
#   하루 서비스일(04:00~익일 00:30)을 수집 → gtfs_output/YYYYMMDD/ 생성
#
# 제출:   cd ~/Seoul_Bus_GTFS && sbatch scripts/collect_daily.sbatch
# 평일 자동화: 아래 두 방법 중 택1
#   (A) 로그인노드 cron:   0 4 * * 1-5  cd ~/Seoul_Bus_GTFS && sbatch scripts/collect_daily.sbatch
#   (B) 자기 재제출:       AUTO_RESUBMIT=1 sbatch scripts/collect_daily.sbatch
#                          (잡 끝에서 다음 평일 04:00로 --begin 재제출)
# ─────────────────────────────────────────────────────────────────────────────
#SBATCH --job-name=seoulbus_collect
#SBATCH --output=logs/slurm_%x_%j.out
#SBATCH --error=logs/slurm_%x_%j.out
#SBATCH --time=21:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
### 클러스터에 맞게 주석 해제·수정 ↓
# #SBATCH --partition=cpu
# #SBATCH --account=your_account

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(pwd)}"
mkdir -p logs

# ── conda 환경 (여러 설치 위치 자동 탐색) ────────────────────────────────────
for c in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" /opt/miniconda3 /opt/anaconda3; do
  if [ -f "$c/etc/profile.d/conda.sh" ]; then source "$c/etc/profile.d/conda.sh"; break; fi
done
conda activate "${CONDA_ENV:-base}"   # 제출 시 CONDA_ENV=GTFS 등으로 지정. 사전에 requirements.txt 설치.
echo "[env] python=$(which python)"

# ── .env 확인 (서버에 직접 생성 필요: SEOUL_TOPIS_API_KEY=...) ────────────────
if [ ! -f .env ]; then
  echo "[FATAL] .env 없음. 'SEOUL_TOPIS_API_KEY=<키>' 파일을 리포 루트에 생성하세요." >&2
  exit 1
fi

echo "[$(date '+%F %T')] SLURM job $SLURM_JOB_ID 시작 — 서울버스 도착 수집"

# ── 서비스일 04:00~00:30 수집 (start 이전 제출 시 04:00까지 대기) ─────────────
python -u scripts/collect_stop_times.py --start 04:00 --end 24:30

echo "[$(date '+%F %T')] 수집 종료. gtfs_output/$(date +%Y%m%d)/ 확인"

# ── (선택) 다음 평일 04:00 자동 재제출 ───────────────────────────────────────
if [ "${AUTO_RESUBMIT:-0}" = "1" ]; then
  dow=$(date +%u)                       # 1=월 … 7=일
  case "$dow" in
    5) skip=3 ;;   # 금 → 월
    6) skip=2 ;;   # 토 → 월
    *) skip=1 ;;   # 그 외 → 다음날
  esac
  begin=$(date -d "+${skip} day 04:00" +%Y-%m-%dT%H:%M:%S)
  echo "[재제출] 다음 실행 --begin=$begin"
  AUTO_RESUBMIT=1 sbatch --begin="$begin" scripts/collect_daily.sbatch
fi
