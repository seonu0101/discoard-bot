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

어느 채널의 어떤 메시지를 수정할지는 state.json 파일에 저장됩니다.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

API_URL = "https://leaderboard.bettermultiplayer.com/leaderboard/{track}?limit=10&offset=0"
TRACK_LABELS = {0: "Duel", 1: "United Combat", 2: "Spirit Ashes"}
STATE_FILE = Path(__file__).with_name("state.json")
MEDAL_COLORS = {1: 0xFFD700, 2: 0xC0C0C0, 3: 0xCD7F32}
DEFAULT_COLOR = 0x5865F2

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
    """상위 10명 목록을 가져온다. 실패하면 예외가 난다."""
    url = API_URL.format(track=track)
    timeout = aiohttp.ClientTimeout(total=10)
    headers = {"User-Agent": "leaderboard-discord-bot"}
    async with session.get(url, timeout=timeout, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
    players = []
    for row in data.get("data", [])[:10]:
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
            url=f"https://steamcommunity.com/profiles/{p['steam_id']}" if p["steam_id"] else None,
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


# ---------------------------------------------------------------- 채널/메시지 ID 저장

def load_state(default_channel_id: int | None) -> dict | None:
    try:
        state = json.loads(STATE_FILE.read_text())
        if state.get("channel_id"):
            return state
    except (FileNotFoundError, ValueError):
        pass
    if default_channel_id:
        return {"channel_id": default_channel_id, "message_id": None, "lang": "ko"}
    return None


def save_state(channel_id: int, message_id: int, lang: str) -> None:
    STATE_FILE.write_text(json.dumps(
        {"channel_id": channel_id, "message_id": message_id, "lang": lang}, indent=2) + "\n")


# ---------------------------------------------------------------- 디스코드에 반영

async def sync_message(client: discord.Client, default_channel_id: int | None,
                       players: list[dict], track: int) -> str:
    """저장된 메시지를 내용이 바뀌었을 때만 수정한다. 없으면 새로 만든다."""
    state = load_state(default_channel_id)
    if state is None:
        return "아직 채널이 정해지지 않았습니다 — 디스코드에서 /리더보드 또는 /leaderboard 를 입력하세요"
    lang = state.get("lang", "ko")
    content, embeds = build_message(players, track, lang)
    channel = client.get_partial_messageable(state["channel_id"])

    message = None
    if state.get("message_id"):
        try:
            message = await channel.fetch_message(state["message_id"])
        except discord.NotFound:
            log.info("저장된 메시지(%s)가 삭제되어 새로 만듭니다.", state["message_id"])

    if message is None:
        message = await channel.send(content=content, embeds=embeds)
        save_state(state["channel_id"], message.id, lang)
        return f"새 메시지를 보냈습니다 (채널 {state['channel_id']}, 메시지 {message.id})"

    if signature(message.content, message.embeds) == signature(content, embeds):
        return "변경 없음 — 수정하지 않았습니다"

    await message.edit(content=content, embeds=embeds)
    return "순위가 바뀌어 메시지를 수정했습니다"


async def post_here(client: discord.Client, default_channel_id: int | None,
                    channel: discord.abc.Messageable, players: list[dict],
                    track: int, lang: str) -> None:
    """/리더보드 명령어: 이 채널에 새 메시지를 올리고, 예전 메시지는 지운다."""
    old = load_state(default_channel_id)
    content, embeds = build_message(players, track, lang)
    message = await channel.send(content=content, embeds=embeds)
    save_state(channel.id, message.id, lang)
    if old and old.get("message_id") and old["message_id"] != message.id:
        try:
            await client.get_partial_messageable(old["channel_id"]).get_partial_message(
                old["message_id"]).delete()
        except discord.HTTPException:
            pass  # 이미 지워졌거나 권한이 없으면 그냥 둔다


# ---------------------------------------------------------------- 계속 실행 모드 (명령어 지원)

class LeaderboardBot(discord.Client):
    def __init__(self, config: dict):
        super().__init__(intents=discord.Intents(guilds=True), proxy=config["proxy"])
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.last_good: list[dict] | None = None
        self.lock = asyncio.Lock()  # 명령어와 자동 갱신이 동시에 메시지를 건드리지 않도록
        self.session: aiohttp.ClientSession | None = None

        self.add_post_command("리더보드", "이 채널에 리더보드를 올리고 계속 갱신합니다", "ko")
        self.add_post_command("leaderboard", "Post the leaderboard in this channel and keep it updated", "en")

    def add_post_command(self, name: str, description: str, lang: str):
        t = TEXT[lang]

        @self.tree.command(name=name, description=description)
        @app_commands.default_permissions(manage_channels=True)
        @app_commands.guild_only()
        async def post_cmd(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.refresh_data()
            if self.last_good is None:
                await interaction.followup.send(t["site_down"])
                return
            try:
                async with self.lock:
                    await post_here(self, self.config["channel_id"], interaction.channel,
                                    self.last_good, self.config["track"], lang)
            except discord.Forbidden:
                await interaction.followup.send(t["no_perm"])
                return
            log.info("/%s 실행: #%s 채널에 메시지를 올렸습니다", name, interaction.channel)
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

    async def refresh_data(self):
        try:
            self.last_good = await fetch_leaderboard(self.session, self.config["track"])
        except Exception as exc:  # 사이트 접속 실패 → 마지막 정상 데이터 유지
            log.warning("사이트 접속 실패, 마지막 데이터를 유지합니다: %r", exc)

    async def updater(self):
        await self.wait_until_ready()
        last_note = None
        while not self.is_closed():
            await self.refresh_data()
            if self.last_good is not None:
                try:
                    async with self.lock:
                        note = await sync_message(self, self.config["channel_id"],
                                                  self.last_good, self.config["track"])
                except discord.Forbidden:
                    note = ("권한 부족: 봇에게 이 채널의 '채널 보기 / 메시지 보내기 / "
                            "링크 첨부 / 메시지 기록 보기' 권한이 있는지 확인하세요.")
                except discord.HTTPException as exc:
                    note = f"디스코드 요청 실패: {exc}"
                if note != last_note:  # 같은 문구를 5초마다 반복해서 찍지 않기
                    log.info(note)
                    last_note = note
            await asyncio.sleep(self.config["interval"])


# ---------------------------------------------------------------- 한 번만 실행 모드 (GitHub Actions)

async def run_once(config: dict) -> None:
    client = discord.Client(intents=discord.Intents.none(), proxy=config["proxy"])
    async with client, aiohttp.ClientSession(trust_env=True) as session:
        await client.login(config["token"])  # 토큰 확인 (틀리면 여기서 오류)
        try:
            players = await fetch_leaderboard(session, config["track"])
        except Exception as exc:
            log.warning("사이트 접속 실패, 디스코드 메시지는 그대로 둡니다: %r", exc)
            return
        log.info(await sync_message(client, config["channel_id"], players, config["track"]))


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
