import os  # Импортируем модуль для работы с переменными окружения
from flask import Flask, request, jsonify  # Flask используется для создания веб-сервера
from fuzzywuzzy import fuzz  # Модуль для вычисления схожести строк
from sqlalchemy import create_engine, Column, Integer, String, Text  # Основные инструменты SQLAlchemy для работы с БД
from sqlalchemy.ext.declarative import declarative_base  # Базовый класс для моделей
from sqlalchemy.orm import sessionmaker  # Менеджер сессий SQLAlchemy
from contextlib import contextmanager  # Контекстный менеджер для упрощения работы с ресурсами

# Инициализация Flask приложения
app = Flask(__name__)

# Получение URL базы данных из переменной окружения (или SQLite по умолчанию)
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///memory_skill.db')

# Создание движка для подключения к базе данных
engine = create_engine(DATABASE_URL)

# Создание базового класса для всех моделей
Base = declarative_base()

# Определение модели для хранения пользовательских сессий
class UserSession(Base):
    """
    Модель для хранения пользовательских сессий в базе данных.

    Атрибуты:
        id (int): Уникальный идентификатор записи.
        session_id (str): Идентификатор сессии пользователя (уникальный).
        original_text (str): Оригинальный текст, который пользователь хочет запомнить.
        state (str): Текущее состояние сессии. Возможные значения:
            - "awaiting_original" (ожидание ввода оригинального текста),
            - "awaiting_user_input" (ожидание ввода текста от пользователя для сравнения).
    """
    __tablename__ = 'user_sessions'  # Имя таблицы в базе данных
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор записи (автоинкремент)
    session_id = Column(String, unique=True, nullable=False)  # Уникальный идентификатор сессии пользователя
    original_text = Column(Text, nullable=True)  # Оригинальный текст, который вводит пользователь
    state = Column(String, default='awaiting_original')  # Состояние сессии (по умолчанию "ожидание текста")

# Создаём таблицы в базе данных (если они ещё не существуют)
Base.metadata.create_all(engine)

# Создание менеджера сессий для выполнения запросов к базе данных
Session = sessionmaker(bind=engine)

# Контекстный менеджер для автоматического управления сессиями базы данных
@contextmanager
def session_scope():
    """
    Контекстный менеджер для работы с сессиями базы данных.

    Обеспечивает безопасную работу с базой данных. При возникновении ошибок выполняет
    откат транзакции (rollback). После выполнения операций автоматически закрывает сессию.
    """
    session = Session()  # Создаём сессию для работы с БД
    try:
        yield session  # Передаём сессию для выполнения операций
        session.commit()  # Если всё прошло успешно, фиксируем изменения
    except Exception:  # Если произошла ошибка
        session.rollback()  # Откатываем транзакцию
        raise  # Пробрасываем ошибку дальше
    finally:
        session.close()  # Закрываем сессию в любом случае

# Функция для очистки текста
def clean_text(text):
    """
    Очистка текста от лишних символов и приведение к единому формату.

    Удаляет все символы, кроме букв, цифр и пробелов. Приводит текст к нижнему регистру.

    Args:
        text (str): Исходный текст для очистки.

    Returns:
        str: Очищенный текст.
    """
    # Удаляем все символы, кроме букв, цифр и пробелов, а также убираем лишние пробелы
    return " ".join(''.join(e for e in text.lower() if e.isalnum() or e.isspace()).split())

