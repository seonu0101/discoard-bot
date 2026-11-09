"""
BetterMultiplayer 리더보드를 디스코드 임베드로 보여주는 봇.

실행 방법
  python bot.py            계속 켜 두기: /리더보드 명령어 + 5초마다 갱신
  python bot.py --once     한 번만 갱신하고 종료 (GitHub Actions용, 명령어는 안 됨)
  python bot.py --dry-run  디스코드 없이 만들어질 임베드만 화면에 출력 (테스트용)

설정은 .env 파일 또는 환경변수에서 읽습니다.
  DISCORD_TOKEN    봇 토큰 (필수)
  CHANNEL_ID       (선택) 처음 올릴 채널 ID. 비워 두고 /리더보드 명령어로 정해도 됩니다.
  TRACK            0=Duel, 1=United Combat, 2=Spirit Ashes (기본 0)
  UPDATE_INTERVAL  갱신 간격(초), 계속 실행 모드에서만 사용 (기본 5)

서버마다 어느 채널의 어떤 메시지를 수정할지 state.json 파일에 저장됩니다.
여러 서버에서 동시에 쓸 수 있습니다 (서버당 리더보드 1개).
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

API_URL = "https://leaderboard.bettermultiplayer.com/leaderboard/{track}?limit={limit}&offset=0"
TRACK_LABELS = {0: "Duel", 1: "United Combat", 2: "Spirit Ashes"}
STATE_FILE = Path(__file__).with_name("state.json")
MEDAL_COLORS = {1: 0xFFD700, 2: 0xC0C0C0, 3: 0xCD7F32}
DEFAULT_COLOR = 0x5865F2
TOP_N = 25               # 표시할 인원
EMBEDS_PER_MESSAGE = 10  # 디스코드 제한: 메시지 하나에 임베드 최대 10개
RECHECK_SECONDS = 60     # 내용이 그대로여도 이 간격마다 메시지가 지워졌는지 확인

log = logging.getLogger("leaderboard-bot")


# ---------------------------------------------------------------- 설정

def read_config() -> dict:
    load_dotenv(Path(__file__).with_name(".env"))
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        sys.exit("DISCORD_TOKEN이 비어 있습니다. .env 파일(또는 GitHub Secrets)을 확인하세요.")
    channel_id = os.getenv("CHANNEL_ID", "").strip()
    if channel_id and not channel_id.isdigit():
        sys.exit("CHANNEL_ID는 숫자여야 합니다.")
    return {
        "token": token,
        "channel_id": int(channel_id) if channel_id else None,
        "track": int(os.getenv("TRACK", "0") or 0),
        "interval": max(float(os.getenv("UPDATE_INTERVAL", "5") or 5), 2.0),
        # 프록시가 있는 환경(일부 클라우드)에서도 동작하도록
        "proxy": os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or None,
    }


# ---------------------------------------------------------------- 데이터 가져오기

async def fetch_leaderboard(session: aiohttp.ClientSession, track: int) -> list[dict]:
    """상위 TOP_N명 목록을 가져온다. 실패하면 예외가 난다."""
    url = API_URL.format(track=track, limit=TOP_N)
    timeout = aiohttp.ClientTimeout(total=10)
    headers = {"User-Agent": "leaderboard-discord-bot"}
    async with session.get(url, timeout=timeout, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
    players = []
    for row in data.get("data", [])[:TOP_N]:
        p = row.get("player") or {}
        players.append({
            "rank": row.get("rank_position"),
            "name": (p.get("persona_name") or "").strip(),
            "avatar": p.get("avatar_url") or None,
            "steam_id": p.get("steam_id"),
            "rating": row.get("rating"),
            "wins": row.get("wins", 0),
            "losses": row.get("losses", 0),
            "draws": row.get("draws", 0),
        })
    return players


# ---------------------------------------------------------------- 임베드 만들기

# 언어별 문구. ko = /리더보드, en = /leaderboard
TEXT = {
    "ko": {
        "header": "🏆 **{label} 리더보드** 상위 {n}명",
        "empty": "🏆 **{label} 리더보드** — 아직 순위 데이터가 없습니다.",
        "record": "{w}승 {l}패",
        "draws": " {d}무",
        "rating": "레이팅 **{r}** · {record}",
        "no_name": "(이름 없음)",
        "site_down": "리더보드 사이트에 접속하지 못했습니다. 잠시 후 다시 시도하세요.",
        "no_perm": "이 채널에 메시지를 올릴 권한이 없습니다. 봇에게 '채널 보기 / 메시지 보내기 / "
                   "링크 첨부 / 메시지 기록 보기' 권한을 주세요.",
        "done": "완료! 이 채널에 리더보드를 올렸고 {s}초마다 갱신합니다.",
        "admin_only": "이 명령어는 서버 관리자만 사용할 수 있습니다.",
    },
    "en": {
        "header": "🏆 **{label} Leaderboard** Top {n}",
        "empty": "🏆 **{label} Leaderboard** — no ranking data yet.",
        "record": "{w}W {l}L",
        "draws": " {d}D",
        "rating": "Rating **{r}** · {record}",
        "no_name": "(no name)",
        "site_down": "Couldn't reach the leaderboard site. Please try again in a moment.",
        "no_perm": "I don't have permission to post here. Please give me View Channel, "
                   "Send Messages, Embed Links and Read Message History.",
        "done": "Done! Posted the leaderboard here; it refreshes every {s} seconds.",
        "admin_only": "Only server administrators can use this command.",
    },
}


def build_message(players: list[dict], track: int, lang: str = "ko") -> tuple[str, list[discord.Embed]]:
    t = TEXT.get(lang, TEXT["ko"])
    label = TRACK_LABELS.get(track, f"Track {track}")
    content = t["header"].format(label=label, n=len(players))
    if not players:
        content = t["empty"].format(label=label)
    embeds = []
    for p in players:
        record = t["record"].format(w=p["wins"], l=p["losses"])
        if p["draws"]:
            record += t["draws"].format(d=p["draws"])
        embed = discord.Embed(
            title=f"#{p['rank']}  {p['name'] or t['no_name']}"[:256],
            description=t["rating"].format(r=p["rating"], record=record),
            url=f"https://leaderboard.bettermultiplayer.com/player/{p['steam_id']}" if p["steam_id"] else None,
            color=MEDAL_COLORS.get(p["rank"], DEFAULT_COLOR),
        )
        if p["avatar"]:
            embed.set_thumbnail(url=p["avatar"])
        embeds.append(embed)
    return content, embeds


def signature(content: str | None, embeds: list[discord.Embed]) -> tuple:
    """메시지 내용이 같은지 비교하기 위한 값."""
    return (
        content or "",
        tuple(
            (e.title, e.description, e.url, e.thumbnail.url, e.color.value if e.color else None)
            for e in embeds
        ),
    )


def build_pages(players: list[dict], track: int, lang: str) -> list[tuple[str, list[discord.Embed]]]:
    """디스코드는 메시지 하나에 임베드를 10개까지만 넣을 수 있어서 10명씩 나눈다.
    첫 메시지에만 제목 문구를 넣는다."""
    content, embeds = build_message(players, track, lang)
    if not embeds:
        return [(content, [])]
    return [(content if i == 0 else "", embeds[i:i + EMBEDS_PER_MESSAGE])
            for i in range(0, len(embeds), EMBEDS_PER_MESSAGE)]


# ---------------------------------------------------------------- 서버별 채널/메시지 ID 저장
# state.json 형식: {"boards": {"<서버 ID>": {"channel_id": ..., "message_ids": [...], "lang": "ko"}}}

def load_boards(default_channel_id: int | None = None) -> dict:
    try:
        data = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        data = {}
    if "boards" in data:
        boards = data["boards"]
    elif data.get("channel_id"):  # 예전 형식(채널 1개) 호환
        ids = data.get("message_ids") or ([data["message_id"]] if data.get("message_id") else [])
        boards = {"legacy": {"channel_id": data["channel_id"], "message_ids": ids,
                             "lang": data.get("lang", "ko")}}
    else:
        boards = {}
    if not boards and default_channel_id:  # .env/Secrets의 CHANNEL_ID 사용
        boards = {"env": {"channel_id": default_channel_id, "message_ids": [], "lang": "ko"}}
    return boards


def save_boards(boards: dict) -> None:
    STATE_FILE.write_text(json.dumps({"boards": boards}, indent=2) + "\n")


# ---------------------------------------------------------------- 디스코드에 반영

UNKNOWN_CHANNEL = 10003  # 디스코드 오류 코드: 채널이 없어짐


async def delete_messages(channel, message_ids: list[int]) -> None:
    for mid in message_ids:
        try:
            await channel.get_partial_message(mid).delete()
        except discord.HTTPException:
            pass  # 이미 지워졌거나 권한이 없으면 그냥 둔다


async def send_pages(channel, pages) -> list[int]:
    ids = []
    for content, embeds in pages:
        message = await channel.send(content=content, embeds=embeds)
        ids.append(message.id)
    return ids


async def sync_board(client: discord.Client, board: dict, pages) -> str:
    """한 서버의 메시지들을 바뀐 것만 수정한다. 지워진 게 있으면 새로 올린다.
    board["message_ids"]를 직접 고친다."""
    channel = client.get_partial_messageable(board["channel_id"])
    saved_ids = board["message_ids"]

    # 저장된 메시지 확인 (하나라도 지워졌으면 순서가 깨지므로 전부 다시 올린다)
    messages = []
    for mid in saved_ids:
        try:
            messages.append(await channel.fetch_message(mid))
        except discord.NotFound as exc:
            if exc.code == UNKNOWN_CHANNEL:
                raise
    if len(messages) != len(saved_ids) or not saved_ids:
        await delete_messages(channel, [m.id for m in messages])
        board["message_ids"] = await send_pages(channel, pages)
        return f"새 메시지 {len(pages)}개를 보냈습니다" + (" (기존 메시지가 삭제됨)" if saved_ids else "")

    changed = 0
    for message, (content, embeds) in zip(messages, pages):
        if signature(message.content, message.embeds) != signature(content, embeds):
            await message.edit(content=content, embeds=embeds)
            changed += 1
    ids = [m.id for m in messages]
    if len(pages) > len(messages):  # 인원이 늘어 메시지가 더 필요하면 뒤에 추가
        ids += await send_pages(channel, pages[len(messages):])
        changed += 1
    elif len(pages) < len(messages):  # 인원이 줄어 남는 메시지는 삭제
        await delete_messages(channel, ids[len(pages):])
        ids = ids[:len(pages)]
        changed += 1
    board["message_ids"] = ids
    return "순위가 바뀌어 메시지를 수정했습니다" if changed else "변경 없음"


def pages_key(pages) -> tuple:
    return tuple(signature(c, e) for c, e in pages)


async def sync_all(client: discord.Client, default_channel_id: int | None,
                   players: list[dict], track: int, recent: dict | None = None) -> dict[str, str]:
    """모든 서버의 리더보드를 갱신한다. 서버별 결과 문구를 돌려준다.

    recent(계속 실행 모드에서만 사용): 내용이 그대로면 RECHECK_SECONDS 동안은
    디스코드에 확인 요청도 보내지 않아서, 서버가 많아도 요청 수가 적다."""
    boards = load_boards(default_channel_id)
    before = json.dumps(boards, sort_keys=True)
    pages_by_lang: dict[str, list] = {}
    notes: dict[str, str] = {}
    now = time.monotonic()

    for key, board in list(boards.items()):
        lang = board.get("lang", "ko")
        if lang not in pages_by_lang:
            pages_by_lang[lang] = build_pages(players, track, lang)
        pages = pages_by_lang[lang]
        sig = (board["channel_id"], tuple(board["message_ids"]), pages_key(pages))
        if recent is not None and key in recent:
            last_sig, last_time = recent[key]
            if last_sig == sig and now - last_time < RECHECK_SECONDS:
                continue
        try:
            notes[key] = await sync_board(client, board, pages)
            if recent is not None:
                recent[key] = ((board["channel_id"], tuple(board["message_ids"]), pages_key(pages)), now)
        except discord.NotFound as exc:
            if exc.code == UNKNOWN_CHANNEL:
                notes[key] = "채널이 삭제되어 이 서버의 리더보드를 목록에서 뺐습니다"
                del boards[key]
            else:
                notes[key] = f"디스코드 요청 실패: {exc}"
        except discord.Forbidden:
            notes[key] = ("권한 부족: 봇에게 이 채널의 '채널 보기 / 메시지 보내기 / "
                          "링크 첨부 / 메시지 기록 보기' 권한이 있는지 확인하세요.")
        except discord.HTTPException as exc:
            notes[key] = f"디스코드 요청 실패: {exc}"

    if json.dumps(boards, sort_keys=True) != before:
        save_boards(boards)
    return notes


async def post_here(client: discord.Client, guild_id: int,
                    channel: discord.abc.Messageable, players: list[dict],
                    track: int, lang: str) -> None:
    """/리더보드 명령어: 이 채널에 새로 올리고, 같은 서버의 예전 메시지들은 지운다.
    다른 서버의 리더보드는 건드리지 않는다."""
    boards = load_boards()
    key = str(guild_id)
    ids = await send_pages(channel, build_pages(players, track, lang))

    # 같은 서버의 예전 리더보드 찾기 (예전 형식/CHANNEL_ID로 만든 것 포함)
    old = []
    for k, b in list(boards.items()):
        ch = client.get_channel(b["channel_id"]) if hasattr(client, "get_channel") else None
        same_guild = k == key or (k in ("legacy", "env") and getattr(getattr(ch, "guild", None), "id", None) == guild_id)
        if same_guild:
            old.append(b)
            del boards[k]
    boards[key] = {"channel_id": channel.id, "message_ids": ids, "lang": lang}
    save_boards(boards)
    for b in old:
        await delete_messages(client.get_partial_messageable(b["channel_id"]),
                              [m for m in b["message_ids"] if m not in ids])


def remove_board(guild_id: int) -> bool:
    boards = load_boards()
    if boards.pop(str(guild_id), None) is None:
        return False
    save_boards(boards)
    return True


# ---------------------------------------------------------------- 계속 실행 모드 (명령어 지원)

class LeaderboardBot(discord.Client):
    def __init__(self, config: dict):
        super().__init__(intents=discord.Intents(guilds=True), proxy=config["proxy"])
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.last_good: list[dict] | None = None
        self.lock = asyncio.Lock()  # 명령어와 자동 갱신이 동시에 저장 파일을 건드리지 않도록
        self.session: aiohttp.ClientSession | None = None
        self.recent: dict = {}

        self.add_post_command("리더보드", "이 채널에 리더보드를 올리고 계속 갱신합니다", "ko")
        self.add_post_command("leaderboard", "Post the leaderboard in this channel and keep it updated", "en")

    def add_post_command(self, name: str, description: str, lang: str):
        t = TEXT[lang]

        @self.tree.command(name=name, description=description)
        # 관리자에게만 명령어가 보이게 하고(default_permissions),
        # 서버 설정에서 다른 사람에게 열어 줘도 실행할 때 한 번 더 확인한다.
        @app_commands.default_permissions(administrator=True)
        @app_commands.guild_only()
        async def post_cmd(interaction: discord.Interaction):
            perms = getattr(interaction.user, "guild_permissions", None)
            if not (perms and perms.administrator):
                await interaction.response.send_message(t["admin_only"], ephemeral=True)
                log.info("/%s 거부: 관리자가 아닌 %s", name, interaction.user)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.refresh_data()
            if self.last_good is None:
                await interaction.followup.send(t["site_down"])
                return
            try:
                async with self.lock:
                    await post_here(self, interaction.guild_id, interaction.channel,
                                    self.last_good, self.config["track"], lang)
                    self.recent.pop(str(interaction.guild_id), None)
            except discord.Forbidden:
                await interaction.followup.send(t["no_perm"])
                return
            log.info("/%s 실행: [%s] #%s 채널에 올렸습니다", name, interaction.guild, interaction.channel)
            await interaction.followup.send(t["done"].format(s=f"{self.config['interval']:g}"))

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(trust_env=True)
        self.loop.create_task(self.updater())

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    async def sync_commands(self, guild: discord.abc.Snowflake):
        # 서버별로 등록하면 명령어가 바로 나타난다
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self):
        log.info("봇 로그인 성공: %s (서버 %d개)", self.user, len(self.guilds))
        for guild in self.guilds:
            try:
                await self.sync_commands(guild)
                log.info("명령어 등록: %s", guild.name)
            except discord.HTTPException as exc:
                log.warning("명령어 등록 실패 (%s): %s", guild.name, exc)
        if not self.guilds:
            log.warning("봇이 아직 어떤 서버에도 초대되지 않았습니다.")

    async def on_guild_join(self, guild: discord.Guild):
        await self.sync_commands(guild)
        log.info("새 서버에 초대됨, 명령어 등록: %s", guild.name)

    async def on_guild_remove(self, guild: discord.Guild):
        async with self.lock:
            if remove_board(guild.id):
                log.info("서버에서 내보내져 리더보드를 목록에서 뺐습니다: %s", guild.name)

    async def refresh_data(self):
        try:
            self.last_good = await fetch_leaderboard(self.session, self.config["track"])
        except Exception as exc:  # 사이트 접속 실패 → 마지막 정상 데이터 유지
            log.warning("사이트 접속 실패, 마지막 데이터를 유지합니다: %r", exc)

    def board_name(self, key: str) -> str:
        guild = self.get_guild(int(key)) if key.isdigit() else None
        return guild.name if guild else key

    async def updater(self):
        await self.wait_until_ready()
        last_notes: dict[str, str] = {}
        waiting_logged = False
        while not self.is_closed():
            await self.refresh_data()
            if self.last_good is not None:
                async with self.lock:
                    notes = await sync_all(self, self.config["channel_id"], self.last_good,
                                           self.config["track"], self.recent)
                if not load_boards(self.config["channel_id"]) and not waiting_logged:
                    log.info("아직 리더보드를 올린 서버가 없습니다 — 디스코드에서 /리더보드 또는 /leaderboard 를 입력하세요")
                    waiting_logged = True
                for key, note in notes.items():
                    if last_notes.get(key) != note:  # 같은 문구를 반복해서 찍지 않기
                        log.info("[%s] %s", self.board_name(key), note)
                        last_notes[key] = note
            await asyncio.sleep(self.config["interval"])


# ---------------------------------------------------------------- 한 번만 실행 모드 (GitHub Actions)

async def run_once(config: dict) -> None:
    client = discord.Client(intents=discord.Intents.none(), proxy=config["proxy"])
    async with client, aiohttp.ClientSession(trust_env=True) as session:
        await client.login(config["token"])  # 토큰 확인 (틀리면 여기서 오류)
        if not load_boards(config["channel_id"]):
            log.info("아직 리더보드를 올린 서버가 없습니다.")
            return
        try:
            players = await fetch_leaderboard(session, config["track"])
        except Exception as exc:
            log.warning("사이트 접속 실패, 디스코드 메시지는 그대로 둡니다: %r", exc)
            return
        notes = await sync_all(client, config["channel_id"], players, config["track"])
        for key, note in notes.items():
            log.info("[%s] %s", key, note)


async def dry_run() -> None:
    track = int(os.getenv("TRACK", "0") or 0)
    async with aiohttp.ClientSession(trust_env=True) as session:
        players = await fetch_leaderboard(session, track)
    content, embeds = build_message(players, track)
    print(content)
    for e in embeds:
        print(f"  [{e.title}] {e.description}  썸네일={e.thumbnail.url}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="한 번만 갱신하고 종료")
    parser.add_argument("--dry-run", action="store_true", help="디스코드 없이 결과만 출력")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("discord").setLevel(logging.WARNING)
    try:
        if args.dry_run:
            asyncio.run(dry_run())
        elif args.once:
            asyncio.run(run_once(read_config()))
        else:
            config = read_config()
            LeaderboardBot(config).run(config["token"], log_handler=None)
    except discord.LoginFailure:
        sys.exit("봇 토큰이 올바르지 않습니다. DISCORD_TOKEN 값을 확인하세요.")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
