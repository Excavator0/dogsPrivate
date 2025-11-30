"""
Модуль для очистки старых файлов из папки prints.
Запускается как фоновая задача при старте бота.
"""
import asyncio
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Время жизни файлов в секундах (1 день = 86400 секунд)
FILE_TTL_SECONDS = 86400  # 24 часа

# Интервал проверки (каждые 6 часов)
CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60


def get_prints_dir() -> Path:
    """Возвращает путь к папке prints."""
    return Path(__file__).parent.parent / "prints"


def cleanup_old_prints(ttl_seconds: int = FILE_TTL_SECONDS) -> int:
    """
    Удаляет файлы из папки prints, которые старше ttl_seconds.
    Возвращает количество удалённых файлов.
    """
    prints_dir = get_prints_dir()
    if not prints_dir.exists():
        return 0
    
    deleted_count = 0
    current_time = time.time()
    
    for file_path in prints_dir.iterdir():
        if not file_path.is_file():
            continue
        
        # Пропускаем .gitkeep и другие служебные файлы
        if file_path.name.startswith("."):
            continue
        
        try:
            file_mtime = file_path.stat().st_mtime
            file_age = current_time - file_mtime
            
            if file_age > ttl_seconds:
                file_path.unlink()
                deleted_count += 1
                logger.info(f"Удалён старый файл: {file_path.name} (возраст: {file_age / 3600:.1f} ч)")
        except OSError as e:
            logger.warning(f"Не удалось удалить файл {file_path}: {e}")
    
    return deleted_count


async def cleanup_task():
    """
    Фоновая задача для периодической очистки старых файлов.
    """
    logger.info("Запущена задача очистки старых файлов из prints/")
    
    while True:
        try:
            deleted = cleanup_old_prints()
            if deleted > 0:
                logger.info(f"Очистка prints/: удалено {deleted} файлов")
        except Exception as e:
            logger.error(f"Ошибка при очистке prints/: {e}")
        
        # Ждём до следующей проверки
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


def start_cleanup_task():
    """
    Запускает фоновую задачу очистки.
    Вызывать при старте бота.
    """
    asyncio.create_task(cleanup_task())