# Основной эндпоинт для обработки пользовательских запросов
@app.route('/handler', methods=['POST'])
def handler():
    """
   Основной эндпоинт для обработки пользовательских запросов.

    Логика:
    1. Если состояние сессии "awaiting_original", сохраняет оригинальный текст.
    2. Если состояние "awaiting_user_input", сравнивает введённый текст с оригинальным.
    3. Возвращает результаты сравнения в формате JSON.

    При ошибках возвращает соответствующие сообщения пользователю.

    JSON-параметры запроса:
        - user_message (str): Текст, введённый пользователем.
        - session_id (str): Идентификатор текущей сессии.

    Returns:
        Response: JSON-ответ с текстом, кнопками и флагом end_session.
    """
    # Получаем данные из запроса (JSON-формат)
    data = request.json
    user_message = data.get('user_message', '').strip()  # Сообщение от пользователя
    session_id = data.get('session_id')  # Идентификатор текущей сессии

    # Если пользовательское сообщение пустое
    if not user_message:
        return jsonify({
            "response": {
                "text": "Введите текст для продолжения.",
                "end_session": False  # Указываем, что сессия не завершается
            }
        })

    # Работа с базой данных через контекстный менеджер
    with session_scope() as db_session:
        # Пытаемся найти сессию по session_id
        session = db_session.query(UserSession).filter_by(session_id=session_id).first()

        # Если сессия не найдена, создаём новую
        if not session:
            session = UserSession(session_id=session_id)
            db_session.add(session)

        # Обработка состояния "ожидание ввода оригинального текста"
        if session.state == "awaiting_original":
            # Если оригинальный текст ещё не был введён
            if not session.original_text:
                session.original_text = user_message  # Сохраняем оригинальный текст в БД
                session.state = "awaiting_user_input"  # Меняем состояние на "ожидание пользовательского ввода"
                return jsonify({
                    "response": {
                        "text": "Оригинальный текст сохранён. Теперь расскажите его, как вы запомнили.",
                        "end_session": False
                    }
                })
            else:
                # Если текст уже сохранён, сообщаем об этом пользователю
                return jsonify({
                    "response": {
                        "text": "Вы уже ввели оригинальный текст. Теперь расскажите его, как вы запомнили.",
                        "end_session": False
                    }
                })

        # Обработка состояния "ожидание ввода текста от пользователя"
        elif session.state == "awaiting_user_input":
            # Если по какой-то причине оригинальный текст отсутствует
            if not session.original_text:
                return jsonify({
                    "response": {
                        "text": "Ошибка: Оригинальный текст не найден. Введите текст заново.",
                        "end_session": False
                    }
                })

            # Сравниваем очищенные версии текстов
            original_clean = clean_text(session.original_text)
            user_clean = clean_text(user_message)
            similarity = fuzz.ratio(original_clean, user_clean)  # Процент совпадения

            # Формируем ответ для пользователя
            response_text = (f"Процент совпадения: {similarity}%\n\n"
                             f"Оригинальный текст: {session.original_text}\n\n"
                             f"Ваш текст: {user_message}")
            return jsonify({
                "response": {
                    "text": response_text,
                    "end_session": False
                },
                "buttons": [{"title": "Сбросить", "action": {"type": "text", "label": "Сбросить"}}]
            })

        # Обработка неизвестного состояния
        else:
            return jsonify({
                "response": {
                    "text": "Произошла ошибка. Попробуйте снова.",
                    "end_session": False
                }
            })

# Эндпоинт для сброса данных текущей сессии
@app.route('/reset', methods=['POST'])
def reset():
    """
    Эндпоинт для сброса данных текущей сессии.

    Сбрасывает оригинальный текст и состояние сессии. Если сессия не найдена, возвращает
    сообщение об ошибке с предложением начать заново.

    JSON-параметры запроса:
        - session_id (str): Идентификатор текущей сессии.

    Returns:
        Response: JSON-ответ с текстом и флагом end_session.
    """
    data = request.json  # Получаем данные из запроса
    session_id = data.get('session_id')  # Идентификатор текущей сессии

    with session_scope() as db_session:
        # Пытаемся найти сессию в базе данных
        session = db_session.query(UserSession).filter_by(session_id=session_id).first()

        if session:
            # Если сессия найдена, сбрасываем данные
            session.original_text = None
            session.state = 'awaiting_original'  # Возвращаем состояние к начальному
            return jsonify({
                "response": {
                    "text": "Данные сброшены. Введите новый текст.",
                    "end_session": False
                }
            })
        else:
            # Если сессия не найдена, сообщаем об ошибке
            return jsonify({
                "response": {
                    "text": "Сессия не найдена. Введите новый текст.",
                    "end_session": False
                }
            })

# Точка входа в приложение
if __name__ == '__main__':
    """
    Запуск Flask-приложения.

    Сервер запускается на всех интерфейсах (0.0.0.0) и использует порт, указанный
    в переменной окружения PORT, или 5000 по умолчанию.
    """
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
