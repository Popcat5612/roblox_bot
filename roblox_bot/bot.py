import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

from roblox_api import (
    RobloxAPIError,
    escape_markdown,
    format_number,
    get_game,
    get_game_icon,
    get_game_votes,
    get_group_games,
    get_group_icon,
    get_group_profile,
    get_recommendations,
    get_user_avatar,
    get_user_count,
    get_user_games,
    get_user_profile,
    is_valid_universe_id,
    resolve_universe_id,
    search_groups,
    search_games,
    search_users,
)


load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()

if not TOKEN:
    raise RuntimeError(".env 파일에 DISCORD_TOKEN을 입력하세요.")


class RobloxDiscordBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents(guilds=True))
        self.tree = app_commands.CommandTree(self)
        self.roblox_session: aiohttp.ClientSession | None = None
        self.favorite_db: sqlite3.Connection | None = None

    async def setup_hook(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        self.roblox_session = aiohttp.ClientSession(timeout=timeout)
        db_path = os.getenv("FAVORITES_DB_PATH")
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            db_path = str(Path(__file__).with_name("favorites.sqlite3"))
        self.favorite_db = sqlite3.connect(db_path)
        self.favorite_db.execute(
            """CREATE TABLE IF NOT EXISTS favorites (
                discord_user_id TEXT NOT NULL,
                universe_id TEXT NOT NULL,
                game_name TEXT NOT NULL,
                root_place_id TEXT,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (discord_user_id, universe_id)
            )"""
        )
        self.favorite_db.commit()

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("서버 %s에 슬래시 명령어를 등록했습니다.", GUILD_ID)
        else:
            await self.tree.sync()
            logging.info("전역 슬래시 명령어를 등록했습니다.")

    async def close(self) -> None:
        if self.roblox_session and not self.roblox_session.closed:
            await self.roblox_session.close()
        if self.favorite_db:
            self.favorite_db.close()
            self.favorite_db = None
        await super().close()


bot = RobloxDiscordBot()


def format_date(value: str | None) -> str:
    if not value:
        return "알 수 없음"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


async def game_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.strip()
    if not current or bot.roblox_session is None:
        return []

    try:
        if is_valid_universe_id(current):
            game = await get_game(bot.roblox_session, current)
            if not game:
                return []
            title = str(game.get("name") or "이름 없는 게임")
            return [app_commands.Choice(name=title[:100], value=current)]

        games = await search_games(bot.roblox_session, current)
        choices = []
        for game in games[:25]:
            universe_id = game.get("universeId")
            if universe_id is None:
                continue
            title = str(game.get("name") or "이름 없는 게임")
            creator = str(game.get("creatorName") or "").strip()
            players = game.get("playerCount")
            label = f"{title} — {creator}" if creator else title
            if players is not None:
                label += f" · {format_number(players)}명 플레이 중"
            choices.append(
                app_commands.Choice(name=label[:100], value=str(universe_id))
            )
        return choices
    except RobloxAPIError:
        logging.exception("게임 검색 자동완성에 실패했습니다.")
        return []


@bot.tree.command(name="game", description="Roblox 게임 정보를 조회합니다")
@app_commands.describe(game="게임 이름을 한국어 또는 영어로 입력하거나 Universe ID를 입력하세요")
@app_commands.autocomplete(game=game_autocomplete)
async def game_command(interaction: discord.Interaction, game: str) -> None:
    game = game.strip()
    if not game:
        await interaction.response.send_message(
            "게임 이름을 입력해 주세요.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        assert bot.roblox_session is not None
        universe_id = await resolve_universe_id(bot.roblox_session, game)
        if not universe_id:
            await interaction.edit_original_response(
                content="게임을 찾지 못했어요. 한글이나 영어 이름으로 다시 검색해 주세요."
            )
            return
        game = await get_game(bot.roblox_session, universe_id)
        if not game:
            await interaction.edit_original_response(
                content="해당 Universe ID의 공개 게임을 찾지 못했어요."
            )
            return

        description = str(game.get("description") or "설명이 등록되지 않았어요.")[:1000]
        embed = discord.Embed(
            title=str(game.get("name") or "이름 없는 게임")[:256],
            description=description,
            color=discord.Color.blue(),
            url=(
                f"https://www.roblox.com/games/{game['rootPlaceId']}"
                if game.get("rootPlaceId")
                else None
            ),
        )
        embed.add_field(
            name="현재 접속자", value=format_number(game.get("playing")), inline=True
        )
        embed.add_field(name="누적 방문 수", value=format_number(game.get("visits")), inline=True)
        embed.add_field(
            name="즐겨찾기", value=format_number(game.get("favoritedCount")), inline=True
        )
        creator = game.get("creator") or {}
        embed.add_field(name="제작자", value=str(creator.get("name") or "알 수 없음")[:1024], inline=True)
        embed.add_field(name="최대 인원", value=format_number(game.get("maxPlayers")), inline=True)
        embed.add_field(name="장르", value=str(game.get("genre") or "알 수 없음")[:1024], inline=True)
        embed.add_field(name="생성일", value=format_date(game.get("created")), inline=True)
        embed.add_field(name="최근 업데이트", value=format_date(game.get("updated")), inline=True)
        try:
            votes = await get_game_votes(bot.roblox_session, universe_id)
            up_votes = int(votes.get("upVotes", 0))
            down_votes = int(votes.get("downVotes", 0))
            vote_total = up_votes + down_votes
            if vote_total:
                percentage = up_votes / vote_total * 100
                embed.add_field(
                    name="좋아요 비율",
                    value=(
                        f"{percentage:.1f}% · 👍 {format_number(up_votes)}"
                        f" / 👎 {format_number(down_votes)}"
                    ),
                    inline=False,
                )
        except RobloxAPIError:
            logging.warning("게임 평가 정보를 가져오지 못했습니다.")
        embed.set_footer(text=f"Universe ID: {universe_id}")
        try:
            icon_url = await get_game_icon(bot.roblox_session, universe_id)
            if icon_url:
                embed.set_thumbnail(url=icon_url)
        except RobloxAPIError:
            logging.warning("게임 아이콘을 가져오지 못했습니다. 정보는 계속 표시합니다.")
        await interaction.edit_original_response(content=None, embed=embed)
    except RobloxAPIError as error:
        await interaction.edit_original_response(content=str(error))
    except Exception:
        logging.exception("게임 정보 명령을 처리하지 못했습니다.")
        await interaction.edit_original_response(
            content="게임 정보를 가져오지 못했어요. 잠시 후 다시 시도해 주세요."
        )


@bot.tree.command(name="recommend", description="비슷한 Roblox 게임을 추천합니다")
@app_commands.describe(game="게임 이름을 한국어 또는 영어로 입력하거나 Universe ID를 입력하세요")
@app_commands.autocomplete(game=game_autocomplete)
async def recommend_command(interaction: discord.Interaction, game: str) -> None:
    game = game.strip()
    if not game:
        await interaction.response.send_message(
            "게임 이름을 입력해 주세요.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        assert bot.roblox_session is not None
        universe_id = await resolve_universe_id(bot.roblox_session, game)
        if not universe_id:
            await interaction.edit_original_response(
                content="게임을 찾지 못했어요. 한글이나 영어 이름으로 다시 검색해 주세요."
            )
            return
        games = await get_recommendations(bot.roblox_session, universe_id)
        recommendations = games[:5]
        if not recommendations:
            await interaction.edit_original_response(
                content="이 게임과 비슷한 추천 게임을 찾지 못했어요."
            )
            return

        lines = []
        for index, game in enumerate(recommendations, start=1):
            name = escape_markdown(game.get("name") or "이름 없는 게임")
            place_id = game.get("rootPlaceId") or game.get("placeId")
            if place_id:
                name = f"[{name}](https://www.roblox.com/games/{place_id})"
            line = f"{index}. {name}"
            if game.get("playing") is not None:
                line += f" · 플레이 중 {format_number(game['playing'])}명"
            lines.append(line)

        embed = discord.Embed(
            title="Roblox 게임 추천",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"기준 Universe ID: {universe_id}")
        await interaction.edit_original_response(content=None, embed=embed)
    except RobloxAPIError as error:
        await interaction.edit_original_response(content=str(error))
    except Exception:
        logging.exception("게임 추천 명령을 처리하지 못했습니다.")
        await interaction.edit_original_response(
            content="게임 추천을 가져오지 못했어요. 잠시 후 다시 시도해 주세요."
        )


async def user_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.strip()
    if not current or bot.roblox_session is None:
        return []
    try:
        users = await search_users(bot.roblox_session, current)
        choices = []
        for user in users[:25]:
            user_id = user.get("id")
            if user_id is None:
                continue
            username = str(user.get("name") or "Unknown")
            display_name = str(user.get("displayName") or username)
            label = f"{display_name} (@{username})"
            choices.append(app_commands.Choice(name=label[:100], value=str(user_id)))
        return choices
    except RobloxAPIError:
        logging.exception("유저 자동완성 검색에 실패했습니다.")
        return []


async def creator_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.strip()
    if not current or bot.roblox_session is None:
        return []

    user_results, group_results = await asyncio.gather(
        search_users(bot.roblox_session, current),
        search_groups(bot.roblox_session, current),
        return_exceptions=True,
    )
    choices: list[app_commands.Choice[str]] = []
    if not isinstance(user_results, Exception):
        for user in user_results[:10]:
            user_id = user.get("id")
            if user_id is None:
                continue
            username = str(user.get("name") or "Unknown")
            display_name = str(user.get("displayName") or username)
            label = f"유저: {display_name} (@{username})"
            choices.append(
                app_commands.Choice(name=label[:100], value=f"user:{user_id}")
            )
    if not isinstance(group_results, Exception):
        for group in group_results[:10]:
            group_id = group.get("id")
            if group_id is None:
                continue
            group_name = str(group.get("name") or "이름 없는 그룹")
            label = f"그룹: {group_name} · 멤버 {format_number(group.get('memberCount'))}명"
            choices.append(
                app_commands.Choice(name=label[:100], value=f"group:{group_id}")
            )
    return choices[:25]


async def resolve_creator_selection(
    query: str,
) -> tuple[str, str] | None:
    query = query.strip()
    if ":" in query:
        kind, value = query.split(":", 1)
        if kind in {"user", "group"} and value.isdigit():
            return kind, value
    if query.isdigit():
        return "user", query
    if bot.roblox_session is None:
        return None

    user_results, group_results = await asyncio.gather(
        search_users(bot.roblox_session, query),
        search_groups(bot.roblox_session, query),
        return_exceptions=True,
    )
    users = [] if isinstance(user_results, Exception) else user_results
    groups = [] if isinstance(group_results, Exception) else group_results
    normalized = query.casefold()

    for user in users:
        if normalized in {
            str(user.get("name") or "").casefold(),
            str(user.get("displayName") or "").casefold(),
        }:
            return "user", str(user["id"])
    for group in groups:
        if normalized == str(group.get("name") or "").casefold():
            return "group", str(group["id"])
    if users:
        return "user", str(users[0]["id"])
    if groups:
        return "group", str(groups[0]["id"])
    return None


def creator_game_link(game: dict) -> str | None:
    root_place = game.get("rootPlace") or {}
    place_id = game.get("rootPlaceId") or root_place.get("id")
    return f"https://www.roblox.com/games/{place_id}" if place_id else None


@bot.tree.command(name="user", description="Roblox 사용자 프로필을 조회합니다")
@app_commands.describe(username="Roblox 사용자 이름 또는 표시 이름")
@app_commands.autocomplete(username=user_autocomplete)
async def user_command(interaction: discord.Interaction, username: str) -> None:
    username = username.strip()
    if not username:
        await interaction.response.send_message("사용자 이름을 입력해 주세요.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)

    try:
        assert bot.roblox_session is not None
        if username.isdigit():
            user_id = username
        else:
            users = await search_users(bot.roblox_session, username)
            if not users:
                await interaction.edit_original_response(
                    content="Roblox 사용자를 찾지 못했어요."
                )
                return
            normalized = username.casefold()
            selected = next(
                (
                    user
                    for user in users
                    if normalized
                    in {
                        str(user.get("name") or "").casefold(),
                        str(user.get("displayName") or "").casefold(),
                    }
                ),
                users[0],
            )
            user_id = str(selected["id"])

        profile, avatar, followers, friends = await asyncio.gather(
            get_user_profile(bot.roblox_session, user_id),
            get_user_avatar(bot.roblox_session, user_id),
            get_user_count(bot.roblox_session, user_id, "followers"),
            get_user_count(bot.roblox_session, user_id, "friends"),
            return_exceptions=True,
        )
        if isinstance(profile, Exception):
            raise profile
        if not profile:
            await interaction.edit_original_response(content="Roblox 사용자를 찾지 못했어요.")
            return

        name = str(profile.get("name") or "Unknown")
        display_name = str(profile.get("displayName") or name)
        badge = " ✓" if profile.get("hasVerifiedBadge") else ""
        embed = discord.Embed(
            title=f"{display_name}{badge}",
            description=str(profile.get("description") or "소개가 등록되지 않았어요.")[:1000],
            url=f"https://www.roblox.com/users/{user_id}/profile",
            color=discord.Color.blue(),
        )
        embed.add_field(name="사용자 이름", value=f"@{name}"[:1024], inline=True)
        embed.add_field(name="가입일", value=format_date(profile.get("created")), inline=True)
        embed.add_field(
            name="팔로워",
            value=format_number(followers) if not isinstance(followers, Exception) else "정보 없음",
            inline=True,
        )
        embed.add_field(
            name="친구",
            value=format_number(friends) if not isinstance(friends, Exception) else "정보 없음",
            inline=True,
        )
        embed.set_footer(text=f"Roblox User ID: {user_id}")
        if isinstance(avatar, str) and avatar:
            embed.set_thumbnail(url=avatar)
        await interaction.edit_original_response(content=None, embed=embed)
    except RobloxAPIError as error:
        await interaction.edit_original_response(content=str(error))
    except Exception:
        logging.exception("유저 프로필 명령을 처리하지 못했습니다.")
        await interaction.edit_original_response(
            content="사용자 프로필을 가져오지 못했어요. 잠시 후 다시 시도해 주세요."
        )


@bot.tree.command(name="creator", description="Roblox 유저 또는 그룹 제작자의 게임을 조회합니다")
@app_commands.describe(creator="Roblox 사용자 이름 또는 그룹 이름")
@app_commands.autocomplete(creator=creator_autocomplete)
async def creator_command(interaction: discord.Interaction, creator: str) -> None:
    creator = creator.strip()
    if not creator:
        await interaction.response.send_message("제작자 이름을 입력해 주세요.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)

    try:
        assert bot.roblox_session is not None
        selection = await resolve_creator_selection(creator)
        if not selection:
            await interaction.edit_original_response(
                content="제작자를 찾지 못했어요. 유저 또는 그룹 자동완성 결과를 선택해 주세요."
            )
            return

        kind, creator_id = selection
        if kind == "group":
            profile, games = await asyncio.gather(
                get_group_profile(bot.roblox_session, creator_id),
                get_group_games(bot.roblox_session, creator_id),
            )
            if not profile:
                await interaction.edit_original_response(content="그룹을 찾지 못했어요.")
                return
            title = str(profile.get("name") or "이름 없는 그룹")
            description = str(profile.get("description") or "그룹 소개가 등록되지 않았어요.")
            owner = profile.get("owner") or {}
            embed = discord.Embed(
                title=title[:256],
                description=description[:1000],
                url=f"https://www.roblox.com/groups/{creator_id}",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="멤버 수", value=format_number(profile.get("memberCount")), inline=True
            )
            if owner.get("username"):
                embed.add_field(name="그룹 소유자", value=str(owner["username"])[:1024], inline=True)
            try:
                icon = await get_group_icon(bot.roblox_session, creator_id)
                if icon:
                    embed.set_thumbnail(url=icon)
            except RobloxAPIError:
                logging.warning("그룹 아이콘을 가져오지 못했습니다.")
        else:
            profile, games = await asyncio.gather(
                get_user_profile(bot.roblox_session, creator_id),
                get_user_games(bot.roblox_session, creator_id),
            )
            if not profile:
                await interaction.edit_original_response(content="사용자를 찾지 못했어요.")
                return
            username_value = str(profile.get("name") or "Unknown")
            title = str(profile.get("displayName") or username_value)
            description = str(profile.get("description") or "소개가 등록되지 않았어요.")
            embed = discord.Embed(
                title=title[:256],
                description=description[:1000],
                url=f"https://www.roblox.com/users/{creator_id}/profile",
                color=discord.Color.blue(),
            )
            embed.add_field(name="사용자 이름", value=f"@{username_value}"[:1024], inline=True)
            try:
                avatar = await get_user_avatar(bot.roblox_session, creator_id)
                if avatar:
                    embed.set_thumbnail(url=avatar)
            except RobloxAPIError:
                logging.warning("제작자 아바타를 가져오지 못했습니다.")

        if games:
            for game in games[:5]:
                name = str(game.get("name") or "이름 없는 게임")
                link = creator_game_link(game)
                visits = game.get("placeVisits", game.get("visits"))
                value = f"방문 {format_number(visits)}"
                if link:
                    value += f" · [게임 열기]({link})"
                embed.add_field(name=name[:256], value=value[:1024], inline=False)
        else:
            embed.add_field(name="공개 게임", value="공개된 게임을 찾지 못했어요.", inline=False)

        embed.set_footer(text=f"공개 제작자 프로필 · ID: {creator_id}")
        await interaction.edit_original_response(content=None, embed=embed)
    except RobloxAPIError as error:
        await interaction.edit_original_response(content=str(error))
    except Exception:
        logging.exception("제작자 명령을 처리하지 못했습니다.")
        await interaction.edit_original_response(
            content="제작자 정보를 가져오지 못했어요. 잠시 후 다시 시도해 주세요."
        )


favorites = app_commands.Group(
    name="favorites", description="내 Roblox 게임 즐겨찾기를 관리합니다"
)


async def favorite_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if bot.favorite_db is None:
        return []
    query = current.strip().casefold()
    rows = bot.favorite_db.execute(
        "SELECT universe_id, game_name FROM favorites WHERE discord_user_id = ? ORDER BY added_at DESC LIMIT 100",
        (str(interaction.user.id),),
    ).fetchall()
    choices = []
    for universe_id, game_name in rows:
        if query and query not in str(game_name).casefold() and query not in str(universe_id):
            continue
        choices.append(
            app_commands.Choice(name=str(game_name)[:100], value=str(universe_id))
        )
        if len(choices) == 25:
            break
    return choices


@favorites.command(name="add", description="게임을 즐겨찾기에 저장합니다")
@app_commands.describe(game="저장할 게임 이름")
@app_commands.autocomplete(game=game_autocomplete)
async def favorites_add(interaction: discord.Interaction, game: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        assert bot.roblox_session is not None and bot.favorite_db is not None
        universe_id = await resolve_universe_id(bot.roblox_session, game)
        if not universe_id:
            await interaction.edit_original_response(content="게임을 찾지 못했어요.")
            return
        result = await get_game(bot.roblox_session, universe_id)
        if not result:
            await interaction.edit_original_response(content="게임 정보를 찾지 못했어요.")
            return
        cursor = bot.favorite_db.execute(
            "INSERT OR IGNORE INTO favorites (discord_user_id, universe_id, game_name, root_place_id) VALUES (?, ?, ?, ?)",
            (
                str(interaction.user.id),
                universe_id,
                str(result.get("name") or "이름 없는 게임"),
                str(result.get("rootPlaceId") or ""),
            ),
        )
        bot.favorite_db.commit()
        if cursor.rowcount:
            message = f"**{result.get('name', '게임')}**을(를) 즐겨찾기에 저장했어요."
        else:
            message = "이미 즐겨찾기에 저장된 게임이에요."
        await interaction.edit_original_response(content=message)
    except RobloxAPIError as error:
        await interaction.edit_original_response(content=str(error))
    except Exception:
        logging.exception("즐겨찾기를 저장하지 못했습니다.")
        await interaction.edit_original_response(
            content="즐겨찾기를 저장하지 못했어요. 잠시 후 다시 시도해 주세요."
        )


@favorites.command(name="remove", description="즐겨찾기에서 게임을 삭제합니다")
@app_commands.describe(game="삭제할 게임")
@app_commands.autocomplete(game=favorite_autocomplete)
async def favorites_remove(interaction: discord.Interaction, game: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    if bot.favorite_db is None:
        await interaction.edit_original_response(content="즐겨찾기 저장소를 사용할 수 없어요.")
        return
    query = game.strip()
    if not query.isdigit():
        row = bot.favorite_db.execute(
            "SELECT universe_id FROM favorites WHERE discord_user_id = ? AND lower(game_name) = lower(?) LIMIT 1",
            (str(interaction.user.id), query),
        ).fetchone()
        if not row:
            await interaction.edit_original_response(content="즐겨찾기 목록에서 게임을 선택해 주세요.")
            return
        query = str(row[0])
    cursor = bot.favorite_db.execute(
        "DELETE FROM favorites WHERE discord_user_id = ? AND universe_id = ?",
        (str(interaction.user.id), query),
    )
    bot.favorite_db.commit()
    message = "즐겨찾기에서 삭제했어요." if cursor.rowcount else "저장된 게임을 찾지 못했어요."
    await interaction.edit_original_response(content=message)


@favorites.command(name="list", description="저장한 게임 목록을 보여줍니다")
async def favorites_list(interaction: discord.Interaction) -> None:
    if bot.favorite_db is None:
        await interaction.response.send_message("즐겨찾기 저장소를 사용할 수 없어요.", ephemeral=True)
        return
    rows = bot.favorite_db.execute(
        "SELECT universe_id, game_name, root_place_id FROM favorites WHERE discord_user_id = ? ORDER BY added_at DESC LIMIT 25",
        (str(interaction.user.id),),
    ).fetchall()
    if not rows:
        await interaction.response.send_message(
            "즐겨찾기가 비어 있어요. `/favorites add`로 게임을 저장해 보세요.",
            ephemeral=True,
        )
        return
    lines = []
    for index, (universe_id, game_name, place_id) in enumerate(rows, start=1):
        label = escape_markdown(game_name)
        if place_id:
            label = f"[{label}](https://www.roblox.com/games/{place_id})"
        lines.append(f"{index}. {label}")
    embed = discord.Embed(
        title=f"{interaction.user.display_name}님의 즐겨찾기",
        description="\n".join(lines),
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(favorites)


@bot.event
async def on_ready() -> None:
    logging.info("%s 봇이 온라인입니다.", bot.user)


def run_bot() -> None:
    bot.run(TOKEN)


if __name__ == "__main__":
    run_bot()
