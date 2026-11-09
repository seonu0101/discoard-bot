#!/bin/bash
# 오라클 클라우드(Ubuntu) 서버에 봇을 설치하고, 24시간 자동 실행되게 등록한다.
# 사용법 (서버에서):
#   curl -fsSL https://raw.githubusercontent.com/seonu0101/discoard-bot/main/deploy/install.sh | bash
# 다시 실행해도 안전하다 (최신 코드로 업데이트 + 재시작).
set -e

APP_DIR="$HOME/discoard-bot"
SERVICE=leaderboard-bot

echo "== 1/4 필요한 프로그램 설치 =="
# 새 서버는 처음 몇 분간 자동 업데이트가 돌기 때문에 끝날 때까지 기다리고(Lock::Timeout),
# 설치 중 질문 창(서비스 재시작 여부 등)이 뜨지 않게 한다.
APT="sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get -o DPkg::Lock::Timeout=900 -y -q"
$APT update
$APT install python3 python3-venv git

echo "== 2/4 코드 받기 =="
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone https://github.com/seonu0101/discoard-bot.git "$APP_DIR"
fi

echo "== 3/4 파이썬 패키지 설치 =="
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
[ -f "$APP_DIR/.env" ] || cp "$APP_DIR/.env.example" "$APP_DIR/.env"

echo "== 4/4 자동 실행 등록 =="
sudo tee /etc/systemd/system/$SERVICE.service > /dev/null <<UNIT
[Unit]
Description=BetterMultiplayer leaderboard Discord bot
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable -q $SERVICE

if grep -qE '^DISCORD_TOKEN=.+' "$APP_DIR/.env"; then
  sudo systemctl restart $SERVICE
  echo
  echo "설치 완료! 봇을 (다시) 켰습니다. 상태 보기: journalctl -u $SERVICE -f"
else
  echo
  echo "설치 완료! 이제 토큰을 넣으세요:  nano $APP_DIR/.env"
  echo "저장 후 봇 켜기:                  sudo systemctl restart $SERVICE"
fi
