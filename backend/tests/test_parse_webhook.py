"""Webhook payloadini normalizatsiya tekshiruvi (tarmoqsiz, sof funksiya)."""
from __future__ import annotations

from app.instagram.models import parse_webhook

SELF = "17999999"


def test_parses_comment():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": SELF,
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": "comment_1",
                            "text": "Qancha turadi?",
                            "from": {"id": "cust_1", "username": "ali"},
                            "media": {"id": "media_1", "caption": "Yangi kotyol"},
                        },
                    }
                ],
            }
        ],
    }
    events = parse_webhook(payload, SELF)
    assert len(events) == 1
    e = events[0]
    assert e.kind == "comment"
    assert e.text == "Qancha turadi?"
    assert e.sender_id == "cust_1"
    assert e.username == "ali"
    assert e.comment_id == "comment_1"
    assert e.media_id == "media_1"


def test_parses_dm():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": SELF,
                "messaging": [
                    {
                        "sender": {"id": "cust_2"},
                        "recipient": {"id": SELF},
                        "message": {"mid": "m1", "text": "Salom, narx?"},
                    }
                ],
            }
        ],
    }
    events = parse_webhook(payload, SELF)
    assert len(events) == 1
    assert events[0].kind == "dm"
    assert events[0].sender_id == "cust_2"


def test_skips_own_comment():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": SELF,
                "changes": [
                    {
                        "field": "comments",
                        "value": {"id": "c", "text": "hi", "from": {"id": SELF}},
                    }
                ],
            }
        ],
    }
    assert parse_webhook(payload, SELF) == []


def test_echo_becomes_echo_event():
    """Akkauntdan chiqqan xabar 'echo' bo'ladi — pipeline uni operator
    aralashuvi sifatida ko'radi (bot pauzasi shundan hosil bo'ladi)."""
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": SELF,
                "messaging": [
                    {
                        "sender": {"id": SELF},
                        "recipient": {"id": "cust_3"},
                        "message": {"text": "Assalomu alaykum, men menejerman",
                                    "is_echo": True},
                    }
                ],
            }
        ],
    }
    events = parse_webhook(payload, SELF)
    assert len(events) == 1
    assert events[0].kind == "echo"
    assert events[0].sender_id == "cust_3"  # suhbatdoshi — mijoz
