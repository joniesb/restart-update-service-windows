import html
import logging
import re

import requests
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from bot.services.deezer import download_and_ensure_min_size
from bot.services.genius import genius_search, scrape_song_details_from_url, find_best_genius_link
from bot.services.spotify import spotify_get_album, spotify_album_to_details, spotify_get_track, try_spotify_lookup
from bot.utils.config import ADMINS, CHANNEL_USERNAME
from bot.utils.helpers import log_user_request, user_data, save_state, custom_buttons, glass_button, preview_messages

logger = logging.getLogger(__name__)


async def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user = query.from_user
    data = query.data or ""
    await query.answer()

    if data == "menu_start":
        await query.edit_message_text("منوی اصلی:", reply_markup=main_menu_keyboard(is_admin=(user.id in ADMINS)))
    elif data == "create_caption":
        await query.edit_message_text("🎵 لطفاً لینک Spotify یا نام آلبوم/آرتیست را ارسال کنید (برای لینک مستقیم بهتر است).")
        context.user_data["expecting_search_from_admin"] = True
    elif data == "add_manual_link":
        kb = InlineKeyboardMarkup([
            [glass_button("Spotify", callback_data="manual_spotify"),
             glass_button("Genius", callback_data="manual_genius")],
            [glass_button("YouTube", callback_data="manual_youtube"),
             glass_button("بازگشت", callback_data="menu_start")]
        ])
        await query.edit_message_text("🔗 نوع لینک را انتخاب کنید:", reply_markup=kb)
    elif data == "request_music":
        await query.edit_message_text("📩 لطفاً نام آلبوم/ترک یا لینک Spotify را ارسال کنید تا برای مدیران بفرستم.")
        context.user_data["expecting_user_request"] = True
    elif data == "show_logs":
        if user.id not in ADMINS:
            await query.edit_message_text("🔒 دسترسی فقط برای ادمین‌ها.")
            return
        try:
            with open('logs/user_requests.log', "r", encoding="utf-8") as f:
                content = f.read()[-4000:] or "هنوز لاگی ثبت نشده."
            await query.edit_message_text(f"📊 آخرین درخواست‌ها:\n\n{content}")
        except FileNotFoundError:
            await query.edit_message_text("📭 هنوز لاگی وجود ندارد.")
    elif data == "admin_menu":
        if user.id not in ADMINS:
            await query.edit_message_text("🔒 دسترسی فقط برای ادمین‌ها.")
            return
        from bot.handlers.admin import admin_reply_kb
        await context.bot.send_message(query.message.chat.id, "🎛 منوی مدیریت ربات:", reply_markup=admin_reply_kb())
    elif data.startswith("hashtag_"):
        tag = data.replace("hashtag_", "")
        await handle_hashtag_selection_by_callback(query, context, tag)
    elif data.startswith("select_genius_"):
        await handle_select_genius_callback(query, context)
    elif data.startswith("manual_"):
        kind = data.replace("manual_", "")
        await query.edit_message_text(f"لطفاً لینک {kind} را بفرستید:")
        context.user_data["manual_kind"] = kind
    elif data in ("confirm_send", "cancel_send"):
        await handle_preview_actions_callback(query, context, data)


def main_menu_keyboard(is_admin=False):
    kb = []
    if is_admin:
        kb.append([glass_button("🏠 منوی اصلی", callback_data="menu_start")])
        kb.append([glass_button("🎵 ساخت کپشن (Spotify یا جستجو)", callback_data="create_caption")])
        kb.append([glass_button("🔗 افزودن لینک دستی", callback_data="add_manual_link")])
        kb.append([glass_button("📊 گزارش درخواست‌ها", callback_data="show_logs")])
        kb.append([glass_button("🧭 منوی ادمین", callback_data="admin_menu")])
    else:
        kb.append([InlineKeyboardButton("📩 درخواست موزیک", callback_data="request_music")])
        kb.append([InlineKeyboardButton("📢 درباره کانال", callback_data="menu_start")])
    return InlineKeyboardMarkup(kb)


