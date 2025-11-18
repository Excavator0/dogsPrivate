import json
import os

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ShippingOption, ShippingQuery, LabeledPrice, PreCheckoutQuery, CallbackQuery, \
    InputMediaPhoto
from aiogram import Router, F

# from database.db import Database
from messages import MESSAGES
from config import PAYMENTS_TOKEN, ADMIN_ID
from handlers.order_handlers import Order, get_base_item, zone_label, order_types
from services.pricing import calculate_order_price

router = Router()
# storage = Database()

shipping_types = {"superspeed": "Супер быстрая", "post": "Почта России", "pickup": "Самовывоз"}

SUPERSPEED_SHIPPING_OPTION = ShippingOption(
    id='superspeed',
    title='Супер быстрая!',
    prices=[
        LabeledPrice(
            label='Лично в руки!',
            amount=50000
        )
    ]
)

POST_SHIPPING_OPTION = ShippingOption(
    id='post',
    title='Почта России',
    prices=[
        LabeledPrice(
            label='Картонная коробка',
            amount=10000
        ),
        LabeledPrice(
            label='Срочное отправление!',
            amount=30000
        )
    ]
)

PICKUP_SHIPPING_OPTION = ShippingOption(
    id='pickup',
    title='Самовывоз',
    prices=[
        LabeledPrice(
            label='Самовывоз в Санкт-Петербурге',
            amount=15000
        )
    ]
)


@router.callback_query(F.data == "checkout")
async def buy_process(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item = data.get("order_type")
    if not item:
        await callback.answer("Не могу найти заказ, вернись назад и начни заново.", show_alert=True)
        return
    price_info = data.get("price")
    if not price_info:
        price_info = calculate_order_price(data)
        await state.update_data({"price": price_info})
    base_item = get_base_item(item)
    message_config = MESSAGES.get(base_item, next(iter(MESSAGES.values())))
    order_label = data.get("order_label") or next((label for label, code in order_types.items() if code == item),
                                                  "AIVADOG заказ")
    payload = json.dumps({"order_id": data.get("order_id"), "user_id": callback.from_user.id})
    await callback.message.delete()
    await callback.message.answer_invoice(
        title=f"{order_label}",
        description=message_config['item_description'],
        provider_token=PAYMENTS_TOKEN,
        currency='rub',
        need_email=True,
        need_phone_number=True,
        is_flexible=True,
        prices=[LabeledPrice(label="AIVADOG кастом", amount=price_info["total"] * 100)],
        start_parameter='aivadog',
        payload=payload)


@router.shipping_query(lambda q: True)
async def shipping_process(shipping_query: ShippingQuery):
    shipping_options = [SUPERSPEED_SHIPPING_OPTION]

    if shipping_query.shipping_address.country_code == 'RU':
        shipping_options.append(POST_SHIPPING_OPTION)

        if shipping_query.shipping_address.city == 'Санкт-Петербург':
            shipping_options.append(PICKUP_SHIPPING_OPTION)

    await shipping_query.bot.answer_shipping_query(
        shipping_query.id,
        ok=True,
        shipping_options=shipping_options

    )


@router.pre_checkout_query(lambda q: True)
async def checkout_process(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    order_id = data.get("order_id")
    if not order_id:
        await message.answer("Не удалось сопоставить заказ. Напиши нам, мы поможем 🙏")
        return
    price_info = data.get("price") or calculate_order_price(data)
    phone = message.successful_payment.order_info.phone_number
    email = message.successful_payment.order_info.email
    storage.log_status(order_id, "Оплачен", "Оплата через ЮKassa")
    reward_id = data.get("discount_reward_id")
    if reward_id:
        storage.mark_discount_used(reward_id, order_id)
    storage.update_order(
        order_id,
        payment_payload=message.successful_payment.provider_payment_charge_id,
        shipping_option=message.successful_payment.shipping_option_id,
        contact_phone=phone,
        contact_email=email,
    )
    await message.answer(
        MESSAGES[get_base_item(data["order_type"])]["successful_payment"].format(
            total_amount=message.successful_payment.total_amount // 100,
            currency=message.successful_payment.currency)
    )
    front_id = data.get("front_id")
    back_id = data.get("back_id")
    zone = zone_label(data.get("order_zone", "chest"))
    customization = data.get("customization", "photo")
    customization_text = {
        "ready": "Готовый дизайн AIVADOG",
        "photo": "Фото питомца",
        "stickers": "Фото + стикеры"
    }.get(customization, "Фото питомца")
    order_label = data.get("order_label") or next((label for label, code in order_types.items()
                                                  if code == data.get("order_type")), "Изделие")
    admin_summary = (
        f"Новый заказ #{data.get('order_number', order_id)}\n"
        f"Изделие: {order_label}\n"
        f"Размер: {data.get('order_size')}\n"
        f"Зона: {zone}\n"
        f"Кастомизация: {customization_text}\n"
        f"Имя питомца: {data.get('pet_name', '—')}\n"
        f"Стикеры: {', '.join(data.get('stickers', [])) or 'Без стикеров'}\n"
        f"Стоимость: {price_info['total']} ₽\n"
        f"Способ доставки: {shipping_types.get(message.successful_payment.shipping_option_id, 'Не выбран')}\n"
        f"Контакты: {message.successful_payment.order_info.phone_number} / "
        f"{message.successful_payment.order_info.email}"
    )
    await message.bot.send_message(chat_id=ADMIN_ID, text=admin_summary)
    media = []
    if front_id:
        media.append(InputMediaPhoto(media=front_id, caption="Фронт"))
    if back_id:
        media.append(InputMediaPhoto(media=back_id, caption="Спина"))
    if media:
        await message.bot.send_media_group(chat_id=ADMIN_ID, media=media)
    for suffix in ("_bg_deleted.png", ".png"):
        path = f"prints/{user_id}{suffix}"
        if os.path.exists(path):
            os.remove(path)
    await message.answer(
        "После оплаты мы начинаем подготовку макета и свяжемся с тобой для финального согласования. "
        "Теперь давай оставим контакты, чтобы команда быстро вышла на связь.\n\nКак тебя зовут?"
    )
    await state.set_state(Order.contact_name)
