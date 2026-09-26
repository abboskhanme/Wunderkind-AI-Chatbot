# Meta App Review — Wunderkind AI assistant

Everything the client needs to take the Meta app (Instagram API with Instagram
Login) from Development mode to Live: dashboard fields, public URLs, permission
justifications to paste, screencast scripts, reviewer instructions, and how the
two Meta callbacks work. `{PUBLIC_URL}` below = the production origin, e.g.
`https://chatbot.wunderkindedu.uz`. The admin panel shows every URL with a copy
button: **Sozlamalar → Instagram → "Meta App Review uchun manzillar"**.

Sources (checked 2026-09-26):
- App Review for Instagram API (updated Jun 30, 2026) —
  https://developers.facebook.com/docs/instagram-platform/app-review
- Create a Meta app with Instagram (Business login settings, Step 10) —
  https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/create-a-meta-app-with-instagram
- Data Deletion Request Callback (updated Nov 7, 2025) —
  https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback

## 0. Is App Review needed at all?

Meta's access table says an app used **only for a business you own or manage**
with Instagram Login needs **Standard Access, App Review not required**; Advanced
Access (App Review + Business Verification) is for apps serving businesses you
do not own. This app serves only Wunderkind's own Instagram account, so:

1. First fill in every dashboard field in section 2 and switch the app to
   **Live** (Live mode needs the Privacy Policy URL and data deletion anyway).
2. Test from an Instagram account that has **no role** on the app: comment the
   keyword and send a DM.
3. If those events arrive and get answered — you are done. If Meta still only
   delivers events from accounts with an app role, or the dashboard insists on
   Advanced Access for a permission, submit App Review with sections 3–5.

## 1. App description (paste into "App details" / review notes)

> Wunderkind is a private school in Uzbekistan. This app connects the school's
> own Instagram professional account to our admissions assistant. When a parent
> comments on one of our posts or sends us a direct message, the assistant
> answers questions about the school (grades, fees, admission) from a knowledge
> base written by our staff, sends the free parenting guide the parent asked for
> (via our Telegram bot), and helps book an admission interview. The first reply
> in every conversation says that it comes from an AI assistant, and a staff
> member can take over at any time. Our admissions staff see every conversation
> in a private admin panel and reply there when a human is needed. The app is
> used only for the school's own Instagram account; we do not run ads, do not
> sell data and do not publish content.

## 2. Dashboard checklist

App settings → **Basic**:

| Field | Value |
|---|---|
| App icon | 1024×1024 PNG, the school logo |
| Category | **Education** |
| Contact email / Business email | the email in panel setting `LEGAL_CONTACT_EMAIL` (App Review results arrive there) |
| Privacy Policy URL | `{PUBLIC_URL}/privacy` |
| Terms of Service URL | `{PUBLIC_URL}/terms` |
| User data deletion | choose **Data deletion callback URL**: `{PUBLIC_URL}/connect/data-deletion` (the instructions page `{PUBLIC_URL}/data-deletion` also works if the form asks for instructions) |

Instagram → API setup with Instagram login → 3. Set up Instagram business login
→ **Business login settings**:

| Field | Value |
|---|---|
| OAuth Redirect URI | `{PUBLIC_URL}/connect/callback` |
| Deauthorize callback URL | `{PUBLIC_URL}/connect/deauthorize` |
| Data deletion request URL | `{PUBLIC_URL}/connect/data-deletion` |

Instagram → Webhooks: callback `{PUBLIC_URL}/webhook/instagram`, verify token =
panel setting "Webhook verify token", fields **comments** and **messages**.

Business portfolio → **Business Verification** (Security Center): required for
Advanced Access; start it early, it needs company documents and can take days.

Before submitting, fill **Sozlamalar → Yuridik ma'lumotlar** in the panel (legal
name, email, phone, address) and open the three pages to check them. Empty
fields fall back to the school name / funnel staff phone / funnel address; an
empty email is simply not shown — Meta reviewers expect one, so set it.

## 3. Permissions — what to paste

### instagram_business_basic
- **What we do:** read the connected account's id and username when the school
  connects its account in our admin panel ("Ulash"), and the username/id of
  people who comment or message us.
- **Why needed:** to know which account is ours (so the assistant never replies
  to its own comments), to show which account is connected, and to label
  conversations with the sender's username for our staff.
- **User benefit:** parents get answers from the correct school account; staff
  see who they are talking to.

### instagram_business_manage_comments
- **What we do:** receive comments on the school's posts (webhook `comments`),
  post one short public reply, and send one private reply to a parent who
  commented the keyword (e.g. "Wunderkind") asking for our free guide.
- **Why needed:** our posts invite parents to comment a keyword to receive the
  guide; without this permission we cannot see the comment or reply to it.
- **User benefit:** a parent who asks for the guide in a comment gets it within
  seconds instead of waiting for a staff member to notice the comment.

### instagram_business_manage_messages (+ Human Agent feature)
- **What we do:** receive direct messages sent to the school's account, answer
  questions about the school with the AI assistant, send the Telegram link for
  the guide, and let staff reply from the admin panel. Staff replies after 24
  hours use the `HUMAN_AGENT` tag (up to 7 days) only for a human answering a
  parent's own question.
- **Why needed:** answering parents' direct messages is the core of the service.
- **User benefit:** parents get immediate, accurate answers at any time of day
  and can reach a human whenever they ask.

## 4. Screencast scripts (one recording per permission, 1–2 min each)

Record in a browser + phone, English UI captions if possible, no personal data
of real parents (use the test account). Start each video by showing the admin
panel URL.

**Basic (`instagram_business_basic`)**
1. Log in to the admin panel as an administrator → Sozlamalar → Instagram.
2. Click **Ulash** → Instagram login and permission screen (show the requested
   permissions) → approve.