async def handle_text_message(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = update.effective_chat.id
    text = (update.message.text or "").strip()

    if context.user_data.pop("expecting_user_request", None):
        username = user.username or user.id
        log_user_request(username, "user_request", text)
        await update.message.reply_text("✅ درخواستت ثبت شد — ادمین‌ها در صورت نیاز پیگیری می‌کنند.")
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(admin_id, f"📩 درخواست از @{username}:\n{text}")
            except Exception:
                pass
        return

    if context.user_data.get("manual_kind"):
        kind = context.user_data.pop("manual_kind")
        await handle_manual_link_text(update, context, kind, text)
        return

    if user.id in ADMINS and context.user_data.pop("expecting_search_from_admin", None):
        await admin_search_entry_text(update, context, text)
        return

    await update.message.reply_text("برای عملکرد کامل از منوی ربات استفاده کن یا با /start شروع کن.")


def parse_spotify_url(text):
    if not text:
        return None, None
    m = re.search(r"spotify:(album|track):([A-Za-z0-9]+)", text)
    if m:
        return m.group(1), m.group(2)
    m2 = re.search(r"open\.spotify\.com/(album|track)/([A-Za-z0-9]+)", text)
    if m2:
        return m2.group(1), m2.group(2)
    m3 = re.search(r"(album|track)/([A-Za-z0-9]+)", text)
    if m3:
        return m3.group(1), m3.group(2)
    return None, None


async def handle_manual_link_text(update: Update, context: CallbackContext, kind, text):
    uid = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.id
    log_user_request(username, f"manual_{kind}", text)

    if kind.lower() == "spotify":
        typ, _id = parse_spotify_url(text)
        if typ == "album":
            album_json = spotify_get_album(_id)
            if not album_json:
                await update.message.reply_text("❌ آلبوم Spotify یافت نشد.")
                return
            details = spotify_album_to_details(album_json)
            entry = {
                "title": details.get("title"),
                "artist": details.get("artist"),
                "release_date": details.get("release_date"),
                "tracklist": details.get("tracklist"),
                "cover_url": details.get("cover_url"),
                "url": details.get("url"),
                "tracks_total": details.get("tracks_total", 0)
            }
            user_data[uid] = entry
            save_state()
            await send_preview_for_entry(update, context, uid, entry)
        elif typ == "track":
            track_json = spotify_get_track(_id)
            if not track_json:
                await update.message.reply_text("❌ ترک Spotify یافت نشد.")
                return
            artist = ", ".join(a.get("name") for a in track_json.get("artists", []))
            entry = {
                "title": track_json.get("name"),
                "artist": artist,
                "release_date": track_json.get("album", {}).get("release_date", ""),
                "tracklist": [],
                "cover_url": track_json.get("album", {}).get("images", [{}])[0].get("url"),
                "url": track_json.get("external_urls", {}).get("spotify"),
                "tracks_total": 1
            }
            user_data[uid] = entry
            save_state()
            await send_preview_for_entry(update, context, uid, entry)
        else:
            await update.message.reply_text("لینک Spotify معتبر نیست.")
    elif kind.lower() == "genius":
        details = scrape_song_details_from_url(text)
        if not details:
            await update.message.reply_text("لینک Genius معتبر یا اطلاعات قابل استخراج نیست.")
            return
        entry = {
            "title": details.get("title"),
            "artist": details.get("artist"),
            "release_date": details.get("release_date"),
            "tracklist": details.get("tracklist"),
            "cover_url": details.get("cover_url"),
            "url": details.get("url"),
            "tracks_total": len(details.get("tracklist") or [])
        }
        user_data[uid] = entry
        save_state()
        await send_preview_for_entry(update, context, uid, entry)
    elif kind.lower() == "youtube":
        user_data[uid] = user_data.get(uid, {})
        user_data[uid]["manual_youtube"] = text
        save_state()
        await update.message.reply_text("لینک YouTube ذخیره شد — حالا آلبوم یا ترک را ارسال کنید.")


async def admin_search_entry_text(update: Update, context: CallbackContext, query_text):
    uid = update.effective_chat.id
    query = query_text.strip()
    username = update.effective_user.username or update.effective_user.id
    log_user_request(username, "search", query)

    if "open.spotify.com" in query or "spotify:" in query:
        typ, _id = parse_spotify_url(query)
        if typ == "album":
            album_json = spotify_get_album(_id)
            if not album_json:
                await update.message.reply_text("❌ آلبوم Spotify پیدا نشد یا API پاسخ نداد.")
                return
            details = spotify_album_to_details(album_json)
            entry = {
                "title": details.get("title"),
                "artist": details.get("artist"),
                "release_date": details.get("release_date"),
                "tracklist": details.get("tracklist"),
                "cover_url": details.get("cover_url"),
                "url": details.get("url"),
                "tracks_total": details.get("tracks_total", 0)
            }
            user_data[uid] = entry
            save_state()
            await send_preview_for_entry(update, context, uid, entry)
        elif typ == "track":
            track_json = spotify_get_track(_id)
            if not track_json:
                await update.message.reply_text("❌ ترک Spotify پیدا نشد.")
                return
            artist = ", ".join(a.get("name") for a in track_json.get("artists", []))
            entry = {
                "title": track_json.get("name"),
                "artist": artist,
                "release_date": track_json.get("album", {}).get("release_date", ""),
                "tracklist": [],
                "cover_url": track_json.get("album", {}).get("images", [{}])[0].get("url"),
                "url": track_json.get("external_urls", {}).get("spotify"),
                "tracks_total": 1
            }
            user_data[uid] = entry
            save_state()
            await send_preview_for_entry(update, context, uid, entry)
    else:
        spotify_details = try_spotify_lookup(query)
        if spotify_details:
            entry = {
                "title": spotify_details.get("title"),
                "artist": spotify_details.get("artist"),
                "release_date": spotify_details.get("release_date"),
                "tracklist": spotify_details.get("tracklist") or [],
                "cover_url": spotify_details.get("cover_url"),
                "url": spotify_details.get("url"),
                "tracks_total": spotify_details.get("tracks_total", 0)
            }
            user_data[uid] = entry
            save_state()
            await send_preview_for_entry(update, context, uid, entry)
        else:
            results = genius_search(query)
            if results:
                kb = []
                for r in results[:6]:
                    label = f"💿 {r['full_title']}" if r['type'] != 'song' else f"🎵 {r['full_title']}"
                    kb.append([InlineKeyboardButton(label, callback_data=f"select_genius_{r['id']}")])
                kb.append([InlineKeyboardButton("❌ کنسل", callback_data="menu_start")])
                await update.message.reply_text("نتایج Genius پیدا شد، یکی را انتخاب کنید:",
                                                reply_markup=InlineKeyboardMarkup(kb))
            else:
                await update.message.reply_text(
                    "❌ موردی پیدا نشد. لطفاً لینک Spotify یا Genius ارسال کنید یا عبارت دقیق‌تری بفرستید.")


async def handle_select_genius_callback(query, context):
    data = query.data or ""
    gid = data.replace("select_genius_", "")
    uid = query.message.chat.id
    try:
        from bot.services.genius import GENIUS_API_BASE
        headers = {"Authorization": f"Bearer {context.bot_data['GENIUS_TOKEN']}"}
        r = requests.get(f"{GENIUS_API_BASE}/songs/{gid}", headers=headers, timeout=10)
        r.raise_for_status()
        song = r.json().get("response", {}).get("song", {})
    except Exception as e:
        logger.warning(f"Genius song details failed: {e}")
        await query.message.reply_text("❌ اطلاعات Genius دریافت نشد.")
        return
    song_url = song.get("url")
    scraped = scrape_song_details_from_url(song_url) if song_url else None
    entry = {
        "title": scraped.get("title") if scraped else song.get("title"),
        "artist": scraped.get("artist") if scraped else song.get("primary_artist", {}).get("name"),
        "release_date": scraped.get("release_date") if scraped else "",
        "tracklist": scraped.get("tracklist") if scraped else [],
        "cover_url": scraped.get("cover_url") if scraped else song.get("song_art_image_url"),
        "url": song_url,
        "tracks_total": len(scraped.get("tracklist") or []) if scraped else 1
    }
    user_data[uid] = entry
    save_state()
    await send_preview_for_entry(query, context, uid, entry)


def build_link_buttons(entry):
    btns = []
    if entry.get("url"):
        btns.append(InlineKeyboardButton("🎧 Spotify", url=entry.get("url")))
    if entry.get("title") and entry.get("artist"):
        deezer_search_url = f"https://www.deezer.com/search/{requests.utils.requote_uri(entry.get('title') + ' ' + entry.get('artist'))}"
        btns.append(InlineKeyboardButton("🎵 Deezer", url=deezer_search_url))
    genius_link = find_best_genius_link(entry.get("title"), entry.get("artist"))
    if genius_link:
        btns.append(InlineKeyboardButton("🧠 Genius", url=genius_link))
    if entry.get("manual_youtube"):
        btns.append(InlineKeyboardButton("▶️ YouTube", url=entry.get("manual_youtube")))

    for title, url in custom_buttons.items():
        if url:
            display = title if len(title) <= 50 else title[:47] + "..."
            btns.append(InlineKeyboardButton(display, url=url))
    return btns, genius_link


async def send_preview_for_entry(source_update, context: CallbackContext, uid, entry):
    bot = context.bot
    caption = build_caption(entry)

    link_buttons, _ = build_link_buttons(entry)
    kb = None
    if link_buttons:
        kb = InlineKeyboardMarkup([link_buttons])

    # Prioritize Deezer for HQ covers
    cover_local = download_and_ensure_min_size(
        entry.get("cover_url"),
        title=entry.get("title"),
        artist=entry.get("artist"),
        prefer_hq=True
    )

    if cover_local:
        with open(cover_local, "rb") as photo_fp:
            msg = await bot.send_photo(chat_id=uid, photo=photo_fp, caption=caption, parse_mode=ParseMode.HTML,
                                       reply_markup=kb)
    else:
        msg = await bot.send_message(chat_id=uid, text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    preview_messages[uid] = msg.message_id
    save_state()

    cover_source = "Deezer HQ" if "deezer" in (cover_local or "") else "Spotify"
    await bot.send_message(chat_id=uid, text=f"🎨 کاور از: {cover_source}")


def build_caption(entry, include_tracklist=True):
    title = entry.get("title") or ""
    artist = entry.get("artist") or ""
    release_date = entry.get("release_date") or ""
    tracklist = entry.get("tracklist", []) or []
    tracks_total = entry.get("tracks_total", 0) or 0

    # Prepare channel link with specific formatting
    channel_tag = f'✘<a href="https://t.me/FlyonSpace">FlyonSpace</a>✘'

    is_album = len(tracklist) > 1 or tracks_total > 1

    if not is_album:
        return f"🎙 ▸ {html.escape(f'{artist} - {title}')}\n\n{channel_tag}"

    header = f"🎙 ▸ {html.escape(f'{artist} - {title}')}\n"
    header += f"💽 ▸ Tracks: {tracks_total}\n"
    header += f"📅 ▸ Released: {html.escape(release_date)}\n"
    body = header

    if include_tracklist and tracklist:
        lines = []
        # Check if the first element of the tracklist is a list (multi-disc)
        if tracklist and isinstance(tracklist[0], list):
            for idx, disc in enumerate(tracklist, start=1):
                lines.append(f"💿 CD {idx}:")
                lines.extend(disc)
        else:
            lines.extend(tracklist)

        tracklist_text = "\n".join(lines).strip()
        # Wrap tracklist in a code block for better formatting
        body += f"Tracklist:\n<code>{html.escape(tracklist_text)}</code>\n"

    body += channel_tag
    return body


async def handle_hashtag_selection_by_callback(query, context, tag):
    uid = query.message.chat.id
    if uid not in user_data:
        await query.message.reply_text("❌ اطلاعاتی برای ارسال یافت نشد. دوباره شروع کنید.")
        return
    user_data[uid]["hashtag"] = tag
    save_state()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ ارسال به کانال", callback_data="confirm_send"),
                                InlineKeyboardButton("❌ لغو", callback_data="cancel_send")]])
    await query.edit_message_text("هشتگ ذخیره شد. اکنون می‌توانید ارسال را تایید یا ویرایش کنید.", reply_markup=kb)


