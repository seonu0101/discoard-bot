BetterMultiplayer 리더보드 디스코드 봇
=====================================

[1. 디스코드 봇 만들기]  (처음 한 번만)
1) https://discord.com/developers/applications 접속 > New Application > 이름 입력 > Create
2) General Information 화면의 "Application ID" 복사해 두기
3) 왼쪽 Bot 메뉴 > Reset Token > 나온 토큰 복사 (다른 사람에게 절대 보여주지 말 것)
4) 아래 주소의 APP_ID 자리에 2)의 ID를 넣어 브라우저로 열고, 내 서버를 골라 초대
   https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot+applications.commands&permissions=84992
   (권한: 채널 보기 / 메시지 보내기 / 링크 첨부 / 메시지 기록 보기)

[2. 테스트: GitHub Codespaces에서 켜기]  (브라우저만 있으면 됨, 월 약 60시간 무료)
1) 저장소 화면 > 초록색 "Code" 버튼 > Codespaces 탭 > "Create codespace on main"
2) 몇 분 기다리면 편집기가 열림. 왼쪽 파일 목록에서 .env 열기
3) DISCORD_TOKEN= 뒤에 토큰 붙여넣고 저장 (Ctrl+S)
4) 아래 터미널에 입력:   python bot.py
   "봇 로그인 성공", "명령어 등록" 이 보이면 정상
5) 디스코드에서 리더보드를 올릴 채널에  /리더보드  입력
   → 그 채널에 임베드가 올라가고 5초마다 갱신됨
   (명령어는 서버 관리 권한(채널 관리)이 있는 사람만 보임)
6) 끄기: 터미널에서 Ctrl+C.  다 쓰면 Codespace도 꺼 두기
   (github.com/codespaces 에서 ... > Stop codespace. 켜 두면 무료 시간이 줄어듦)

[3. Codespace를 꺼도 자동 갱신 (GitHub Actions, 5~10분 간격)]
* 이 방식은 /리더보드 명령어가 안 됩니다. 채널은 state.json 또는 CHANNEL_ID로 정해짐.
1) 저장소 > Settings > Secrets and variables > Actions > New repository secret
   - DISCORD_TOKEN = 봇 토큰
   - CHANNEL_ID    = 채널 ID (디스코드 설정 > 고급 > 개발자 모드 켜기 > 채널 우클릭 > 채널 ID 복사)
2) 저장소를 Public 으로 (Settings > 맨 아래 Change visibility). Private이면 무료 시간이 부족함
3) Actions 탭 > Update leaderboard > Run workflow

[참고]
- 리더보드 메시지를 디스코드에서 지워도, 다음 갱신 때 새로 만듭니다.
- 저장소에 60일 동안 변화가 없으면 GitHub가 자동 실행을 멈춥니다. Actions 탭에서 다시 Enable.