3. The success page shows "Instagram ulandi"; back in Sozlamalar the card shows
   "Ulangan: @wunderkind…".

**Comments (`instagram_business_manage_comments`)**
1. From the test Instagram account, comment "Wunderkind" under a school post.
2. Show the public reply appearing under the comment.
3. Show the private reply in the test account's Direct inbox.
4. In the admin panel → Suhbatlar, show the conversation with the comment.

**Messages (`instagram_business_manage_messages` + Human Agent)**
1. From the test account send a DM: "What grades do you accept?".
2. Show the assistant's reply (with the AI disclosure line) in Instagram.
3. In the admin panel → Suhbatlar, open the conversation, type a reply as staff
   and send it; show it arriving in Instagram.

## 5. Reviewer instructions (App Review → verification details)

> 1. Open `{PUBLIC_URL}` and log in with username `<reviewer login>` and password
>    `<password>`. This is an operator account created for Meta review; it can
>    see conversations and leads and reply to parents.
> 2. From the test Instagram account `<@test_account>` / `<password>` (or your
>    own account), send a direct message to `@<school account>` — for example
>    "What grades do you accept?". The assistant replies within a few seconds.
> 3. Comment "Wunderkind" under any post of `@<school account>`: you get a public
>    reply and a private message with a link to our Telegram bot.
> 4. In the admin panel open **Suhbatlar** (Conversations): both conversations
>    are listed. Open one, type a message in the reply box and press send — it is
>    delivered to Instagram as a staff reply.
> The panel UI is in Uzbek: Suhbatlar = Conversations, Leadlar = Leads,
> Bosh sahifa = Dashboard.

Client to-do: create the operator user in **Foydalanuvchilar** (role
"operator", strong password, disable it after review), and a test Instagram
account that is **not** an admin of the school page.

## 6. The two callbacks (technical)

Both accept Meta's form post `signed_request=<base64url(sig)>.<base64url(json)>`,
verify HMAC-SHA256 over the encoded payload with the **Instagram App Secret**
(panel setting `IG_APP_SECRET`), and answer **400** on a missing/forged/malformed
request (nothing changes). Code: `backend/app/instagram/signed_request.py`,
`backend/app/instagram/meta_callbacks.py`, `backend/app/legal/deletion.py`.

`POST /connect/data-deletion` (payload `user_id` = Instagram-scoped id):
1. records a `data_deletion_requests` row (`received`, 16-char code);
2. deletes the person's Instagram leads + messages, funnel entries with that
   Instagram id (+ deliveries, interview bookings), and — because the funnel
   linked them — the same person's Telegram entries and leads; clears their
   conversation cache;
3. if the id is **our own connected account** (IG_USER_ID / IG_ACCOUNT_ID):
   clears the token and identity → Instagram is disconnected;
4. marks the row `completed` and answers
   `{"url": "{PUBLIC_URL}/data-deletion?code=<code>", "confirmation_code": "<code>"}`;
5. in the background: blanks the person's rows in the Google Sheet (label
   "O'chirildi") and sends a staff alert to Telegram (code + counts, no names).

`POST /connect/deauthorize`: if it is our account → disconnect + staff alert;
anyone else → nothing to do; always 200 for a valid signature.

### Manual test (server shell)

```bash
docker compose -p wkagent exec backend python -c "
from app.config import settings; from app import runtime_config as rc; import asyncio
from app.instagram.signed_request import build_signed_request
asyncio.run(rc.reload())
print(build_signed_request({'algorithm':'HMAC-SHA256','user_id':'test-123'}, settings.IG_APP_SECRET))"
curl -s -X POST {PUBLIC_URL}/connect/data-deletion --data-urlencode "signed_request=<output>"
```

Never use the connected account's own id for this test — it disconnects Instagram.

### Failure modes

| Symptom | Cause / action |
|---|---|
| Meta says the callback failed, logs show `IG_APP_SECRET is not set` | Enter the Instagram App Secret in Sozlamalar → Instagram. |
| Logs show `signature mismatch` | Secret in the panel is not the **Instagram** app secret of this app (Meta app secret ≠ Instagram app secret). |
| Staff alert "Avtomatik o'chirish bajarilmadi" | DB error mid-way (nothing was deleted, the transaction rolled back); the request stays `received` — re-send the same signed request (manual test above, with that user id) or ask the developer, within 30 days. |
| Staff alert lists IDs for Google Sheets | Google was unreachable/denied; delete the rows whose "ID" column holds those IDs. |
| Alert "IG_ACCESS_TOKEN .env faylida ham bor" | The token is also in the server `.env`; remove it there or it comes back on restart. |
| Instagram disconnected unexpectedly | Someone removed the app from the school account (Instagram → Apps and websites) — reconnect with "Ulash". |

## 7. Known limits (tell the client)

- Instagram ids: Meta sends the id that Instagram Login gave **our app** for that
  person. Parents who only message us never log in to our app, so automatic
  requests realistically come only from the school's own account. Parents'
  deletion requests arrive by email/phone/message. **Gap:** the panel's
  Leadlar → delete removes the conversation only — the funnel record (name,
  phone, grade, interview) and the Google Sheet row stay. Until a "delete all
  data of this person" admin action exists, staff forward such requests to the
  developer (or delete the funnel row/Sheet row by hand) within 30 days.
- The privacy policy promises deletion 24 months after the last contact; there is
  no automatic purge job yet — staff must clean old leads (or ask us to add a
  scheduled purge) before the first records reach 24 months (Sept 2028).
- Hosting in Frankfurt: Uzbekistan's personal data law has a data localisation
  requirement for citizens' personal data — the client should confirm with a
  lawyer whether a local copy/server is needed. The policy text states the real
  location, it does not claim compliance.
