import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен
TOKEN = None

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start. Отправляет приветственное сообщение пользователю
    """
    try:
        await update.message.reply_text("Привет! Я бот, который помогает отслеживать цены на ваши CS2 предметы")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {e}")

# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /help. Отправляет вспомогательную информацию пользователю
    """
    try:
        await update.message.reply_text("Здесь должна быть вспомогательная информация")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения: {e}")

# Обработчик текстовых сообщений
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик текстовых сообщений. Отправляет обратно то, что написал пользователь
    """
    text = update.message.text
    if text is None:
        try:
            await update.message.reply_text("Я понимаю только текст")
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения: {e}")
    else:
        try:
            await update.message.reply_text(f"Твое сообщение: {text}")
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения: {e}")

def main():
    global TOKEN
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set in environment")

    # Создаём приложение
    app = Application.builder().token(TOKEN).build()

    # Обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Запускаем бота в режиме Long Polling
    print("Бот запущен. Нажмите Ctrl+C для остановки")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()