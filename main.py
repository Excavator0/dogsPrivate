import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.utils.deep_linking import create_start_link

from handlers import order_handlers, shipping_handlers, admin_handlers
from config import token
# from aiogram.fsm.storage.redis import RedisStorage, Redis

# Инициализируем логгер
logger = logging.getLogger(__name__)


# Функция конфигурирования и запуска бота
async def main():
    # Конфигурируем логирование
    logging.basicConfig(
        level=logging.INFO,
        format='%(filename)s:%(lineno)d #%(levelname)-8s '
               '[%(asctime)s] - %(name)s - %(message)s')

    # Выводим в консоль информацию о начале запуска бота
    logger.info('Starting bot')

    # Загружаем конфиг в переменную config
    # Инициализируем бот и диспетчер
    bot = Bot(token=token,
              parse_mode='HTML')
    # redis = Redis(host='localhost')
    # storage = RedisStorage(redis=redis)
    dp = Dispatcher()

    # Регистриуем роутеры в диспетчере
    dp.include_router(order_handlers.router)
    dp.include_router(shipping_handlers.router)
    dp.include_router(admin_handlers.router)

    bot_commands = [
        BotCommand(command="/menu", description="Новый заказ")
    ]
    await bot.set_my_commands(bot_commands)
    await create_start_link(bot, "shirt")
    await create_start_link(bot, "cap")
    await create_start_link(bot, "cup")
    await create_start_link(bot, "flag")
    await create_start_link(bot, "bag")



    # Пропускаем накопившиеся апдейты и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


asyncio.run(main())