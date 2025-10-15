from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from bot.handlers.user import main_menu_keyboard
from bot.utils.config import ADMINS, CHANNEL_USERNAME
from bot.utils.helpers import load_json_safe, DATA_FILE, find_channel_id


async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in ADMINS:
        await update.message.reply_text("سلام ادمین! منوی اصلی:", reply_markup=main_menu_keyboard(is_admin=True))
    else:
        await update.message.reply_text("سلام! من ربات موزیک هستم 🎧\nبرای درخواست از دکمه استفاده کنید:",
                                      reply_markup=main_menu_keyboard(is_admin=False))


async def stats_command(update: Update, context: CallbackContext):
    if update.effective_user.id not in ADMINS:
        return
    data = load_json_safe(DATA_FILE, [])
    if not data:
        await update.message.reply_text("📭 هنوز هیچ موزیکی ارسال نشده.")
        return
    total = len(data)
    last = data[-5:]
    msg = f"📊 آمار کلی موزیک‌ها:\n\n🔸 تعداد کل: {total}\n\nآخرین ۵ مورد:\n"
    for item in reversed(last):
        msg += f"- {item['title']} - {item['artist']} ({item['time']})\n"
    await update.message.reply_text(msg)


async def find_channel_command(update: Update, context: CallbackContext):
    if update.effective_user.id not in ADMINS:
        return
    await update.message.reply_text("🔍 در حال تلاش برای پیدا کردن آیدی کانال...")
    channel_id = await find_channel_id(context.bot, CHANNEL_USERNAME)
    if channel_id:
        await update.message.reply_text(
            f"✅ آیدی کانال پیدا شد: `{channel_id}`\nمی‌توانید آن را در متغیر CHANNEL_USERNAME قرار دهید.",
            parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ آیدی کانال پیدا نشد. مطمئن شوید ربات عضو کانال است.")