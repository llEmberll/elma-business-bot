import traceback
import pymysql.cursors
from datetime import datetime


class Db_operator:
    def __init__(self, main_config, dbtables_config, logging):
        self.main_config = main_config
        self.dbtables_config = dbtables_config
        self.logging = logging


    # Установить содеинение с базой данных
    def set_connection(self):
        try:
            connection = pymysql.connect(host=self.main_config['DB']['host'],
                                         user=self.main_config['DB']['user'],
                                         password=self.main_config['DB']['password'],
                                         database=self.main_config['DB']['database'],
                                         cursorclass=pymysql.cursors.DictCursor)
            return connection
        except Exception as e:
            return self.on_exception("При подключении к базе произошла ошибка", traceback.format_exc())


    # Добавить одну запись в таблицу
    def add_record(self, table_name: str, fields_and_values: dict):   #Входные данные - словарь, где ключи словаря = имена полей, значения в словаре = значения полей

        # Преобразование данных в формат, понятный для базы данных
        fields_and_values = self.form_fields_and_values(fields_and_values)

        try:
            connection = self.set_connection()
            with connection:
                with connection.cursor() as cur:
                    # Отправка запроса в базу данных, указав имя таблицы и подготовленные поля и их значения
                    cur.execute(f"INSERT INTO {table_name}({fields_and_values['fields']}) VALUES ({fields_and_values['values']});")

                    # Сохранение результата запроса
                    connection.commit()
                    return True
        except Exception as e:
            return self.on_exception(f"Ошибка при добавлении в базу записей: \n{fields_and_values}", traceback.format_exc())


    # Удаление записей из базы по значению поля
    def delete_records(self, table_name: str, keyfield: str, value: str):
        connection = self.set_connection()
        try:
            with connection:
                with connection.cursor() as cur:
                    # Отпрвка запроса на удаление всех совпадений
                    cur.execute(f"DELETE from {table_name} WHERE {keyfield} = '{value}';")

                    # Сохранение результата запроса
                    connection.commit()
                    return True

        except Exception as e:
            return self.on_exception(f"Ошибка при удалении из базы {table_name} поля с именем {keyfield} и значением {value}",
                                     traceback.format_exc())


    # Очистить поля для создания запроса в элму, используя айди юзера
    def clear_user_fields_by_id(self, user_id):
        table_name = self.dbtables_config['Base_Requests']['table_name']
        return self.delete_records(table_name, 'user_id', user_id)


    # Получить поля для создания запроса в элму, используя айди юзера
    def get_user_request_data_by_id(self, user_id):
        table_name = self.dbtables_config['Base_Requests']['table_name']
        return self.find_record(table_name, 'user_id', user_id)


    # Добавить поля для создания запроса в элму, используя айди юзера
    def fill_user_request_fields(self, request_data: dict):
        # Предварительная очистка полей юзера, чтобы запись была уникальной
        res_clear = self.clear_user_fields_by_id(request_data['user_id'])

        return self.add_record(self.dbtables_config['Base_Requests']['table_name'], request_data)


    # Форматирование входных данных в понятный для базы данных вид
    def form_fields_and_values(self, fields_and_values: dict):
        fields = ""
        values = ""
        for element in fields_and_values:
            # Создание строки вида (field1, field2, field3) для указания полей, которые будут определены
            fields = fields + f"{element}, "

            # Создание строки вида (value_field1, value_field2, value_field3) для указания значения полей
            values = values + f"'{fields_and_values[element]}', "

        # Срез запятой и пробела в конце строк
        fields = fields[:-2]
        values = values[:-2]

        return {'fields': fields, 'values': values}


    # Найти несколько записей в базе данных по значению поля
    def find_records(self, table_name: str, field: str, value: str):
        connection = self.set_connection()
        try:
            with connection:
                with connection.cursor() as cur:
                    # Отправка запроса: Выбрать все записи с соответствующим значением поля
                    cur.execute(f"SELECT * FROM {table_name} WHERE {field} like '{value}';")

                    # Возврат всего результата выборки
                    fetch = cur.fetchall()
                    return fetch
        except Exception as e:
            return self.on_exception(f"При поиске в базе записей по полю {field}={value} произошла ошибка",
                                     traceback.format_exc())


    # Найти одну запись по значению поля
    def find_record(self, table_name: str, field: str, value: str):
        connection = self.set_connection()
        try:
            with connection:
                with connection.cursor() as cur:
                    # Отправка запроса: Выбрать все записи, где поля имеет такое значение
                    cur.execute(f"SELECT * FROM {table_name} WHERE {field} like '{value}';")

                    # Возврат одной записи с результата выборки
                    fetch = cur.fetchone()
                    return fetch                    #format = {'id': '123', 'email': 'email@email.com', ...}
        except Exception as e:
            return self.on_exception(f"При поиске в базе записи по полю {field}={value} произошла ошибка",
                                     traceback.format_exc())


    # Найти юзера по айди
    def find_user_by_id(self, user_id):
        table_name = self.dbtables_config['Users']['table_name']
        field_name = 'id'
        return self.find_record(table_name, field_name, value=user_id)


    # Найти юзера по чат айди телеграмма
    def find_user_by_chat_id(self, chat_id):
        table_name = self.dbtables_config['Users']['table_name']
        field_name = 'telegram_chat_id'
        return self.find_record(table_name, field_name, value=chat_id)


    # Найти юзера по емеилу
    def find_user_by_email(self, email):
        table_name = self.dbtables_config['Users']['table_name']
        field_name = 'email'
        return self.find_record(table_name, field_name, value=email)


    # Внести нового юзера в базу
    def add_user(self, chat_id, email):
        table_name = self.dbtables_config['Users']['table_name']
        user = {
                'telegram_chat_id': chat_id,
                'email': email
               }
        return self.add_record(table_name, user)


    # Обработка исключений
    def on_exception(self, ex_text: str, error):
        print(f"{ex_text}:\n{error}")
        time = datetime.now()
        self.logging.error(f"\n-------------{time}--------------\n{ex_text}:\n{error}")
        return None