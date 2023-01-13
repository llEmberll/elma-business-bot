import traceback
import telebot
import ssl
import time
import datetime
import logging
from task_bot import Task_bot
from aiohttp import web
from configparser import ConfigParser


main_config = ConfigParser()
db_config = ConfigParser()
main_config.read("config.ini")
db_config.read("dbtables.ini")

logging.basicConfig(filename=main_config['LOG']['filename'], level=logging.INFO)

bot_token = main_config['TG']['bot_token']
bot = telebot.TeleBot(bot_token)

email_for_registration_example = main_config['ELMA']['correct_email_for_registration_example']

#Защитный токен для проверки подлинности вебхуков от элмы
elma_webhook_token = main_config['ELMA']['elma_webhook_token']

#[Настрйки веб-хука]#
WEBHOOK_PORT_LOCAL = main_config['WEBHOOK']['WEBHOOK_PORT_LOCAL']
WEBHOOK_LISTEN = main_config['WEBHOOK']['WEBHOOK_LISTEN']

WEBHOOK_SSL_CERT = main_config['WEBHOOK']['WEBHOOK_SSL_CERT']
WEBHOOK_SSL_PRIV = main_config['WEBHOOK']['WEBHOOK_SSL_PRIV']

WEBHOOK_URL_BASE = "https://%s:%s" % (main_config['WEBHOOK']['WEBHOOK_HOST'], int(main_config['WEBHOOK']['WEBHOOK_PORT']))
WEBHOOK_URL_PATH = "/%s/" % (bot_token)

app = web.Application()


def on_exception(message, error):
    print(message, f"\n\n{error}\n")
    time = datetime.datetime.now()
    logging.error(
        f"\n-------------{time}--------------\n{message}\n\nError:\n{error}\n"
    )


# Проверка приватности перехваченного сообщения
def is_private_chat_id(chat_id) -> bool:
    if chat_id < 0:
        return False
    return True


# Прием API запросов от телеграмма
async def telegram_handle(request):
    request_body_dict = await request.json()
    update = telebot.types.Update.de_json(request_body_dict)
    bot.process_new_updates([update])

    return web.Response()


# Прием API запросов от элмы
async def elma_handle(request):
    match_info = request.match_info

    try:
        request_body_dict = await request.json()

        # Проверка защитного токена
        if match_info.get('token') == elma_webhook_token:
            if match_info.get('action') == 'new-status':
                # Уведолмение автора задачи об изменении её статуса
                try:
                    taskbot = Task_bot(bot, logging, main_config, db_config)
                    taskbot.on_new_status_request(request_body_dict)
                except Exception as e:
                    on_exception(f"При уведомлении автора задачи о новом статусе прозиошла ошибка"
                                 f"\nrequest_body_dict: {request_body_dict}\nmatch info: {match_info}", traceback.format_exc())

            return web.Response()
        else:
            on_exception(
                f"Неверный токен при отправке вебхука от элмы\n"
                f"request_body_dict: {request_body_dict}\nmatch info: {match_info}\n"
                f"input token: {match_info.get('token')}",
                f"Wrong elma secure token, must be: {elma_webhook_token}"
                        )

    except Exception as e:
        on_exception(f"Невалидное тело в запросе от элмы"
                 f"\nmatch info: {match_info}", traceback.format_exc())


#[Маршрутизация]#
app.add_routes([
                web.post('/elma/{action}/{token}/', elma_handle),   # Прием входящих от элмы запросов
                web.post(f'/{bot_token}/', telegram_handle)
                ])


###Перехват команды /menu###
@bot.message_handler(commands=['menu'])
def reaction(message):
    try:
        chat_id = message.chat.id
        if is_private_chat_id(chat_id):
            taskbot = Task_bot(bot, logging, main_config, db_config)
            auth_status = taskbot.user_authorization(chat_id)
            if auth_status['success']:
                taskbot.show_menu(chat_id)
    except Exception as e:
        on_exception(f"Error in handle command: /menu\nmessage: {message}", traceback.format_exc())


###Перехват команды /auth###
@bot.message_handler(commands=['auth'])
def reaction(message):
    try:
        chat_id = message.chat.id
        if is_private_chat_id(chat_id):
            taskbot = Task_bot(bot, logging, main_config, db_config)

            # Проверка статуса авторизации юзера
            auth_status = taskbot.user_authorization(chat_id)
            if auth_status['success']:
                taskbot.show_menu(chat_id, "Вы уже авторизованы!")
            else:
                taskbot.bot.send_message(chat_id, f"Для авторизации введите емеил, пример: {email_for_registration_example}", parse_mode='Markdown')
    except Exception as e:
        on_exception(f"Error in handle command: /auth\nmessage: {message}", traceback.format_exc())


###Перехват текстовых сообщений сообщений###
@bot.message_handler(content_types=['text'])
def reaction(message):
    try:
        chat_id = message.chat.id
        if is_private_chat_id(chat_id):
            taskbot = Task_bot(bot, logging, main_config, db_config)
            taskbot.start(message)
            return
    except Exception as e:
        on_exception(f"Error in handle text message\nmessage: {message}", traceback.format_exc())


###Обработчик inline кнопок в сообщениях###
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    callback_data = call.data

    try:
        taskbot = Task_bot(bot, logging, main_config, db_config)
        taskbot.callback_handle(call)
    except Exception as e:
        on_exception(f"Error in handle inline buttons\ncallback data: {callback_data}", traceback.format_exc())


###Перехват фото###
@bot.message_handler(content_types=['photo'])
def reaction(message):
    chat_id = message.chat.id
    if is_private_chat_id(chat_id):
        # Функционал в разработке
        print("photo!")


def main():
    # Снятие вебхука телеграмма
    bot.remove_webhook()
    time.sleep(1)

    # Установка вебухка телеграмма
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH,
                    certificate=open(WEBHOOK_SSL_CERT, 'r'))

    # Установка настроек сервера
    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    context.load_cert_chain(WEBHOOK_SSL_CERT, WEBHOOK_SSL_PRIV)

    # Запуск приложения
    web.run_app(
        app,
        host=WEBHOOK_LISTEN,
        port=WEBHOOK_PORT_LOCAL,
        ssl_context=context,
    )

main()