import logging
import os

from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler

from bot.handlers import admin, user, commands
from bot.utils.config import TOKEN, ADMINS


async def main():
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TOKEN).job_queue(None).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", commands.start))
    application.add_handler(CommandHandler(["menu", "admin"], admin.admin_menu_command))
    application.add_handler(CommandHandler("stats", commands.stats_command))
    application.add_handler(CommandHandler("find_channel", commands.find_channel_command))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(CallbackQueryHandler(user.button_callback))

    # admin reply-keyboard conversation
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^(➕ افزودن دکمه جدید|✏️ ویرایش دکمه|❌ حذف دکمه|🔙 بستن منو)$') & filters.User(user_id=ADMINS), admin.admin_menu_reply_handler)],
        states={
            admin.ADD_BUTTON: [MessageHandler(filters.TEXT & filters.User(user_id=ADMINS), admin.admin_add_button_step)],
            admin.EDIT_CHOOSE: [MessageHandler(filters.TEXT & filters.User(user_id=ADMINS), admin.admin_edit_button_choose)],
            admin.EDIT_STEP: [MessageHandler(filters.TEXT & filters.User(user_id=ADMINS), admin.admin_edit_button_step)],
            admin.REMOVE_STEP: [MessageHandler(filters.TEXT & filters.User(user_id=ADMINS), admin.admin_remove_button_step)]
        },
        fallbacks=[CommandHandler('cancel', admin.cancel_conversation)]
    )
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user.handle_text_message))

    # Run the bot until the user presses Ctrl-C
    await check_channel_access(application.bot)
    application.run_polling()


if __name__ == "__main__":
    import asyncio
    from bot.utils.helpers import check_channel_access

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
    )
    asyncio.run(main())