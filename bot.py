"""
BetterMultiplayer 리더보드를 디스코드 임베드로 보여주는 봇.

실행 방법
  python bot.py            계속 켜 두고 5초마다 갱신 (일반 서버/호스팅용)
  python bot.py --once     한 번만 갱신하고 종료 (GitHub Actions용)
  python bot.py --dry-run  디스코드 없이 만들어질 임베드만 화면에 출력 (테스트용)

설정은 .env 파일 또는 환경변수에서 읽습니다.
  DISCORD_TOKEN    봇 토큰 (필수)
  CHANNEL_ID       메시지를 올릴 채널 ID (필수)
  TRACK            0=Duel, 1=United Combat, 2=Spirit Ashes (기본 0)
  UPDATE_INTERVAL  갱신 간격(초), 계속 실행 모드에서만 사용 (기본 5)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv

API_URL = "https://leaderboard.bettermultiplayer.com/leaderboard/{track}?limit=10&offset=0"
TRACK_LABELS = {0: "Duel", 1: "United Combat", 2: "Spirit Ashes"}
MESSAGE_ID_FILE = Path(__file__).with_name("message_id.txt")
MEDAL_COLORS = {1: 0xFFD700, 2: 0xC0C0C0, 3: 0xCD7F32}
DEFAULT_COLOR = 0x5865F2

log = logging.getLogger("leaderboard-bot")


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
            "name": (p.get("persona_name") or "").strip() or "(이름 없음)",
            "avatar": p.get("avatar_url") or None,
            "steam_id": p.get("steam_id"),
            "rating": row.get("rating"),
            "wins": row.get("wins", 0),
            "losses": row.get("losses", 0),
            "draws": row.get("draws", 0),
        })
    return players


# ---------------------------------------------------------------- 임베드 만들기

def build_message(players: list[dict], track: int) -> tuple[str, list[discord.Embed]]:
    label = TRACK_LABELS.get(track, f"Track {track}")
    content = f"🏆 **{label} 리더보드** 상위 {len(players)}명"
    if not players:
        content = f"🏆 **{label} 리더보드** — 아직 순위 데이터가 없습니다."
    embeds = []
    for p in players:
        record = f"{p['wins']}승 {p['losses']}패"
        if p["draws"]:
            record += f" {p['draws']}무"
        embed = discord.Embed(
            title=f"#{p['rank']}  {p['name']}"[:256],
            description=f"레이팅 **{p['rating']}** · {record}",
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


# ---------------------------------------------------------------- 메시지 ID 저장

def load_message_id() -> int | None:
    try:
        return int(MESSAGE_ID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def save_message_id(message_id: int) -> None:
    MESSAGE_ID_FILE.write_text(f"{message_id}\n")


# ---------------------------------------------------------------- 디스코드에 반영

async def sync_message(channel: discord.PartialMessageable, content: str,
                       embeds: list[discord.Embed]) -> str:
    """메시지를 새로 만들거나, 내용이 바뀌었을 때만 수정한다."""
    message = None
    message_id = load_message_id()
    if message_id:
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            log.info("저장된 메시지(%s)가 삭제되어 새로 만듭니다.", message_id)

    if message is None:
        message = await channel.send(content=content, embeds=embeds)
        save_message_id(message.id)
        return f"새 메시지를 보냈습니다 (ID {message.id})"

    if signature(message.content, message.embeds) == signature(content, embeds):
        return "변경 없음 — 수정하지 않았습니다"

    await message.edit(content=content, embeds=embeds)
    return "순위가 바뀌어 메시지를 수정했습니다"


# ---------------------------------------------------------------- 실행

def read_config() -> tuple[str, int, int, float]:
    load_dotenv(Path(__file__).with_name(".env"))
    token = os.getenv("DISCORD_TOKEN", "").strip()
    channel_id = os.getenv("CHANNEL_ID", "").strip()
    if not token or not channel_id:
        sys.exit("DISCORD_TOKEN 또는 CHANNEL_ID가 비어 있습니다. .env 파일(또는 GitHub Secrets)을 확인하세요.")
    if not channel_id.isdigit():
        sys.exit("CHANNEL_ID는 숫자여야 합니다.")
    track = int(os.getenv("TRACK", "0") or 0)
    interval = float(os.getenv("UPDATE_INTERVAL", "5") or 5)
    return token, int(channel_id), track, max(interval, 2.0)


async def dry_run() -> None:
    track = int(os.getenv("TRACK", "0") or 0)
    async with aiohttp.ClientSession(trust_env=True) as session:
        players = await fetch_leaderboard(session, track)
    content, embeds = build_message(players, track)
    print(content)
    for e in embeds:
        print(f"  [{e.title}] {e.description}  썸네일={e.thumbnail.url}")


async def run(once: bool) -> None:
    token, channel_id, track, interval = read_config()
    # 프록시가 있는 환경(일부 클라우드)에서도 동작하도록
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or None
    client = discord.Client(intents=discord.Intents.none(), proxy=proxy)
    last_good: list[dict] | None = None

    async with client, aiohttp.ClientSession(trust_env=True) as session:
        await client.login(token)  # 토큰 확인 (틀리면 여기서 오류)
        channel = client.get_partial_messageable(channel_id)
        log.info("봇 로그인 성공: %s / 채널 %s", client.user, channel_id)

        while True:
            try:
                last_good = await fetch_leaderboard(session, track)
            except Exception as exc:  # 사이트 접속 실패 → 마지막 정상 데이터 유지
                log.warning("사이트 접속 실패, 마지막 데이터를 유지합니다: %r", exc)

            if last_good is not None:
                content, embeds = build_message(last_good, track)
                try:
                    log.info(await sync_message(channel, content, embeds))
                except discord.Forbidden:
                    log.error("권한 부족: 봇에게 이 채널의 '채널 보기 / 메시지 보내기 / "
                              "링크 첨부 / 메시지 기록 보기' 권한이 있는지 확인하세요.")
                    if once:
                        raise
                except discord.HTTPException as exc:
                    log.warning("디스코드 요청 실패: %s", exc)
                    if once:
                        raise

            if once:
                return
            await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="한 번만 갱신하고 종료")
    parser.add_argument("--dry-run", action="store_true", help="디스코드 없이 결과만 출력")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("discord").setLevel(logging.WARNING)
    try:
        asyncio.run(dry_run() if args.dry_run else run(args.once))
    except discord.LoginFailure:
        sys.exit("봇 토큰이 올바르지 않습니다. DISCORD_TOKEN 값을 확인하세요.")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
