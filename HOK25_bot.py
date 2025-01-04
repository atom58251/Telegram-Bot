import uuid
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import pandas as pd
import os
from dotenv import load_dotenv
import nest_asyncio
import asyncio

load_dotenv()

# Загрузка токена и ID администратора из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN или ADMIN_ID не найдены в переменных окружения.")

nest_asyncio.apply()

# Переменная для отслеживания того, кто ожидает ответа
waiting_for_response = None

# Функция для сохранения данных в базу данных SQLite
def save_to_db(user_id, user_name, user_username, user_message):
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    # Создаем таблицу, если она не существует
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        UserID INTEGER,
        MessageID TEXT PRIMARY KEY,
        Name TEXT,
        Username TEXT,
        Message TEXT,
        AdminResponse TEXT
    )
    ''')
    # Генерация уникального идентификатора сообщения
    message_id = str(uuid.uuid4())
    # Вставляем данные
    cursor.execute(
        "INSERT INTO users (UserID, MessageID, Name, Username, Message) VALUES (?, ?, ?, ?, ?)",
        (user_id, message_id, user_name, user_username, user_message)
    )
    conn.commit()
    conn.close()
    return message_id

# Функция для сохранения ответа администратора
def save_admin_response(message_id, admin_response):
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET AdminResponse = ? WHERE MessageID = ?",
        (admin_response, message_id)
    )
    conn.commit()
    conn.close()

# Функция для экспорта данных в CSV
def export_to_csv():
    conn = sqlite3.connect("user_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    df = pd.DataFrame(rows, columns=["UserID", "MessageID", "Name", "Username", "Message", "AdminResponse"])
    csv_filename = "user_data.csv"
    df.to_csv(csv_filename, index=False)
    conn.close()
    return csv_filename

# Команда для выгрузки данных в CSV
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != int(ADMIN_ID):
        await update.message.reply_text("Вы не являетесь администратором!")
        return
    csv_filename = export_to_csv()
    with open(csv_filename, "rb") as f:
        await update.message.reply_document(document=f, filename=csv_filename)

# Главная команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Часто задаваемые вопросы", callback_data="faq"),
         InlineKeyboardButton("Завершить чат", callback_data="end_chat")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Выберите опцию:", reply_markup=reply_markup)

# Обработка кнопок
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    global waiting_for_response

    if query.data == "faq":
        keyboard = [
            [InlineKeyboardButton("Общие вопросы", callback_data="general"),
             InlineKeyboardButton("Техническая поддержка", callback_data="tech_support")],
            [InlineKeyboardButton("Задать вопрос", callback_data="ask_question")],
            [InlineKeyboardButton("Завершить чат", callback_data="end_chat")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выберите тему:", reply_markup=reply_markup)
    elif query.data == "ask_question":
        await query.edit_message_text("Напишите ваш вопрос администратору.")
    elif query.data == "end_chat":
        await query.edit_message_text("Спасибо за использование бота. Чат завершен.")
    elif query.data.startswith("respond_"):
        _, user_id, message_id = query.data.split("_")
        waiting_for_response = (int(user_id), message_id)
        await query.edit_message_text("Напишите ваш ответ.")

# Обработка текстовых сообщений от администратора
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_response

    if waiting_for_response:
        user_id, message_id = waiting_for_response
        admin_response = update.message.text

        # Извлекаем вопрос пользователя из базы данных
        conn = sqlite3.connect("user_data.db")
        cursor = conn.cursor()
        cursor.execute("SELECT Message FROM users WHERE MessageID = ?", (message_id,))
        question = cursor.fetchone()[0]  # Получаем вопрос
        conn.close()

        # Отправляем пользователю вопрос и ответ
        response_message = f"Ваш вопрос: {question}\n\n {admin_response}"
        await context.bot.send_message(chat_id=user_id, text=response_message)

        # Сохраняем ответ в базу данных
        save_admin_response(message_id, admin_response)

        # Уведомляем администратора, что ответ отправлен, и показываем вопрос
        admin_message = f"Ответ на вопрос от пользователя: {user_id}\n" \
                        f"Сообщение: {question}\n\n" \
                        f"Ответ администратора: {admin_response}"
        await update.message.reply_text(admin_message)

        # Сбрасываем ожидание ответа
        waiting_for_response = None
    else:
        user = update.message.from_user
        user_message = update.message.text
        message_id = save_to_db(user.id, user.full_name, user.username, user_message)

        # Уведомляем администратора
        message_to_admin = f"Вопрос от пользователя: {user.full_name}\n" \
                           f"ID пользователя: {user.id}\n" \
                           f"Юзернейм: @{user.username}\n\n" \
                           f"Сообщение: {user_message}"
        keyboard = [
            [InlineKeyboardButton("Ответить", callback_data=f"respond_{user.id}_{message_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=ADMIN_ID, text=message_to_admin, reply_markup=reply_markup)



# Главная функция
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CommandHandler("export", export_data))

    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
