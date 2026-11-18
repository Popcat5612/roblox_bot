import asyncio
import re
from time import monotonic
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import aiohttp


GAMES_API = "https://games.roblox.com/v1/games"
SEARCH_API = "https://apis.roblox.com/search-api/omni-search"
THUMBNAILS_API = "https://thumbnails.roblox.com/v1/games/icons"
USERS_API = "https://users.roblox.com/v1"
GROUPS_API = "https://groups.roblox.com/v1"
GAMES_BY_USER_API = "https://games.roblox.com/v2/users"
GAMES_BY_GROUP_API = "https://games.roblox.com/v2/groups"

_REQUEST_INTERVAL_SECONDS = 0.35
_RESPONSE_CACHE_TTL_SECONDS = 45
_RESPONSE_CACHE_LIMIT = 512
_response_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_request_lock = asyncio.Lock()
_next_request_at = 0.0
_rate_limited_until = 0.0


class RobloxAPIError(Exception):
    """Raised when the public Roblox Games API cannot return usable data."""


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    global _next_request_at, _rate_limited_until

    cache_key = re.sub(r"([?&]sessionId=)[^&]+", r"\1search-session", url)
    now = monotonic()
    cached = _response_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    async with _request_lock:
        while True:
            now = monotonic()
            cached = _response_cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]
            if _rate_limited_until > now:
                wait_seconds = int(_rate_limited_until - now + 0.999)
                raise RobloxAPIError(
                    f"Roblox API가 잠시 요청을 제한 중이에요. 약 {wait_seconds}초 후 다시 시도해 주세요."
                )
            delay = _next_request_at - now
            if delay <= 0:
                _next_request_at = now + _REQUEST_INTERVAL_SECONDS
                break
            await asyncio.sleep(delay)

    try:
        async with session.get(url, headers={"Accept": "application/json"}) as response:
            if response.status == 429:
                retry_after = response.headers.get("Retry-After", "30")
                try:
                    cooldown = min(max(float(retry_after), 5.0), 60.0)
                except ValueError:
                    cooldown = 30.0
                _rate_limited_until = max(
                    _rate_limited_until, monotonic() + cooldown
                )
                raise RobloxAPIError(
                    f"Roblox API가 요청을 제한 중이에요. 약 {int(cooldown)}초 후 다시 시도해 주세요."
                )
            if response.status >= 400:
                raise RobloxAPIError(f"Roblox API 요청 실패 (HTTP {response.status})")
            result = await response.json(content_type=None)
    except aiohttp.ClientError as error:
        raise RobloxAPIError("Roblox API에 연결하지 못했어요.") from error
    except TimeoutError as error:
        raise RobloxAPIError("Roblox API 응답 시간이 초과됐어요.") from error

    now = monotonic()
    if len(_response_cache) >= _RESPONSE_CACHE_LIMIT:
        expired = [key for key, (expires_at, _) in _response_cache.items() if expires_at <= now]
        for key in expired:
            _response_cache.pop(key, None)
        if len(_response_cache) >= _RESPONSE_CACHE_LIMIT:
            _response_cache.pop(next(iter(_response_cache)))
    _response_cache[cache_key] = (now + _RESPONSE_CACHE_TTL_SECONDS, result)
    return result


def is_valid_universe_id(value: str) -> bool:
    return re.fullmatch(r"\d{1,20}", value) is not None


async def get_game(
    session: aiohttp.ClientSession, universe_id: str
) -> dict[str, Any] | None:
    url = f"{GAMES_API}?{urlencode({'universeIds': universe_id})}"
    result = await _get_json(session, url)
    games = result.get("data", [])
    return games[0] if games else None


async def get_game_icon(
    session: aiohttp.ClientSession, universe_id: str
) -> str | None:
    params = urlencode(
        {
            "universeIds": universe_id,
            "size": "512x512",
            "format": "Png",
            "isCircular": "false",
        }
    )
    result = await _get_json(session, f"{THUMBNAILS_API}?{params}")
    icons = result.get("data", [])
    if not icons:
        return None
    return icons[0].get("imageUrl")


async def get_game_votes(
    session: aiohttp.ClientSession, universe_id: str
) -> dict[str, Any]:
    return await _get_json(session, f"{GAMES_API}/{universe_id}/votes")


