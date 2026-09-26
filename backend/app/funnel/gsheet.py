"""Google Sheets export of funnel entries (SPEC §10.1 "Google Sheets").

Sheets REST API v4 over httpx; the OAuth token comes from a JWT signed with the
service-account key (RS256 via pyjwt + cryptography). One row per entry.

Which row belongs to which entry is read from the sheet itself: the last column
"ID" holds entry.id and every batch reads that column first. So sorting or
deleting rows in the sheet never sends an update to the wrong person; an entry
whose ID is not found is appended. `sheet_row` is only the last known row.

Outbox: every change sets `sheet_dirty`; `sync_dirty()` runs every minute and
clears the flag only if the entry did not change while it was being written.
Auth / rate-limit / 5xx / network errors stop the batch (retried next minute);
any other 4xx is that entry's problem: logged, the rest continue.
Not configured → no-op.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime
from typing import Optional

import httpx
import jwt
from loguru import logger
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session as db_session
from app.funnel import funnels, repo, texts
from app.models.funnel import FunnelEntry, InterviewBooking

HEADER = ["Sana", "Manba", "Ism-familiya", "Telefon", "Sinf", "Telegram", "Telegram ID",
          "Instagram", "Qo'llanma", "Suhbat sanasi", "Suhbat vaqti", "Suhbat holati",
          "Yangilangan", "ID", "Voronka"]
# "Voronka" (funnel name) is appended AFTER "ID" so existing layouts do not shift
_LAST_COLUMN = "O"                     # 15 columns; N = ID, O = funnel
_NARROW_LAST_COLUMN = "N"              # when column O holds the client's own data
_FUNNEL_HEADER = "Voronka"
_ID_COLUMN = "N"
_SOURCE_COLUMN = "B"
MERGED_LABEL = "Birlashtirildi"
_BATCH_STOPPERS = (401, 403, 429)      # plus 5xx and network errors (status 0)
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
API = "https://sheets.googleapis.com/v4/spreadsheets"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
BATCH = 50

# Tests inject httpx.MockTransport here (no network)
_transport: Optional[httpx.AsyncBaseTransport] = None
_token_cache: dict[str, tuple[str, float]] = {}
_ready_sheets: set[str] = set()        # "<spreadsheet>|<worksheet>" with header checked
_o_taken: set[str] = set()             # ready sheets whose column O is NOT ours
_O_TAKEN_ALERT_KEY = "fnl:alert:sheet-column-o"


class SheetError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def spreadsheet_id(value: str) -> Optional[str]:
    """ID from a bare ID or a full docs.google.com link."""
    value = (value or "").strip()
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", value)
    if match:
        return match[1]
    return value if re.fullmatch(r"[A-Za-z0-9_-]{20,}", value) else None


def _account() -> Optional[dict]:
    try:
        data = json.loads(settings.GSHEET_SERVICE_ACCOUNT_JSON or "")
    except ValueError:
        return None
    if isinstance(data, dict) and data.get("client_email") and data.get("private_key"):
        return data
    return None


def configured() -> bool:
    return bool(_account() and spreadsheet_id(settings.GSHEET_SPREADSHEET_ID))


def _worksheet() -> str:
    return (settings.GSHEET_WORKSHEET or "").strip() or "Leadlar"


def _a1(cells: str) -> str:
    """'Leadlar'!A1:M1 — the sheet name quoted, apostrophes doubled."""
    return "'" + _worksheet().replace("'", "''") + "'!" + cells


def _values_url(sheet: str, cells: str, suffix: str = "") -> str:
    return f"{API}/{sheet}/values/{urllib.parse.quote(_a1(cells), safe='')}{suffix}"


async def _access_token(http: httpx.AsyncClient, account: dict) -> str:
    cache_key = account["client_email"] + hashlib.sha256(
        account["private_key"].encode()).hexdigest()[:16]
    cached = _token_cache.get(cache_key)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    token_uri = account.get("token_uri") or DEFAULT_TOKEN_URI
    issued = int(time.time())
    headers = {"kid": account["private_key_id"]} if account.get("private_key_id") else None
    try:
        assertion = jwt.encode(
            {"iss": account["client_email"], "scope": SCOPE, "aud": token_uri,
             "iat": issued, "exp": issued + 3600},
            account["private_key"], algorithm="RS256", headers=headers)
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise SheetError(f"Service account kaliti o'qilmadi: {exc}", 401) from None
    resp = await http.post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    body = _json(resp)
    if resp.status_code != 200 or not body.get("access_token"):
        # Always an auth problem (whatever HTTP code): stops the whole batch
        raise SheetError("Google kirishni rad etdi: "
                         + str(body.get("error_description") or body.get("error") or resp.status_code),
                         401)
    _token_cache[cache_key] = (body["access_token"], issued + int(body.get("expires_in") or 3600))
    return body["access_token"]


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _call(http: httpx.AsyncClient, account: dict, method: str, url: str, **kwargs) -> dict:
    token = await _access_token(http, account)
    try:
        resp = await http.request(method, url, headers={"Authorization": f"Bearer {token}"},
                                  **kwargs)
    except httpx.HTTPError as exc:
        raise SheetError(f"Google Sheets'ga ulanib bo'lmadi: {exc}") from None
    body = _json(resp)
    if resp.status_code >= 300:
        message = str((body.get("error") or {}).get("message") or resp.text[:200])
        raise SheetError(message, resp.status_code)
    return body


async def _ensure_sheet(http: httpx.AsyncClient, account: dict, sheet: str) -> str:
    """Spreadsheet title; creates the worksheet and the header row when missing."""
    meta = await _call(http, account, "GET", f"{API}/{sheet}",
                       params={"fields": "properties.title,sheets.properties.title"})
    title = str((meta.get("properties") or {}).get("title") or "")
    ready_key = f"{sheet}|{_worksheet()}"
    if ready_key in _ready_sheets:
        return title
    names = [s.get("properties", {}).get("title") for s in meta.get("sheets") or []]
    if _worksheet() not in names:
        await _call(http, account, "POST", f"{API}/{sheet}:batchUpdate",
                    json={"requests": [{"addSheet": {"properties": {"title": _worksheet()}}}]})
    header = await _call(http, account, "GET", _values_url(sheet, f"A1:{_LAST_COLUMN}1"))
    current = (header.get("values") or [[]])[0]
    column_o = str(current[len(HEADER) - 1]).strip() if len(current) >= len(HEADER) else ""
    if column_o and column_o != _FUNNEL_HEADER:
        # The client uses column O for something else: never overwrite it
        _o_taken.add(ready_key)
        wanted, last = HEADER[:-1], _NARROW_LAST_COLUMN
        await _alert_column_o_taken(column_o)
    else:
        _o_taken.discard(ready_key)
        wanted, last = HEADER, _LAST_COLUMN
    if current[:len(wanted)] != wanted:      # empty sheet, or an older header
        await _call(http, account, "PUT", _values_url(sheet, f"A1:{last}1"),
                    params={"valueInputOption": "RAW"}, json={"values": [wanted]})
    _ready_sheets.add(ready_key)
    return title


async def _alert_column_o_taken(found: str) -> None:
    from app.state.store import store
    from app.telegram import notifier

    try:
        if await store.seen_once(_O_TAKEN_ALERT_KEY, 24 * 3600):
            return
        await notifier.send_text(
            "⚠️ <b>Google Sheets: «O» ustuni band</b>\n"
            f"U yerda «{found[:40]}» turibdi — «{_FUNNEL_HEADER}» ustuni yozilmayapti "
            "(qolgan ustunlar yozilyapti). O ustunini bo'shating yoki "
            f"«{_FUNNEL_HEADER}» deb nomlang.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sheets column-O alert failed: {}", exc)


def _width(sheet: str) -> tuple[int, str]:
    """(columns, last column letter) this sheet may be written with."""
    if f"{sheet}|{_worksheet()}" in _o_taken:
        return len(HEADER) - 1, _NARROW_LAST_COLUMN
    return len(HEADER), _LAST_COLUMN


def _fmt(dt: Optional[datetime], pattern: str = "%Y-%m-%d %H:%M") -> str:
    return texts.local(dt).strftime(pattern) if dt else ""


def entry_row(entry: FunnelEntry, booking: Optional[InterviewBooking],
              now: Optional[datetime] = None, funnel_name: str = "") -> list[str]:
    """One sheet row in HEADER order (RAW strings: "+998…" must stay text)."""
    if entry.pdf_sent_at:
        guide = "Yuborildi"
    elif entry.step == "pdf_pending":
        guide = "Kutilmoqda"
    else:
        guide = ""
    return [
        _fmt(entry.created_at),
        texts.SOURCE_LABELS.get(entry.source, entry.source),
        entry.full_name or "",
        entry.phone or "",
        texts.grade_display(entry.grade),
        f"@{entry.tg_username}" if entry.tg_username else "",
        entry.tg_user_id or "",
        f"@{entry.ig_username}" if entry.ig_username else "",
        guide,
        _fmt(booking.starts_at, "%Y-%m-%d") if booking else "",
        _fmt(booking.starts_at, "%H:%M") if booking else "",
        texts.BOOKING_LABELS.get(booking.status, booking.status) if booking else "",
        _fmt(now or repo.now()),
        str(entry.id) if entry.id else "",
        funnel_name,
    ]


def row_number(updated_range: str) -> Optional[int]:
    """"'Leadlar'!A7:M7" -> 7."""
    match = re.search(r"![A-Z]+(\d+)", updated_range or "")
    return int(match[1]) if match else None


async def _row_index(http: httpx.AsyncClient, account: dict, sheet: str) -> dict[str, int]:
    """entry id -> row number, read from the sheet's ID column."""
    body = await _call(http, account, "GET",
                       _values_url(sheet, f"{_ID_COLUMN}:{_ID_COLUMN}"))
    index: dict[str, int] = {}
    for number, cells in enumerate(body.get("values") or [], start=1):
        value = str(cells[0]).strip() if cells else ""
        if value and value != "ID":
            index[value] = number
    return index


