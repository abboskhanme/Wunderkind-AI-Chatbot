"""Bot O'Z izohiga javob bermasligi — cheksiz halqadan himoya.

Bu real hodisa: Instagram bir joyda app-scoped `user_id`, boshqa joyda
akkauntning o'z `id` sini beradi. Faqat bittasi bilan solishtirilgani uchun
bot o'z javobini «begona izoh» deb hisoblab, o'ziga qayta-qayta javob yozib
ketdi. Shu sabab bu yerda IKKALA ID va username ham tekshiriladi.
"""
from app.instagram.models import parse_webhook

ACCOUNT_ID = "17841415881877618"   # webhook'da `from.id` shu keladi
USER_ID = "28078615215162402"      # OAuth qaytargan app-scoped id
USERNAME = "khan.progress"


def _comment(from_id: str, username: str = "", text: str = "salom") -> dict:
    return {
        "entry": [{
            "changes": [{
                "field": "comments",
                "value": {
                    "id": "cmt_1",
                    "text": text,
                    "from": {"id": from_id, "username": username},
                    "media": {"id": "media_1"},
                },
            }]
        }]
    }


def test_own_comment_by_account_id_is_ignored():
    """Webhook akkaunt ID'sini yuborsa ham o'z izohimiz o'tkazib yuboriladi."""
    events = parse_webhook(_comment(ACCOUNT_ID), {USER_ID, ACCOUNT_ID}, USERNAME)
    assert events == []


def test_own_comment_by_user_id_is_ignored():
    """Boshqa formatdagi ID kelsa ham xuddi shunday."""
    events = parse_webhook(_comment(USER_ID), {USER_ID, ACCOUNT_ID}, USERNAME)
    assert events == []


def test_own_comment_caught_by_username_when_ids_unknown():
    """ID'lar noma'lum bo'lsa ham username bo'yicha tanib olinadi.

    Aynan shu zaxira tekshiruv halqani boshlanishidan oldin to'xtatadi.
    """
    events = parse_webhook(_comment("boshqa_id", USERNAME), set(), USERNAME)
    assert events == []


def test_stranger_comment_is_processed():
    """Begona odamning izohi esa normal qayta ishlanadi."""
    events = parse_webhook(
        _comment("999", "mijoz", "Narxi qancha?"), {USER_ID, ACCOUNT_ID}, USERNAME
    )
    assert len(events) == 1
    assert events[0].kind == "comment"
    assert events[0].text == "Narxi qancha?"
    assert events[0].sender_id == "999"


def test_own_dm_is_echo_not_reply():
    """Akkauntimizdan chiqqan DM — «echo», unga javob yozilmaydi."""
    payload = {"entry": [{"messaging": [{
        "sender": {"id": ACCOUNT_ID},
        "recipient": {"id": "999"},
        "message": {"text": "Salom!"},
    }]}]}
    events = parse_webhook(payload, {USER_ID, ACCOUNT_ID}, USERNAME)
    assert len(events) == 1 and events[0].kind == "echo"


def test_single_id_string_still_supported():
    """Eski chaqiruv shakli (bitta satr) ham ishlaydi."""
    assert parse_webhook(_comment(ACCOUNT_ID), ACCOUNT_ID) == []