async def handle_preview_actions_callback(query, context, action):
    uid = query.message.chat.id
    if action == "cancel_send":
        await query.edit_message_text("🚫 عملیات لغو شد.", reply_markup=None)
        user_data.pop(uid, None)
        preview_messages.pop(uid, None)
        save_state()
    elif action == "confirm_send":
        await handle_confirm_to_channel_callback(query, context)


async def handle_confirm_to_channel_callback(query, context):
    uid = query.message.chat.id
    entry = user_data.get(uid)
    bot = context.bot
    if not entry:
        await query.message.reply_text("❌ اطلاعاتی پیدا نشد. دوباره شروع کنید.")
        return

    caption = build_caption(entry)
    album_buttons, _ = build_link_buttons(entry)
    kb = InlineKeyboardMarkup([album_buttons]) if album_buttons else None

    # Prioritize Deezer for HQ covers in the final post
    cover_local = download_and_ensure_min_size(
        entry.get("cover_url"),
        title=entry.get("title"),
        artist=entry.get("artist"),
        prefer_hq=True
    )

    try:
        if cover_local and len(caption) <= 1024:
            with open(cover_local, "rb") as photo_fp:
                await bot.send_photo(chat_id=CHANNEL_USERNAME, photo=photo_fp, caption=caption,
                                     parse_mode=ParseMode.HTML, reply_markup=kb)
        elif cover_local:
            short_caption = build_caption(entry, include_tracklist=False)
            with open(cover_local, "rb") as photo_fp:
                await bot.send_photo(chat_id=CHANNEL_USERNAME, photo=photo_fp, caption=short_caption,
                                     parse_mode=ParseMode.HTML, reply_markup=kb)
            await bot.send_message(chat_id=CHANNEL_USERNAME, text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await bot.send_message(chat_id=CHANNEL_USERNAME, text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)

        from bot.utils.helpers import add_to_stats
        add_to_stats(entry.get("title", ""), entry.get("artist", ""), query.from_user.username or str(uid))
        await bot.send_message(chat_id=uid, text="🎉 پست با موفقیت به کانال ارسال شد!")
    except Exception as e:
        logger.error(f"Failed to send to channel: {e}")
        await bot.send_message(chat_id=uid, text=f"❌ خطا در ارسال به کانال: {e}")

    user_data.pop(uid, None)
    preview_messages.pop(uid, None)
    save_state()