async def _put_row(http: httpx.AsyncClient, account: dict, sheet: str, number: int,
                   row: list[str]) -> None:
    size, last = _width(sheet)
    await _call(http, account, "PUT",
                _values_url(sheet, f"A{number}:{last}{number}"),
                params={"valueInputOption": "RAW"}, json={"values": [row[:size]]})


async def _write(http: httpx.AsyncClient, account: dict, sheet: str, entry: FunnelEntry,
                 row: list[str], index: dict[str, int]) -> int:
    """Update the entry's row (found by ID) or append one. A merged Instagram
    entry's row is taken over when this entry has none, else marked merged."""
    number = index.get(str(entry.id))
    merged = index.get(str(entry.sheet_merged_id)) if entry.sheet_merged_id else None
    if number is None and merged is not None:
        number = merged                     # take over: the ID cell becomes ours
    elif merged is not None and merged != number:
        await _call(http, account, "PUT",
                    _values_url(sheet, f"{_SOURCE_COLUMN}{merged}:{_SOURCE_COLUMN}{merged}"),
                    params={"valueInputOption": "RAW"}, json={"values": [[MERGED_LABEL]]})
    if number is not None:
        await _put_row(http, account, sheet, number, row)
        return number
    size, last = _width(sheet)
    body = await _call(http, account, "POST",
                       _values_url(sheet, f"A:{last}", ":append"),
                       params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                       json={"values": [row[:size]]})
    number = row_number(str((body.get("updates") or {}).get("updatedRange") or ""))
    if number is None:
        raise SheetError("Google qator raqamini qaytarmadi")
    return number


