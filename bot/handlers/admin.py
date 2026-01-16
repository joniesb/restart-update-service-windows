import logging

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import CallbackContext, ConversationHandler

from bot.utils.helpers import custom_buttons, save_state
from bot.utils.config import ADMINS

logger = logging.getLogger(__name__)

# states for ConversationHandler for admin add/edit/remove
(ADD_BUTTON, EDIT_CHOOSE, EDIT_STEP, REMOVE_STEP) = range(4)


async def admin_menu_command(update: Update, context: CallbackContext):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("🔒 فقط ادمین‌ها دسترسی دارند.")
        return
    await update.message.reply_text("🎛 منوی مدیریت ربات:", reply_markup=admin_reply_kb())


def admin_reply_kb():
    keyboard = [["➕ افزودن دکمه جدید", "✏️ ویرایش دکمه"], ["❌ حذف دکمه", "🔙 بستن منو"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


async def admin_menu_reply_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("🔒 فقط ادمین‌ها دسترسی دارند.")
        return
    text = (update.message.text or "").strip()
    if text == "➕ افزودن دکمه جدید":
        await update.message.reply_text(
            "لطفاً عنوان و لینک دکمه را به فرمت زیر ارسال کن:\nمثال:\n🌐 وبسایت | https://example.com",
            reply_markup=ReplyKeyboardRemove())
        return ADD_BUTTON
    if text == "✏️ ویرایش دکمه":
        if not custom_buttons:
            await update.message.reply_text("هیچ دکمه‌ی سفارشی‌ای وجود ندارد.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        titles = "\n".join(f"- {t}" for t in custom_buttons.keys())
        await update.message.reply_text(
            f"دکمه‌های فعلی:\n{titles}\n\nلطفاً عنوان دکمه‌ای که می‌خواهی ویرایش کنی را بفرست (دقیقا).",
            reply_markup=ReplyKeyboardRemove())
        return EDIT_CHOOSE
    if text == "❌ حذف دکمه":
        if not custom_buttons:
            await update.message.reply_text("هیچ دکمه‌ی سفارشی‌ای وجود ندارد.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        titles = "\n".join(f"- {t}" for t in custom_buttons.keys())
        await update.message.reply_text(
            f"دکمه‌های فعلی:\n{titles}\n\nلطفاً عنوان دکمه‌ای که می‌خواهی حذف کنی را بفرست (دقیقا).",
            reply_markup=ReplyKeyboardRemove())
        return REMOVE_STEP
    if text == "🔙 بستن منو":
        await update.message.reply_text("منو بسته شد.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    await update.message.reply_text("عمل نامشخص. از منوی مدیریت استفاده کن.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def admin_add_button_step(update: Update, context: CallbackContext):
    text = (update.message.text or "").strip()
    if "|" not in text:
        await update.message.reply_text("فرمت اشتباه است. لطفاً مثل مثال زیر ارسال کن:\n🌐 وبسایت | https://example.com")
        return ConversationHandler.END
    title, url = [s.strip() for s in text.split("|", 1)]
    if not title or not url:
        await update.message.reply_text("عنوان یا لینک خالی است. دوباره تلاش کن.")
        return ConversationHandler.END
    custom_buttons[title] = url
    save_state()
    await update.message.reply_text(f"✅ دکمه '{title}' اضافه شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def admin_edit_button_choose(update: Update, context: CallbackContext):
    title = (update.message.text or "").strip()
    if title not in custom_buttons:
        await update.message.reply_text("عنوان یافت نشد. عملیات کنسل شد.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    context.user_data["editing_old_title"] = title
    await update.message.reply_text(
        "لطفاً عنوان جدید و لینک جدید را به فرمت زیر ارسال کن:\nمثال:\n🌐 وبسایت جدید | https://new.example.com",
        reply_markup=ReplyKeyboardRemove())
    return EDIT_STEP


async def admin_edit_button_step(update: Update, context: CallbackContext):
    old_title = context.user_data.get("editing_old_title")
    text = (update.message.text or "").strip()
    if "|" not in text:
        await update.message.reply_text("فرمت اشتباه است. لطفاً مثل مثال زیر ارسال کن:\n🌐 وبسایت جدید | https://new.example.com")
        return ConversationHandler.END
    new_title, url = [s.strip() for s in text.split("|", 1)]
    if not new_title or not url:
        await update.message.reply_text("عنوان یا لینک خالی است. دوباره تلاش کن.")
        return ConversationHandler.END
    custom_buttons.pop(old_title, None)
    custom_buttons[new_title] = url
    save_state()
    await update.message.reply_text(f"✅ دکمه '{old_title}' ویرایش شد -> '{new_title}'",
                                    reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def admin_remove_button_step(update: Update, context: CallbackContext):
    title = (update.message.text or "").strip()
    if title not in custom_buttons:
        await update.message.reply_text("عنوان یافت نشد. عملیات کنسل شد.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    custom_buttons.pop(title, None)
    save_state()
    await update.message.reply_text(f"✅ دکمه '{title}' حذف شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: CallbackContext):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END