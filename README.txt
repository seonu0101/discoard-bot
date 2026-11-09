BetterMultiplayer 리더보드 디스코드 봇
=====================================

[처음 한 번만 하는 설정]
1. 디스코드 봇 만들기: https://discord.com/developers/applications
   - New Application > Bot > Reset Token 으로 토큰 복사
   - OAuth2 > URL Generator 에서 "bot" 체크, 권한은
     View Channels / Send Messages / Embed Links / Read Message History
   - 만들어진 주소로 들어가 내 서버에 봇 초대
2. 채널 ID 복사: 디스코드 설정 > 고급 > 개발자 모드 켜기 > 채널 우클릭 > "채널 ID 복사"
3. GitHub 저장소 > Settings > Secrets and variables > Actions > New repository secret
   - DISCORD_TOKEN = 봇 토큰
   - CHANNEL_ID    = 채널 ID

[봇 켜기 / 다시 켜기]  (GitHub에서 자동 실행, 약 5~10분마다 갱신)
1. 저장소 > Actions 탭
2. 왼쪽 "Update leaderboard" 클릭
3. "Enable workflow" 버튼이 보이면 누르기
4. "Run workflow" 버튼 누르기 → 초록 체크가 뜨면 성공
   이후에는 자동으로 계속 실행됩니다.

[봇 끄기]
Actions > Update leaderboard > 오른쪽 위 "..." > Disable workflow

[참고]
- 메시지를 새로 만들고 싶으면 저장소의 message_id.txt 를 지우면 됩니다.
  (디스코드에서 메시지를 지워도 다음 실행 때 새로 만듭니다.)
- 저장소에 60일 동안 변화가 없으면 GitHub가 자동 실행을 멈춥니다.
  그럴 땐 위 "봇 켜기"의 3~4번을 다시 하면 됩니다.
- 빨간 X가 뜨면 실행 기록을 눌러 "Update Discord message" 단계의 오류 문구를 확인하세요.

[PC나 서버에서 5초마다 갱신하고 싶을 때]
  pip install -r requirements.txt
  .env 파일에 DISCORD_TOKEN, CHANNEL_ID 값 넣기
  python bot.py
