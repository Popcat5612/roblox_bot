# Roblox Discord Bot

Python으로 만든 디스코드 봇입니다. Roblox 공개 Games API에서 게임 정보와 비슷한 게임 추천을 가져옵니다. 이 기능에는 Roblox API 키가 필요하지 않습니다.

## 명령어

- `/game game:<게임 이름>` — 이름을 검색해 게임 아이콘, 현재 접속자, 누적 방문 수, 즐겨찾기 수, 제작자와 장르를 보여줍니다.
- `/recommend game:<게임 이름>` — 검색한 게임과 비슷한 게임을 최대 5개 추천합니다.
- `/creator creator:<이름>` — Roblox 유저나 그룹을 검색해 프로필과 공개 게임을 보여줍니다.
- `/user username:<이름>` — Roblox 사용자 프로필, 아바타, 가입일, 팔로워와 친구 수를 보여줍니다.
- `/favorites add game:<게임>` — 내 즐겨찾기에 게임을 저장합니다.
- `/favorites remove game:<게임>` — 내 즐겨찾기에서 게임을 지웁니다.
- `/favorites list` — 내가 저장한 게임을 확인합니다.

게임 이름은 **한국어 또는 영어**로 입력하고, 자동완성 목록에서 원하는 결과를 고르면 됩니다. Universe ID를 직접 입력해도 사용할 수 있습니다.
`/user`는 Roblox 사용자 이름 또는 표시 이름을, `/creator`는 사용자나 그룹 이름을 자동완성으로 선택합니다. 즐겨찾기는 봇을 실행하는 컴퓨터의 `favorites.sqlite3`에 디스코드 사용자별로 저장됩니다.

## 디스코드에 추가하기

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 새 Application을 만들고 **Bot**을 추가합니다.
2. Bot 페이지에서 토큰을 복사합니다. 토큰은 비밀번호처럼 비공개로 보관하세요.
3. `.env.example` 파일을 복사해 `.env`로 이름을 바꾸고 `DISCORD_TOKEN`을 입력합니다. 테스트 서버에서 명령어를 바로 확인하려면 `DISCORD_GUILD_ID`도 입력합니다.
4. Developer Portal의 **OAuth2 → URL Generator**에서 `bot`과 `applications.commands` 범위를 선택하고, Bot Permissions에서 **Send Messages**와 **Embed Links**를 선택합니다. 생성된 초대 링크로 봇을 서버에 추가합니다.
5. Python 3.10 이상을 설치하고 프로젝트 폴더에서 실행합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python bot.py
```

`DISCORD_GUILD_ID`를 설정하면 해당 서버에 명령어를 등록해 바로 시험할 수 있습니다. 비워 두면 전역 명령으로 등록되며, 디스코드에 표시되기까지 시간이 걸릴 수 있습니다. 봇을 계속 사용하려면 `python bot.py` 프로세스가 실행 중이어야 합니다.

Flask 상태 페이지도 로컬에서 함께 실행하려면 `python app.py`를 사용하세요. 이 명령은 Flask와 Discord 봇을 함께 시작합니다.

## Render 배포

저장소를 GitHub에 올린 뒤 Render에서 **New → Blueprint**를 선택하면 `render.yaml` 설정의 단일 웹 서비스가 Flask와 Discord 봇을 함께 시작합니다. `DISCORD_TOKEN`과 필요하면 `DISCORD_GUILD_ID` 환경 변수를 Render 대시보드에 입력하세요. Render는 Flask를 Gunicorn으로 실행하고 `/healthz`를 상태 확인에 사용합니다.

Flask 상태 페이지는 `/`에서 확인할 수 있습니다. Gunicorn은 봇의 중복 접속을 막기 위해 워커 1개로 설정되어 있습니다.

Render의 기본 파일 시스템은 재배포·재시작 때 초기화되므로 `favorites.sqlite3`의 즐겨찾기도 사라질 수 있습니다. 즐겨찾기를 유지하려면 유료 웹 서비스에 영구 디스크를 연결하고 `FAVORITES_DB_PATH=/var/data/favorites.sqlite3`로 설정하세요. 무료 웹 서비스는 요청이 없으면 15분 후 잠들 수 있어 봇 연결도 끊깁니다.

## 참고 문서

- [Roblox Games API](https://create.roblox.com/docs/ko-kr/cloud/reference/domains/games) — 게임 상세 정보(`/v1/games`)와 추천(`/v1/games/recommendations/game/{universeId}`)
- [Roblox Thumbnails API](https://create.roblox.com/docs/cloud/reference/features/thumbnails) — 게임 아이콘 이미지 URL을 가져옵니다.
- [Roblox Users API](https://create.roblox.com/docs/cloud/reference/domains/users) — 공개 사용자 검색과 프로필 조회에 사용합니다.
- [Roblox Groups API](https://create.roblox.com/docs/cloud/reference/domains/groups) — 그룹 정보를 조회합니다.
- [Roblox 검색 API 안내](https://devforum.roblox.com/t/official-list-of-deprecated-web-endpoints/62889/59) — 게임 이름 검색에 사용합니다. 검색 API는 Open Cloud의 안정된 API 레퍼런스에 포함되지 않아 동작이 변경될 수 있습니다.
- [Render Flask 배포 가이드](https://render.com/docs/deploy-flask)와 [영구 디스크 안내](https://render.com/docs/disks)
- [discord.py 슬래시 명령 문서](https://discordpy.readthedocs.io/en/stable/interactions/api.html) — CommandTree와 `sync()`로 명령어를 등록합니다.