def _stops_batch(exc: SheetError) -> bool:
    """Google/auth-wide problems stop the batch; other 4xx belong to one entry."""
    return exc.status in _BATCH_STOPPERS or exc.status >= 500 or exc.status == 0


async def sync_dirty(limit: int = BATCH) -> int:
    """Scheduler entry point: write dirty entries. Returns rows written."""
    account = _account()
    sheet = spreadsheet_id(settings.GSHEET_SPREADSHEET_ID)
    if not account or not sheet:
        return 0
    async with db_session.SessionLocal() as db:
        entries = list((await db.execute(
            select(FunnelEntry).where(FunnelEntry.sheet_dirty.is_(True))
            .order_by(FunnelEntry.updated_at).limit(limit)
        )).scalars().all())
        bookings = await repo.latest_bookings(db, [e.id for e in entries])
        names = {f.id: f.name for f in await funnels.load_all(db)}
    if not entries:
        return 0
    written = 0
    async with httpx.AsyncClient(timeout=20.0, transport=_transport) as http:
        try:
            if f"{sheet}|{_worksheet()}" not in _ready_sheets:
                await _ensure_sheet(http, account, sheet)
            index = await _row_index(http, account, sheet)
            for entry in entries:
                try:
                    row = entry_row(entry, bookings.get(entry.id),
                                    funnel_name=names.get(entry.funnel_id, ""))
                    number = await _write(http, account, sheet, entry, row, index)
                except SheetError as exc:
                    if _stops_batch(exc):
                        raise
                    logger.warning("Sheets: entry {} skipped ({}): {}", entry.id, exc.status, exc)
                    await _forget_row(entry)
                    continue
                index[str(entry.id)] = number
                await _mark_synced(entry, number)
                written += 1
        except SheetError as exc:
            # Google down / no access / sheet deleted: the rest stays dirty and is
            # retried next minute, re-checking the worksheet first
            _ready_sheets.discard(f"{sheet}|{_worksheet()}")
            logger.warning("Google Sheets sync stopped ({} written): {}", written, exc)
    return written


async def _mark_synced(entry: FunnelEntry, number: int) -> None:
    """Save the row number always; clear dirty only if the entry is unchanged
    since it was read. updated_at is kept as is."""
    async with db_session.SessionLocal() as db:
        await db.execute(
            update(FunnelEntry).where(FunnelEntry.id == entry.id).values(
                sheet_row=number,
                sheet_merged_id=None,
                sheet_dirty=case((FunnelEntry.updated_at == entry.updated_at, False),
                                 else_=True),
                updated_at=FunnelEntry.updated_at,
            ))
        await db.commit()


