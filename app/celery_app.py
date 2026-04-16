from celery import Celery
import os
from . import es_client

# Берем настройки из переменных окружения (как в Docker)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery('messenger_tasks', broker=REDIS_URL, backend=REDIS_URL)

# Настройки для оптимизации
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)


@celery_app.task(bind=True, max_retries=3)
def process_media_task(self, file_url: str, file_type: str):
    """
    Фоновая задача для обработки медиа.
    В будущем здесь будет сжатие картинок и конвертация аудио.
    """
    try:
        print(f">>> Начало обработки файла: {file_url} (Тип: {file_type})")

        # Имитация тяжелой работы (сжатие/конвертация)
        import time
        time.sleep(2)

        print(f"<<< Файл {file_url} успешно обработан!")
        return {"status": "success", "url": file_url}

    except Exception as e:
        print(f"Ошибка обработки: {e}")
        raise self.retry(exc=e, countdown=5)

@celery_app.task
def index_message_task(msg_id: int, text: str, sender: str, chat_id: int, timestamp: str):
    if text: # Индексируем только текст
        es_client.index_message(msg_id, text, sender, chat_id, timestamp)