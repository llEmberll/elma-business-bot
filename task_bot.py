import traceback
import datetime
import re
import requests
import json
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from requests.adapters import HTTPAdapter, Retry
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from json import loads
from db_operator import Db_operator
from telebot.types import ReplyKeyboardRemove, \
    ReplyKeyboardMarkup, KeyboardButton, \
    InlineKeyboardMarkup, InlineKeyboardButton

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class Task_bot:
    telegram_update = None
    user = None
    user_message_text = ''

    elma_bot_user = None

    keyboard_main_menu = None


    def __init__(self, bot, logging, main_config, db_config):
        self.logging = logging
        self.bot = bot
        self.main_config = main_config
        self.db_config = db_config

        self.database = Db_operator(self.main_config, self.db_config, self.logging)

        self.elma_home_domain = main_config['ELMA']['home_domain']

        self.admin_token = main_config['ELMA']['admin_token']
        self.admin_chat_id = main_config['TG']['admin_chat_id']
        
        self.not_registered_chat_id = main_config['TG']['not_registered_chat_id']

        self.headers = {
                        'GET':
                                {
                                    'Authorization': f"Bearer {self.admin_token}"
                                },
                        'POST':
                                {
                                    'Authorization': f'Bearer {self.admin_token}',
                                    'Content-Type': 'application/json'
                                }
        }


        # Загрузка json файлов
        with open(main_config['DB']['elma_data_path'], encoding="utf8") as file:
            self.elma_data = json.load(file)
        with open(main_config['DB']['reply_buttons_data_path'], encoding="utf8") as file:
            self.reply_buttons_data = json.load(file)
        with open(main_config['DB']['inline_buttons_data_path'], encoding="utf8") as file:
            self.inline_buttons_data = json.load(file)
        with open(main_config['DB']['status_data_path'], encoding="utf8") as file:
            self.status_data = json.load(file)

        self.elma_bot_user = {'id': main_config['ELMA']['admin_user_elma_id'],
                              'email': main_config['ELMA']['admin_user_email'],
                              'name': main_config['ELMA']['admin_user_name']}

        self.example_email = main_config['ELMA']['correct_email_for_registration_example']

        self.business_process_name = main_config['ELMA']['business_process_name']

        self.main_project = self.elma_data['projects'][main_config['ELMA']['main_project_name']]
        self.main_section = self.elma_data['projects'][self.main_project['name']]['sections'][main_config['ELMA']['main_section_name']]


    # Уведолмение автора задачи об изменении её статуса
    def on_new_status_request(self, request_data):
        if 'customer' in request_data:
            customer = request_data['customer']

            # Если автор задачи это элма бот, значит уведомлять некого
            if (customer == self.elma_bot_user['email']):
                return

            # Поиск юзера по емеилу в базе
            self.user = self.database.find_user_by_email(customer)

            if self.user is not None:
                try:
                    # Перевод входящего статуса задачи в человеческий вид
                    status_data = self.status_data[f"{request_data['status']}"]
                    status = status_data['view']
                except Exception as e:
                    status = 'Неизвестно'

                text = f"⚙️ Новый статус задачи [{request_data['__name']}]({request_data['request_url']}): *{status}*"

                self.bot.send_message(self.user['telegram_chat_id'], text, parse_mode='Markdown')
                return
            self.on_exception("При отправке уведомления о новом статусе не найден юзер в базе", f"{request_data}", self.not_registered_chat_id)


    # Обработка нажатия inline кнопок телеграмма
    def callback_handle(self, call):
        # Декодирование данных, спрятанных в кнопке
        decoded_call_data = json.loads(call.data)

        self.chat_id = call.from_user.id

        # Получение статуса авторизаци юзера
        auth = self.user_authorization(self.chat_id)

        if auth['success']:
            self.authorized_callback(decoded_call_data)
        else:
            self.not_authorized_callback()


    def start(self, telegram_update_data):
        #Создание inline меню
        self.inline_keyboard = self.create_inline_keyboard(self.inline_buttons_data['another_chapter_example'])

        self.telegram_update = telegram_update_data
        self.chat_id = self.telegram_update.chat.id
        self.user_message_text = self.telegram_update.text

        auth = self.user_authorization(self.chat_id)
        if auth['success']:
            if auth['message'] == 'Регистрация была успешно завершена!':
                self.on_registration(self.chat_id, auth['message'])
                return
            self.on_authorize()
        else:
            self.on_not_authorize(auth['message'])


    # Действия при регистрации
    def on_registration(self, chat, text="Добро пожаловать!"):
        self.show_menu(chat, text)


    # Действия при неавторизованном нажатии inline кнопки
    def not_authorized_callback(self):
        self.bot.send_message(self.chat_id, "Для авторизации используйте команду /auth")


    # Действия при авторизованном нажатии inline кнопки
    def authorized_callback(self, decoded_call_data):
        call_type = decoded_call_data.get('type')

        if call_type is not None:
            if call_type == 'ClearRequest':
                res_clear = self.database.clear_user_fields_by_id(self.user['id'])
                self.show_menu(self.chat_id)
            elif call_type == 'SendRequest':
                self.on_send_request_click()
            elif call_type == 'type_for_example1':
                if 'id' in decoded_call_data:
                    self.provide_to_elma(self.chat_id, decoded_call_data['id'])
        else:
            # Показ подробной информации о нажатой задаче
            self.on_show_task_click(decoded_call_data)


    # Действия при нажатии на задачу
    def on_show_task_click(self, decoded_call_data):
        if 'i' in decoded_call_data:
            # Проект и раздел для создания ссылки на задачу
            project = self.get_project_by_id(decoded_call_data.get('p'))
            section = self.get_section_by_id(project['name'], decoded_call_data.get('s'))

            if project == None or section == None:
                self.bot.send_message(self.admin_chat_id,
                                      f"Не удалось найти пространство в элме. \nАйди проекта: {decoded_call_data.get('p')}\n{decoded_call_data.get('s')}\n"
                                      )

                self.show_menu(self.chat_id, "Не удалось найти пространство запроса в elma")

                self.on_exception(f"Не удалось найти пространство в элме. \nАйди проекта: {decoded_call_data.get('p')}\n{decoded_call_data.get('s')}\n",
                                  f"project or section == None")

            # Получении информации о задаче по айди в элме
            request_data = self.web_query(
                'POST',
                f"https://elma365.{self.elma_home_domain}/pub/v1/app/{self.main_project['code_name']}/{self.main_section['code_name']}/{decoded_call_data['i']}/get",
                json.dumps(
                            {}
                          )
                                          )

            if request_data is not None:
                if request_data['success'] == False:
                    if 'not found' in request_data['error']:
                        text = "Не удалось найти запрос"
                    else:
                        text = "При получении запроса сервис вернул ошибку"

                    self.on_exception(f"Безуспешный показ задачи\ncall data: {decoded_call_data}", request_data['error'])
                    self.show_menu(self.chat_id, text)
                else:
                    # Настройка выводимых полей и их порядка
                    # (информация о полях должна быть заранее записана в local_base/elma_projects_data)
                    fields_for_display = ['summary', 'description', 'status', 'executor']

                    res_show = self.show_request(request_data, project, section, fields_for_display)
                    if not res_show:
                        self.show_menu(self.chat_id, "Не удалось получить поля запроса")
            return
        self.show_menu("При обработке кнопки произошла ошибка")


    # Действия при нажатии кнопки "Отправить запрос"
    def on_send_request_click(self):
        #Получение полей юзера
        send_data = self.database.get_user_request_data_by_id(self.user['id'])

        if (send_data is not None):
            # Подготовка контекстных полей для создания задачи
            request_fields = {
                self.main_section['fields']['summary']['code_name']: send_data['summary'],
                self.main_section['fields']['description']['code_name']: send_data['description'],
                self.main_section['fields']['customer']['code_name']: [send_data['author_id']]
            }

            create_url = f"https://elma365.{self.elma_home_domain}/pub/v1/app/{self.main_project['code_name']}/{self.main_section['code_name']}/create"
            create_body = json.dumps({"context": request_fields})
            res_send = self.web_query(
                                        'POST',
                                        create_url,
                                        create_body,
                                     )

            if res_send is not None:
                if res_send['success']:
                    self.show_menu(self.chat_id, "Запрос создан")
                    request_id = res_send['item']['__id']

                    # Запуск бизнес процесса для запроса
                    res_run = self.run_business_process(self.main_project['code_name'], self.main_section['code_name'], self.business_process_name, request_id)

                else:
                    error = res_send['error']
                    self.on_exception(f"При создании задачи произошла ошибка({self.user['email']})\n"
                                      f"url: {create_url}\n"
                                      f"body: {create_body}\n"
                                      f"raw_send_data: {send_data}\n",
                                      error
                                      )
                    self.show_menu(self.chat_id, f"При создании запроса произошла ошибка:\n{error}")
            else:
                self.show_menu(self.chat_id, f"При создании запроса произошла ошибка")

        else:
            self.show_menu(self.chat_id, "Недостаточно заполненных полей для создания запроса")

        res_clear = self.database.clear_user_fields_by_id(self.user['id'])


    # Запуск бизнес процесса для запроса
    def run_business_process(self, project, section, process_name, request_id):
        run_url = f"https://elma365.{self.elma_home_domain}/pub/v1/bpm/template/{project}.{section}/{process_name}/run"
        run_body = json.dumps({
            "context": {
                f"{self.main_section['code_name']}": [
                    f"{request_id}"
                ]
            }
        })
        return self.web_query(
            'POST',
            run_url,
            run_body,
        )


    # Получить кнопки, которые видимы для юзера
    def get_buttons_by_user_groups(self, groups):
        buttons = self.reply_buttons_data['common']
        for group in groups:
            # Каждая группа это уровень доступа, открывающий определенные кнопки, поиск доступных разделов
            if group in self.reply_buttons_data:
                current_reply_buttons_data = self.reply_buttons_data[group]

                # Добавление всех кнопок из текущего доступного раздела
                for button_data in current_reply_buttons_data:
                    buttons.append(button_data)

        return buttons


    # Действия при неавторизованном доступе
    def on_not_authorize(self, message):
        text = f"Вы не авторизованы!\nДля авторизации введите емеил,соответствующий примеру:\n{self.example_email}"
        if len(message) > 0:
            text = f"{message}\nДля авторизации введите емеил,соответствующий примеру:\n{self.example_email}"

        self.bot.send_message(self.chat_id, text)


    # Действия при авторизованном доступе
    def on_authorize(self):
        # self.show_menu(self.chat_id, "Вы авторизованы!")

        # Формирование доступных юзеру кнопок для создания основной клавиатуры
        needle_buttons = self.get_buttons_by_user_groups(self.user['groups'])

        # Создание основного меню
        self.keyboard_main_menu = self.create_reply_keyboard(needle_buttons)

        res_parse = self.parse_message()
        if (res_parse == None):
            self.show_menu(self.chat_id, "При обработке сообщения произошла ошибка")
            return

        if res_parse['button'] == None:
            if not res_parse['reply']:
                if len(self.user_message_text) > 0:
                    self.on_simple_text_message(res_parse)

                else:
                    self.show_menu(self.chat_id, "Тело запроса не может быть пустым")

        else:
            self.on_reply_button(res_parse['button'])
            # Очистка полей для создания задачи по айди юзера
            res_clear = self.database.clear_user_fields_by_id(self.user['id'])


    # Реакция на простое текстовое сообщение
    def on_simple_text_message(self, res_parse_message):
        # Установка автора для будущей задачи(подготовка к созданию задачи происходит сразу после приема текстового сообщения)
        author = self.set_author_for_request_by_message(res_parse_message)

        is_long_message = len(self.user_message_text) > 50

        # Заполнение в базе данных полей для создания задачи, используя сообщение юзера
        request_fields = self.base_request_data_from_message(self.user_message_text, author, is_long_message)

        # Сохранение записанных полей
        res_fill = self.database.fill_user_request_fields(request_fields)

        # Создание клавиатуры для отправки базового запроса
        inline_keyboard = self.create_inline_keyboard(self.inline_buttons_data['base_request_actions'])

        self.bot.send_message(self.chat_id, f"Тема: {request_fields['summary']}\nОтправить запрос?",
                              reply_markup=inline_keyboard)


    # Установка автора для будущей задачи
    def set_author_for_request_by_message(self, message):
        author = None
        if message['forward']:
            # Если сообщение переслано, автором задачи будет автор оригинального сообщения
            user_by_chat_id = self.database.find_user_by_chat_id(self.telegram_update.forward_from.id)
            if user_by_chat_id is not None:

                author = self.find_elma_user_by_email(user_by_chat_id['email'])
            else:
                # Если сообщение пересланное, но автора оригинала не удалось найти, автором задачи будет отправитель сообщения боту
                author = self.find_elma_user_by_email(self.user['email'])

        else:
            # Автор задачи - отправитель сообщения боту
            author = self.find_elma_user_by_email(self.user['email'])
        if author == None or not author:
            self.bot.send_message(self.admin_chat_id,
                                  "Не удалось установить автора задачи, поэтому автором назначен бот")

            # При безуспешном нахождении данных о юзере, автором будет элма бот
            author = self.elma_bot_user
        return author


    # Получение проекта по его айди(работа с локальной базой данных json формата)
    def get_project_by_id(self, id):
        for project in self.elma_data['projects']:
            if self.elma_data['projects'][project]['id'] == id:
                return self.elma_data['projects'][project]
        return None


    # Получение секции по её айди(работа с локальной базой данных json формата)
    def get_section_by_id(self, project, id):
        for section in self.elma_data['projects'][project]['sections']:
            if self.elma_data['projects'][project]['sections'][section]['id'] == id:
                return self.elma_data['projects'][project]['sections'][section]
        return None


    # Подготовка полей для создания запроса юзером, используя входящее сообщение
    def base_request_data_from_message(self, message, author, is_long_message=False):
        try:
            summary = re.sub("^\s+|\n|\r|\s+$", ' ', message)
            description = summary

            if is_long_message:
                # Обрезка названия задачи, если текст слишком велик
                summary = summary[:47] + "..."

            return {'summary': summary, 'description': description, 'author_id': author['id'], 'user_id': self.user['id']}
        except Exception as e:
            return self.on_exception("При парсе сообщения на поля базового запроса произошла ошибка", traceback.format_exc())


    # Получение задач юзера в конкретном разделе по его айди в элме
    def get_user_requests(self, user_elma_id, project, section):
        # Подготовка фильтра по статусам задач
        #(Информация о статусах должна быть заранее прописана в local_base/status_data)
        needle_statuses = [
                              1,
                              2,
                              3,
                              4,
                              7
                          ]
        try:
            # Подготовка поля, по которому будет фильтрация поиска задачи
            filter_author_field = section['fields']['customer']['code_name']

            # Получение списка задач из элмы с фильтром на пользователя и статусы задач
            requests_json = self.web_query(
                'POST',
                f"https://elma365.{self.elma_home_domain}/pub/v1/app/{project['code_name']}/{section['code_name']}/list",
                json.dumps(
                            {
                                "active": True,
                                "filter": {
                                    "tf": {
                                        filter_author_field: f"{user_elma_id}",
                                        "__status": needle_statuses
                                    }
                                },
                                "size": 20
                            }
                          )
                                          )

            if requests_json['success']:
                return self.collect_requests_by_user_requests(requests_json['result']['result'])
            else:
                if requests_json['error'] == 'not found':
                    return []

                return self.on_exception("При получении запросов элма вернула ошибку", requests_json['error'])
        except Exception as e:
            return self.on_exception("При получении запросов произошла ошибка", traceback.format_exc())


    # Собрать задачи юзера(парсинг)
    def collect_requests_by_user_requests(self, requests_data):
        user_requests = []

        for request in requests_data:
            user_requests.append({'name': f"{request['__name']}", 'id': f"{request['__id']}"})
        return user_requests


    # Создание reply клавиатуры
    def create_reply_keyboard(self, buttons_data):
        keyboard = ReplyKeyboardMarkup(True)

        for element in buttons_data:
            keyboard.add(KeyboardButton(element['text']))
        return keyboard


    # Найти юзера элмы, используя емеил(кастомный апи метод элмы)
    # Элма не отправляет достаточно инфорации о юзере из стандартных api методов,
    # Поэтому лучше создать свой метод в элме, принимающий в параметр емеил и отдающий id юзера элмы, имя, тег телеграмма, заранее прописанный в учетке элмы(нужно для связи юзера элмы с тг юзером)
    # и группы, в которых состоит юзер
    def find_elma_user_by_email(self, email):
        try:
            url = f"https://elma365.{self.elma_home_domain}/api/extensions/SOME_PATH_TO_API_METHOD/script/extentionapi/METHOD_NAME?email={email}"
            payload = {}

            response_json = self.web_query('GET', url, payload)
            if response_json is not None:
                if 'msg' in response_json:
                    if response_json['msg'] == 'success':
                        if 'useruid' in response_json and 'name' in response_json and 'groups' in response_json:
                            elma_user = {'id': response_json['useruid'], 'email': email, 'name': response_json['name'], 'tags': response_json['tags'], 'groups': response_json['groups']}
                            return elma_user

                        return None
            return self.on_exception(f"Не удалось найти такого юзера в элме({email})", response_json)
        except Exception as e:
            return self.on_exception("Ошибка при получении юзера по емеилу", traceback.format_exc())


    def validate_email(self, email) -> bool:
        if re.fullmatch(r'([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[a-z]{2,16}\.[a-z]{2,16}', email): return True
        return False


    # Статус авторизации юзера
    def user_authorization(self, chat_id):
        # Выборка записи в таблице юзеров по чат айди телеграмма
        res_find = self.database.find_user_by_chat_id(chat_id)
        if res_find == None:
            # Запись не найдена

            if self.validate_email(self.user_message_text):
                # Если сообщением юзера был корректный емеил

                email = self.user_message_text

                #Поиск юзера элмы по емеилу
                elma_user = self.find_elma_user_by_email(email)
                if elma_user is not None:
                    # юзер в элме найден
                    if f"@{self.telegram_update.from_user.username}" in elma_user['tags']:
                        # У элма юзера есть отсылка на телеграмм аккаунт текущего юзера

                        # Добавление юзера в базу
                        res_add_record = self.database.add_user(chat_id, email)

                        if res_add_record:
                            res_find = self.database.find_user_by_chat_id(chat_id)

                            # Обновление юзера, с которым сейчас ведется работа
                            self.user = (
                            {'id': res_find['id'], 'useruid': elma_user['id'], 'email': email, 'chat_id': chat_id,
                             'groups': elma_user['groups']})

                            # Формирование доступных юзеру кнопок для создания основной клавиатуры
                            needle_buttons = self.get_buttons_by_user_groups(self.user['groups'])

                            # Создание основного меню
                            self.keyboard_main_menu = self.create_reply_keyboard(needle_buttons)

                            return {'success': True, 'message': "Регистрация была успешно завершена!"}
                        else:
                            return {'success': False, 'message': "Не удалось добавить запись в базу"}
                    else:
                        return {'success': False, 'message': "Не удалось подтвердить, что данная учетная запись принадлежит вам"}
                else:
                    return {'success': False, 'message': "Не удалось найти пользователя с такой почтой"}

            return {'success': False, 'message': ""}
        else:
            elma_user = self.find_elma_user_by_email(res_find['email'])
            if elma_user is not None:
                self.user = ({'id': res_find['id'], 'useruid': elma_user['id'], 'email': res_find['email'], 'chat_id': chat_id, 'groups': elma_user['groups']})

                # Формирование доступных юзеру кнопок для создания основной клавиатуры
                needle_buttons = self.get_buttons_by_user_groups(self.user['groups'])

                # Создание основного меню
                self.keyboard_main_menu = self.create_reply_keyboard(needle_buttons)

                return {'success': True, 'message': "Авторизация была успешно завершена"}

            return {'success': False, 'message': "Не удалось найти юзера в элме по емеилу из базы"}


    # Сбор необходимой информации о сообщении
    def parse_message(self):
        try:
            forward = False
            reply = False

            if self.telegram_update.reply_to_message is not None:
                reply = True
            elif self.telegram_update.forward_from is not None:
                forward = True

            button = self.get_reply_button_by_text(self.user_message_text)   #Если была нажата кнопка, button вернет информацию о ней, иначе None

            return {'button': button, 'reply': reply, 'forward': forward}
        except Exception as e:
            return self.on_exception("При парсе сообщения произошла ошибка", traceback.format_exc())


    # Найти кнопку по её тексту(работа с локальной базой формата json)
    def get_reply_button_by_text(self, text):
        for section in self.reply_buttons_data:
            for button_data in self.reply_buttons_data[section]:
                if button_data['text'] == text: return button_data
        return None


    # Действия при нажатии на reply кнопку
    def on_reply_button(self, button):
        if button['text'] == 'Создать запрос':
            self.on_create_request_click_button()
        elif button['text'] == 'Мои запросы':
            self.on_show_requests_click_button()
        elif button['text'] == 'Административное':
            # Проверка прав юзера
            if ('teamleads' in self.user['groups']):
                self.on_administrative_click()
                return
            self.show_menu(self.chat_id, "Недостаточно прав")


    # Действия при нажатии reply кнопки создать задачу
    def on_create_request_click_button(self):
        self.show_menu(self.chat_id, "Введите тему")


    # Действия при нажатии reply кнопки показать мои задачи
    def on_show_requests_click_button(self):
        user_elma_id = self.user['useruid']

        if user_elma_id == None:
            self.show_menu(self.chat_id, "Не удалось найти вашу учетную запись в elma")
            return

        requests_project = self.main_project
        requests_section = self.main_section

        # Получение задач юзера из конкретной секции
        user_requests = self.get_user_requests(user_elma_id, requests_project, requests_section)

        if user_requests == None:
            self.show_menu(self.chat_id, "При получении запросов произошла ошибка")
            return

        res_show_requests = self.show_requests(user_requests, requests_project, requests_section)
        if res_show_requests == None:
            self.show_menu(self.chat_id, "При отображении запросов произошла ошибка")
            return


    # Действия при нажатии reply кнопки Административное
    def on_administrative_click(self):
        # Подготовка ссылки для перехода к административному разделу
        administrative_section_link = f"https://elma365.{self.elma_home_domain}/hr/employees"   # Ссылка на административный раздел

        text = f"Продолжите [здесь]({administrative_section_link})"
        self.bot.send_message(self.chat_id, text, parse_mode='Markdown')


    # Подготовка сопровождающих ссылок на соответствующую секцию в элме
    def provide_to_elma(self, chat_id, id):
        text = "Создайте запрос "
        url = f"https://elma365.{self.elma_home_domain}/example_chapter/example_chapter"
        if id in [256, 257, 340]:
            url = f"https://elma365.{self.elma_home_domain}/example_chapter2/example_chapter2"
        elif id == 258:
            url = f"https://elma365.{self.elma_home_domain}/example_chapter3/example_chapter3"
        elif id == 260:
            url = f"https://elma365.{self.elma_home_domain}/example_chapter4/example_chapter4"
        elif id == 263:
            url = f"https://elma365.{self.elma_home_domain}/example_chapter5/example_chapter5"

        text += f"[здесь]({url})"
        self.bot.send_message(chat_id, text, parse_mode='Markdown')


    # Создание inline клавиатуры телеграмма
    def create_inline_keyboard(self, inline_buttons_data):
        inline_keyboard = InlineKeyboardMarkup()

        for element in inline_buttons_data:
            row_data = inline_buttons_data[element]
            data = {key: row_data[key] for key in row_data}

            inline_keyboard.add(InlineKeyboardButton(text=element, callback_data=json.dumps(data)))

        return inline_keyboard


    # Показать inline клавиатуру
    def show_inline_menu(self, chat_id, text):
        self.bot.send_message(chat_id, text, reply_markup=self.inline_keyboard)


    # Показать основную reply клавиатуру
    def show_menu(self, chat_id, text='Основное меню'):
        self.bot.send_message(chat_id, text, reply_markup=self.keyboard_main_menu)


    # Найти имя юзера элмы по айди из задачи
    def get_username_from_request_field(self, request_data):
        useruid = request_data[0]
        res_find_user = self.web_query(
            'POST',
            f"https://elma365.{self.elma_home_domain}/pub/v1/user/list",
            json.dumps({
                "ids": [f"{useruid}"],
                "size": 1,
                "from": 0
            })
        )

        if res_find_user is not None:
            if res_find_user['success']:
                return res_find_user['result']['result'][0]['__name']
            else:
                self.on_exception("Безуспешный возврат юзера элмы по id", res_find_user['error'])
        return useruid


    # Получение человеческого значения поля по типу поля
    def get_request_field_value_by_type(self, request_data, field_type):
        if request_data == None: return

        if field_type == 'string':
            return request_data
        elif field_type == 'user':
            # В теле задачи обычно айди юзера элмы, нужно нормальное имя
            return self.get_username_from_request_field(request_data)
        elif field_type == 'select':
            return request_data[0]['name']
        elif field_type == 'status':
            status = f"{request_data['status']}"
            if status in self.status_data:
                # Обращение к локальной информации о статусах в local_base/status_data
                return self.status_data[status]['view']


    # Создание ссылки на задачу
    def create_request_link(self, id, project, section):
        return f"https://elma365.{self.elma_home_domain}/{project['code_name']}/{section['code_name']}(p:item/{project['code_name']}/{section['code_name']}/{id}"


    # Показать информацию о задаче юзеру
    def show_request(self, request_data, project, section,needle_request_fields_titles=None):
        try:
            # Выгрузка информации о полях задач из локальной базы формата json по конкретной секции
            request_fields_data = self.elma_data['projects'][self.main_project['name']]['sections'][section['name']]['fields']

            # Создание ссылки на задачу
            request_link = self.create_request_link(request_data['item']['__id'], project, section)

            if needle_request_fields_titles == None:
                # Если нет параметра о том, какие поля нужно показать, то показывать все поля, которые есть в локальной базе
                needle_request_fields_titles = request_fields_data.keys()

            # Парс полей запроса
            parsed_request_fields = self.parse_request_fields(request_data, request_fields_data, needle_request_fields_titles)

            # Формирование текста
            text = self.form_request_description(parsed_request_fields, request_link)

            self.bot.send_message(self.chat_id, text, parse_mode='Markdown')

            return True
        except Exception as e:
            return self.on_exception("При парсе полей задачи произошла ошибка", traceback.format_exc())


    # Показ задач юзера в элме
    def show_requests(self, user_requests, project, section):
        try:
            if len(user_requests) < 1:
                self.bot.send_message(self.chat_id, "Пусто")
                return True

            inline_requests = InlineKeyboardMarkup()

            # Создание inline клавиатуры из задач юзера для возможности увидеть подробности задачи при нажатии
            for item in user_requests:

                button_body = {
                                'i': item['id'],
                                'p': project['id'],
                                's': section['id']
                              }

                inline_requests.add(InlineKeyboardButton(text=f"{item['name']}", callback_data=json.dumps(button_body)))

            self.bot.send_message(self.chat_id, "Ваши запросы:", reply_markup=inline_requests)
            return True
        except Exception as e:
            return self.on_exception("При показе моих запросов произошла ошибка", traceback.format_exc())


    # Формирование информации о задаче
    def form_request_description(self, field_and_values, link) -> str:
        request_description = ""
        for field in field_and_values:
            field_value = field_and_values[field]
            # Пустые поля не показывать
            if field_value is not None:
                string = f"{field}: {field_and_values[field]}\n"
                if field == 'Резюме':
                    # Прикрепление сопровождающей ссылки к названию задачи
                    string = f"{field}: [{field_and_values[field]}]({link})\n"
                request_description += string
        return request_description


    # Приведение полей задачи к человеческому виду
    def parse_request_fields(self, request_data, fields_data,needle_fields) -> dict:
        parsed_fields = {}

        for field in needle_fields:
            field_code_name = fields_data[field]['code_name']
            if field_code_name in request_data['item']:
                field_type = fields_data[field]['type']

                field_value = self.get_request_field_value_by_type(request_data['item'][field_code_name], field_type)

                field_name = fields_data[field]['view']

                parsed_fields.update({field_name: field_value})
        return parsed_fields


    # Модель веб-запроса
    def web_query(self, method, url, body):
        try:
            response = requests.request(f"{method}", url, headers=self.headers[f"{method}"], data=body)
            response_json = loads(response.text)
            return response_json
        except Exception as e:
            return self.on_exception(
                f"При отправке веб-запроса произошла ошибка:\nURL: {url}\nmethod: {method}\nbody: {body}\n\n", traceback.format_exc())


    # Обработка исключений
    def on_exception(self, ex_text, error, chat=None):
        print(f"{ex_text}:\n{error}")

        if chat == None: chat = self.admin_chat_id
        self.bot.send_message(chat, f"{ex_text}: \n{error}\n")

        time = datetime.datetime.now()
        self.logging.error(
            f"\n-------------{time}--------------\n{ex_text}:\n{error}")
        return None