async def _forget_row(entry: FunnelEntry) -> None:
    """Per-entry 4xx: drop the remembered row; the entry stays dirty."""
    async with db_session.SessionLocal() as db:
        await db.execute(update(FunnelEntry).where(FunnelEntry.id == entry.id).values(
            sheet_row=None, updated_at=FunnelEntry.updated_at))
        await db.commit()


async def reset_target() -> int:
    """GSHEET_SPREADSHEET_ID / GSHEET_WORKSHEET changed: rows in the old sheet mean
    nothing in the new one — forget them and export everything again."""
    _ready_sheets.clear()
    _o_taken.clear()
    async with db_session.SessionLocal() as db:
        result = await db.execute(update(FunnelEntry).values(
            sheet_row=None, sheet_dirty=True, updated_at=FunnelEntry.updated_at))
        await db.commit()
    logger.info("Google Sheets target changed — {} entries queued", result.rowcount)
    return int(result.rowcount or 0)


async def mark_all_dirty(db: AsyncSession) -> int:
    """Panel "resync": queue every entry (rows are updated in place)."""
    result = await db.execute(update(FunnelEntry).values(
        sheet_dirty=True, updated_at=FunnelEntry.updated_at))
    await db.commit()
    return int(result.rowcount or 0)


async def test_connection() -> dict:
    """For the panel button: {ok, title?, error?} with an Uzbek hint."""
    account = _account()
    sheet = spreadsheet_id(settings.GSHEET_SPREADSHEET_ID)
    if not account:
        return {"ok": False, "error": "Service account JSON kiritilmagan"}
    if not sheet:
        return {"ok": False, "error": "Jadval ID yoki havolasi kiritilmagan"}
    _ready_sheets.discard(f"{sheet}|{_worksheet()}")      # re-check the header too
    try:
        async with httpx.AsyncClient(timeout=20.0, transport=_transport) as http:
            title = await _ensure_sheet(http, account, sheet)
    except SheetError as exc:
        return {"ok": False, "error": _hint(exc, account)}
    return {"ok": True, "title": title}


def _hint(exc: SheetError, account: dict) -> str:
    if exc.status == 403:
        return (f"Jadvalga ruxsat yo'q — jadvalni {account.get('client_email')} manziliga "
                "«Editor» qilib ulashing")
    if exc.status == 404:
        return "Jadval topilmadi — ID yoki havolani tekshiring"
    return str(exc)[:300]


# ===========================================================================
# User data deletion (SPEC §12.2): blank the rows of deleted entries
# ===========================================================================
DELETED_LABEL = "O'chirildi"
_ERASE_ATTEMPTS = 3


def _transient(exc: SheetError) -> bool:
    return exc.status == 429 or exc.status >= 500 or exc.status == 0


async def erase_rows(entry_ids: list[str]) -> dict:
    """Blank every cell (ID included) of the rows holding these entries and put
    "O'chirildi" in the source column, so the sheet keeps no personal data of a
    person whose data was deleted. The entries are already gone from the DB, so
    there is no outbox: transient Google errors are retried here with backoff and
    a final failure is reported to the caller (staff are alerted to do it by hand).

    Returns {"configured": bool, "erased": int, "error": str | None}.
    """
    account = _account()
    sheet = spreadsheet_id(settings.GSHEET_SPREADSHEET_ID)
    if not account or not sheet or not entry_ids:
        return {"configured": bool(account and sheet), "erased": 0, "error": None}
    wanted = {str(i) for i in entry_ids}
    last_error: Optional[SheetError] = None
    for attempt in range(_ERASE_ATTEMPTS):
        erased = 0
        try:
            async with httpx.AsyncClient(timeout=20.0, transport=_transport) as http:
                index = await _row_index(http, account, sheet)
                size, last = _width(sheet)
                for entry_id in sorted(wanted):
                    number = index.get(entry_id)
                    if number is None:
                        continue
                    blank = [""] * size
                    blank[ord(_SOURCE_COLUMN) - ord("A")] = DELETED_LABEL
                    await _call(http, account, "PUT",
                                _values_url(sheet, f"A{number}:{last}{number}"),
                                params={"valueInputOption": "RAW"}, json={"values": [blank]})
                    erased += 1
            logger.info("Sheets: {} row(s) erased after a data deletion request", erased)
            return {"configured": True, "erased": erased, "error": None}
        except SheetError as exc:
            last_error = exc
            if not _transient(exc) or attempt == _ERASE_ATTEMPTS - 1:
                break
            await asyncio.sleep(2 ** attempt)
    logger.warning("Sheets: rows of deleted entries not erased ({}): {}",
                   last_error.status if last_error else "?", last_error)
    return {"configured": True, "erased": 0, "error": str(last_error)[:200]}