async def search_games(
    session: aiohttp.ClientSession, query: str
) -> list[dict[str, Any]]:
    query = query.strip()[:100]
    if not query:
        return []

    params = urlencode(
        {
            "searchQuery": query,
            "sessionId": str(uuid4()),
            "pageType": "all",
        }
    )
    result = await _get_json(session, f"{SEARCH_API}?{params}")

    games: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for group in result.get("searchResults", []):
        if group.get("contentGroupType") != "Game":
            continue
        for game in group.get("contents", []):
            universe_id = game.get("universeId")
            if universe_id is None or str(universe_id) in seen_ids:
                continue
            seen_ids.add(str(universe_id))
            games.append(game)
    return games


async def search_users(
    session: aiohttp.ClientSession, query: str
) -> list[dict[str, Any]]:
    params = urlencode({"keyword": query.strip()[:100], "limit": 10})
    result = await _get_json(session, f"{USERS_API}/users/search?{params}")
    users = result.get("data", [])
    return users if isinstance(users, list) else []


async def get_user_profile(
    session: aiohttp.ClientSession, user_id: str
) -> dict[str, Any] | None:
    try:
        return await _get_json(session, f"{USERS_API}/users/{user_id}")
    except RobloxAPIError as error:
        if "HTTP 404" in str(error):
            return None
        raise


async def get_user_games(
    session: aiohttp.ClientSession, user_id: str
) -> list[dict[str, Any]]:
    params = urlencode({"accessFilter": "Public", "limit": 10, "sortOrder": "Desc"})
    result = await _get_json(session, f"{GAMES_BY_USER_API}/{user_id}/games?{params}")
    games = result.get("data", [])
    return games if isinstance(games, list) else []


async def search_groups(
    session: aiohttp.ClientSession, query: str
) -> list[dict[str, Any]]:
    params = urlencode({"keyword": query.strip()[:100], "limit": 10})
    result = await _get_json(session, f"{GROUPS_API}/groups/search?{params}")
    groups = result.get("data", [])
    return groups if isinstance(groups, list) else []


async def get_group_profile(
    session: aiohttp.ClientSession, group_id: str
) -> dict[str, Any] | None:
    try:
        return await _get_json(session, f"{GROUPS_API}/groups/{group_id}")
    except RobloxAPIError as error:
        if "HTTP 404" in str(error):
            return None
        raise


async def get_group_games(
    session: aiohttp.ClientSession, group_id: str
) -> list[dict[str, Any]]:
    params = urlencode({"accessFilter": "Public", "limit": 10, "sortOrder": "Desc"})
    url = f"{GAMES_BY_GROUP_API}/{group_id}/gamesV2?{params}"
    result = await _get_json(session, url)
    games = result.get("data", [])
    return games if isinstance(games, list) else []


async def get_user_avatar(
    session: aiohttp.ClientSession, user_id: str
) -> str | None:
    params = urlencode(
        {"userIds": user_id, "size": "150x150", "format": "Png", "isCircular": "true"}
    )
    result = await _get_json(
        session, f"https://thumbnails.roblox.com/v1/users/avatar-headshot?{params}"
    )
    items = result.get("data", [])
    return items[0].get("imageUrl") if items else None


async def get_group_icon(
    session: aiohttp.ClientSession, group_id: str
) -> str | None:
    params = urlencode(
        {"groupIds": group_id, "size": "150x150", "format": "Png", "isCircular": "false"}
    )
    result = await _get_json(
        session, f"https://thumbnails.roblox.com/v1/groups/icons?{params}"
    )
    items = result.get("data", [])
    return items[0].get("imageUrl") if items else None


async def get_user_count(
    session: aiohttp.ClientSession, user_id: str, count_type: str
) -> int | None:
    url = f"https://friends.roblox.com/v1/users/{user_id}/{count_type}/count"
    result = await _get_json(session, url)
    count = result.get("count")
    return int(count) if count is not None else None


async def resolve_universe_id(
    session: aiohttp.ClientSession, query: str
) -> str | None:
    query = query.strip()
    if is_valid_universe_id(query):
        return query

    games = await search_games(session, query)
    if not games:
        return None
    universe_id = games[0].get("universeId")
    return str(universe_id) if universe_id is not None else None


async def get_recommendations(
    session: aiohttp.ClientSession, universe_id: str
) -> list[dict[str, Any]]:
    url = f"{GAMES_API}/recommendations/game/{universe_id}"
    result = await _get_json(session, url)
    games = result.get("games", [])
    return games if isinstance(games, list) else []


def format_number(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def escape_markdown(value: Any) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~])", r"\\\1", str(value))
