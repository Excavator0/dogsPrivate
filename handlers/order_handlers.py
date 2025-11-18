import json
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Union

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InputMediaPhoto, InlineKeyboardButton, Message
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards.order_keyboards
from config import ADMIN_ID
from database.db import Database
from image_processing import *
from keyboards.confirmation_keyboards import *
from keyboards.order_keyboards import *
from keyboards.print_processing_keyboards import *
from services.designs import find_design, get_design_preview, list_ready_designs
from services.pricing import DEFAULT_PRICING, build_price_message, calculate_order_price

router = Router()
storage = Database()

order_types = {
    "Футболка • чёрная": "shirt_black",
    "Футболка • серая": "shirt_grey",
    "Футболка • зелёная": "shirt_green",
    "Футболка • розовая": "shirt_pink",
    "Худи": "hoodie",
    "Свитшот": "sweatshirt",
    "Кофта на молнии": "zip",
    "Штаны": "pants",
}

sizes = ["XS", "S", "M", "L", "XL", "2XL", "One size"]
size_step = 50

zone_schemes = {
    "shirt": [
        ("Грудь", "chest"),
        ("Спина", "back"),
        ("Левый рукав", "sleeve_left"),
        ("Правый рукав", "sleeve_right"),
    ],
    "hoodie": [
        ("Грудь", "chest"),
        ("Спина", "back"),
        ("Левый рукав", "sleeve_left"),
        ("Правый рукав", "sleeve_right"),
        ("Капюшон", "hood"),
    ],
    "sweatshirt": [
        ("Грудь", "chest"),
        ("Спина", "back"),
        ("Левый рукав", "sleeve_left"),
        ("Правый рукав", "sleeve_right"),
    ],
    "zip": [
        ("Грудь", "chest"),
        ("Спина", "back"),
        ("Левый рукав", "sleeve_left"),
        ("Правый рукав", "sleeve_right"),
        ("Капюшон", "hood"),
    ],
    "pants": [
        ("Левая штанина", "pant_left"),
        ("Правая штанина", "pant_right"),
    ],
}

sticker_catalog = [
    ("🌸 Цветочек", "flower"),
    ("🦴 Косточка", "bone"),
    ("💛 Сердце", "heart"),
    ("⭐ Звезда", "star"),
    ("⚽ Мяч", "ball"),
]

READY_DESIGNS = list_ready_designs()
DESIGN_INDEX = {design.id: idx for idx, design in enumerate(READY_DESIGNS)}
DELIVERY_RESPONSES = {
    "delivery_pickup": "Самовывоз доступен по адресу: Обводного канала, 223-225. Напиши удобный день и время — подготовим заказ.",
    "delivery_courier": "Пришли, пожалуйста, адрес в Санкт-Петербурге и контактный номер — организуем курьера.",
    "delivery_cdek": "Отправим СДЭКом. Напиши ФИО получателя, адрес и индекс, чтобы мы подготовили отправку.",
}


def designs_available() -> bool:
    return bool(READY_DESIGNS)


def _design_caption(design) -> str:
    return f"«{design.title}» — фирменный макет AIVADOG. Добавим твоего питомца и покажем предпросмотр!"


def _design_keyboard(mode: str, index: int, design_id: str) -> InlineKeyboardBuilder:
    total = len(READY_DESIGNS)
    builder = InlineKeyboardBuilder()
    if total > 1:
        prev_index = (index - 1) % total
        next_index = (index + 1) % total
        builder.add(InlineKeyboardButton(text="⬅️", callback_data=f"{mode}_show_{prev_index}"))
        builder.add(InlineKeyboardButton(text="➡️", callback_data=f"{mode}_show_{next_index}"))
        builder.adjust(2)
    action_text = "Хочу такой!" if mode == "example" else "Выбрать этот дизайн"
    action_callback = f"{mode}_pick_{design_id}"
    builder.row(InlineKeyboardButton(text=action_text, callback_data=action_callback))
    back_callback = "back_to_main" if mode == "example" else "design_cancel"
    back_text = "🔙 Назад к выбору" if mode == "example" else "Назад"
    builder.row(InlineKeyboardButton(text=back_text, callback_data=back_callback))
    return builder


async def send_design_card(message: Message, index: int, mode: str, edit: bool = False):
    if not READY_DESIGNS:
        await message.answer("Каталог дизайнов появится совсем скоро 💛")
        return
    index = index % len(READY_DESIGNS)
    design = READY_DESIGNS[index]
    file = get_design_preview(design)
    keyboard = _design_keyboard(mode, index, design.id).as_markup()
    caption = _design_caption(design)
    if edit:
        media = InputMediaPhoto(media=file, caption=caption)
        await message.edit_media(media, reply_markup=keyboard)
    else:
        await message.answer_photo(photo=file, caption=caption, reply_markup=keyboard)


async def _reply(target: Union[Message, CallbackQuery], text: str, **kwargs):
    if isinstance(target, CallbackQuery):
        return await target.message.answer(text, **kwargs)
    return await target.answer(text, **kwargs)


async def _prompt_ready_design_selection(target: Union[Message, CallbackQuery], state: FSMContext, start_index: int = 0):
    if not designs_available():
        await _reply(target, "Каталог готовых макетов временно недоступен. Отправь фото питомца, и дизайнер подготовит принт.")
        await state.set_state(Order.image_sent)
        return
    await send_design_card(target.message if isinstance(target, CallbackQuery) else target, start_index, "design")
    await state.set_state(Order.ready_design)


async def _handle_preselected_ready(target: Union[Message, CallbackQuery], state: FSMContext):
    data = await state.get_data()
    design_title = data.get("selected_design_title")
    design_id = data.get("selected_design_id")
    if not design_id or not design_title:
        await _prompt_ready_design_selection(target, state)
        return
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Сменить макет", callback_data="design_change"))
    await _reply(
        target,
        f"Ты выбрал макет «{design_title}». Теперь загрузи фото питомца документом (PNG/JPG до 2 МБ). "
        "Ракурс должен быть похож на пример.",
        reply_markup=builder.as_markup(),
    )
    await state.update_data({"preferred_customization": None, "customization": "ready"})
    await state.set_state(Order.image_sent)

@router.callback_query(F.data.startswith("zone_"))
async def choose_customization(callback: CallbackQuery, state: FSMContext):
    zone = callback.data.replace("zone_", "")
    await state.update_data({"order_zone": zone})
    data = await state.get_data()
    if data.get("preferred_customization") == "ready":
        await _handle_preselected_ready(callback, state)
        return
    zone_title = zone_label(zone)
    await callback.message.edit_text(
        text=f"Выбери вариант кастомизации для зоны «{zone_title}»:"
    )
    await callback.message.edit_reply_markup(
        reply_markup=make_customization_keyboard().as_markup()
    )
    await state.set_state(Order.customization)


@router.callback_query(F.data == "back_to_items")
async def back_to_items(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('Выбери изделие, на которое хочешь нанести принт')
    await callback.message.edit_reply_markup(make_type_keyboard(order_types).as_markup())
    await state.set_state(Order.order_type)


@router.callback_query(F.data.in_({"custom_ready", "custom_photo", "custom_stickers"}))
async def customization_selected(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.replace("custom_", "")
    await state.update_data({"customization": choice, "stickers_planned": choice == "stickers"})
    await callback.answer()
    if choice == "ready":
        data = await state.get_data()
        start_index = DESIGN_INDEX.get(data.get("selected_design_id"), 0)
        await _prompt_ready_design_selection(callback, state, start_index)
        await callback.message.delete()
        return
    await callback.message.delete()
    await callback.message.answer(
        "Отправь фото своего питомца документом (PNG/JPG до 2 МБ), чтобы я подготовил макет."
    )
    await state.set_state(Order.image_sent)


@router.callback_query(F.data == "back_to_zones")
async def back_to_zones(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    zones = zone_schemes.get(get_base_item(data.get("order_type")), zone_schemes["shirt"])
    await callback.message.edit_text("Выбери зону нанесения принта 👇")
    await callback.message.edit_reply_markup(make_zone_keyboard(zones).as_markup())
    await state.set_state(Order.zone)

def get_base_item(item_code: str) -> str:
    return item_code.split("_", 1)[0]


@lru_cache(maxsize=32)
def get_template_bounds(item_code: str) -> tuple[int, int]:
    template_path = _resolve_template_path(item_code, 0)
    with Image.open(template_path) as template:
        return template.size


def zone_label(zone_code: str) -> str:
    mapping = {
        "chest": "Грудь",
        "back": "Спина",
        "sleeve_left": "Левый рукав",
        "sleeve_right": "Правый рукав",
        "hood": "Капюшон",
        "pant_left": "Левая штанина",
        "pant_right": "Правая штанина",
        "photo": "К фото",
    }
    return mapping.get(zone_code, zone_code)


class Order(StatesGroup):
    order_type = State()
    order_size = State()
    zone = State()
    customization = State()
    ready_design = State()
    image_sent = State()
    pet_name = State()
    sticker_zone = State()
    sticker_choice = State()
    price = State()
    bg_deleted = State()
    pos = State()
    side = State()
    angle = State()
    size = State()
    album_id = State()
    chat_id = State()
    front_id = State()
    back_id = State()
    contact_name = State()
    contact_phone = State()
    contact_email = State()


class UGCSubmission(StatesGroup):
    waiting_photo = State()
    waiting_order_number = State()


@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    storage.upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    user_row = storage.get_user_by_tg(message.from_user.id)
    if user_row:
        storage.set_subscription(user_row["id"], True)
    chat_id = message.chat.id
    await message.answer(
        text=("Привет! Я — AIVADOG-бот 🐾\n\n"
              "Здесь твой питомец становится частью твоего стиля 💛\n\n"
              "Со мной ты можешь:\n"
              "• выбрать изделие\n"
              "• загрузить фото хвостика 🐶\n"
              "• добавить фирменные принты и стикеры\n"
              "• увидеть предпросмотр и оплатить заказ\n\n"
              "С чего начнём?👇"),
        reply_markup=make_main_menu_keyboard().as_markup()
    )
    await state.update_data({
        "chat_id": chat_id,
        "pos": [[-1, -1], [-1, -1]],
        "side": 0,
        "stickers": [],
        "preferred_customization": None,
        "selected_design_id": None,
        "selected_design_title": None,
    })


@router.message(CommandStart(deep_link=False))
async def start_default(message: Message, state: FSMContext):
    await cmd_start(message, state)


@router.message(CommandStart(deep_link=True))
async def start_with_link(message: Message, command: CommandObject, state: FSMContext):
    storage.upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    user_row = storage.get_user_by_tg(message.from_user.id)
    if user_row:
        storage.set_subscription(user_row["id"], True)
    args = command.args or ""
    if args.startswith("ref-"):
        user = storage.get_user_by_tg(message.from_user.id)
        if user:
            activated = storage.register_referral_hit(args, user["id"])
            if activated:
                await message.answer("Ура! По ссылке друга зашёл новый пользователь — скидка готовится 💛")
        await cmd_start(message, state)
        return
    if args not in order_types.values():
        await cmd_start(message, state)
        return
    order_label = next((label for label, code in order_types.items() if code == args), "Изделие")
    await state.update_data({"order_type": args, "order_label": order_label, "pos": [[-1, -1], [-1, -1]], "side": 0, "stickers": []})
    await message.answer(text=f"Товар: {order_label}\nТеперь выбери размер изделия", reply_markup=make_sizes_keyboard(sizes[:-1]).as_markup())
    await state.set_state(Order.order_size)


@router.callback_query(F.data == "choose_item")
async def menu_choose_item(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        text='Выбери изделие, на которое хочешь нанести принт'
    )
    await callback.message.edit_reply_markup(
        reply_markup=make_type_keyboard(order_types).as_markup()
    )
    await state.set_state(Order.order_type)


@router.callback_query(F.data == "brand_info")
async def show_brand_info(callback: CallbackQuery):
    text = (
        "AIVADOG – бренд, созданный из любви к питомцам.\n\n"
        "Мы создаём одежду и аксессуары с уникальными принтами питомцев, чтобы ваш любимец всегда был рядом с вами, "
        "ведь каждый день с питомцем – это радость, уют и маленькие моменты, которые делают жизнь ярче.\n"
        "Мы верим, что любовь к нашим хвостикам можно носить с собой – на худи, футболке, на брелке или шоппере.\n"
        "C любовью к деталям, этике и качеству – каждый дизайн проходит ручную доработку, печать делается с вниманием к материалам и цветам.\n"
        "Наше стремление – не просто одежда, а выражение привязанности и радости каждый день/AivaDog – это не просто одежда. "
        "Это способ показать, как сильно вы связаны со своим любимцем. ❤️"
    )
    await callback.message.edit_text(text=text)
    await callback.message.edit_reply_markup(reply_markup=make_back_to_main_keyboard().as_markup())


@router.callback_query(F.data == "show_examples")
async def show_examples(callback: CallbackQuery):
    if not designs_available():
        await callback.message.edit_text(
            text="Галерея готовых дизайнов скоро появится, а пока можно сразу выбрать изделие 👇"
        )
        await callback.message.edit_reply_markup(reply_markup=make_back_to_main_keyboard().as_markup())
        return
    await callback.message.edit_text(
        text="Вот несколько наших принтов-шаблонов. Листай стрелками и жми «Хочу такой!» 👇"
    )
    await callback.message.edit_reply_markup(reply_markup=make_back_to_main_keyboard().as_markup())
    await send_design_card(callback.message, 0, "example")


@router.callback_query(F.data.startswith("example_show_"))
async def example_switch(callback: CallbackQuery):
    if not designs_available():
        await callback.answer()
        return
    index = int(callback.data.replace("example_show_", ""))
    await send_design_card(callback.message, index, "example", edit=True)


@router.callback_query(F.data.startswith("example_pick_"))
async def example_pick(callback: CallbackQuery, state: FSMContext):
    design_id = callback.data.replace("example_pick_", "")
    design = find_design(design_id)
    if not design:
        await callback.answer("Не удалось загрузить макет", show_alert=True)
        return
    await state.update_data({
        "selected_design_id": design.id,
        "selected_design_title": design.title,
        "preferred_customization": "ready",
    })
    await callback.message.delete()
    await callback.message.answer(
        f"Дизайн «{design.title}» сохранён! Теперь выбери изделие 👇",
        reply_markup=make_type_keyboard(order_types).as_markup()
    )
    await state.set_state(Order.order_type)


@router.callback_query(Order.ready_design, F.data.startswith("design_show_"))
async def design_switch(callback: CallbackQuery, state: FSMContext):
    if not designs_available():
        await callback.answer()
        return
    index = int(callback.data.replace("design_show_", ""))
    await send_design_card(callback.message, index, "design", edit=True)
    await callback.answer()
    await state.set_state(Order.ready_design)


@router.callback_query(F.data == "design_change")
async def design_change(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    index = DESIGN_INDEX.get(data.get("selected_design_id"), 0)
    await state.update_data({"selected_design_id": None, "selected_design_title": None})
    await _prompt_ready_design_selection(callback, state, index)


@router.callback_query(Order.ready_design, F.data == "design_cancel")
async def design_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer(
        "Выбери вариант кастомизации:",
        reply_markup=make_customization_keyboard().as_markup()
    )
    await state.set_state(Order.customization)


@router.callback_query(Order.ready_design, F.data.startswith("design_pick_"))
async def design_pick(callback: CallbackQuery, state: FSMContext):
    design_id = callback.data.replace("design_pick_", "")
    design = find_design(design_id)
    if not design:
        await callback.answer("Не удалось выбрать макет", show_alert=True)
        return
    await state.update_data({
        "selected_design_id": design.id,
        "selected_design_title": design.title,
        "preferred_customization": None,
        "customization": "ready",
    })
    await callback.message.delete()
    await callback.message.answer(
        f"Отлично! Теперь загрузи фото своего питомца документом (PNG/JPG до 2 МБ), чтобы мы вставили его в макет «{design.title}».",
    )
    await state.set_state(Order.image_sent)


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        text=("Привет! Я — AIVADOG-бот! 🐾\n\n"
              "Добро пожаловать в AIVADOG — место, где твой питомец становится частью твоего стиля 💛\n\n"
              "Здесь ты можешь:\n\n"
              "• выбрать изделие (футболку, худи, свитшот, штаны, брелок или шоппер),\n\n"
              "• загрузить фото своей собачки 🐶,\n\n"
              "• добавить фирменные принты и стикеры,\n\n"
              "• увидеть готовый предпросмотр перед заказом!\n\n"
              "С чего начнём?👇")
    )
    await callback.message.edit_reply_markup(reply_markup=make_main_menu_keyboard().as_markup())


@router.callback_query(F.data.in_(set(order_types.values())))
async def order_size(callback: CallbackQuery, state: FSMContext):
    item = callback.data
    order_label = next((label for label, code in order_types.items() if code == item), "Изделие")
    await state.update_data({
        "order_type": item,
        "order_label": order_label,
        "pos": [[-1, -1], [-1, -1]],
        "side": 0,
        "stickers": [],
        "stickers_planned": False,
        "color": None,
    })
    await callback.message.edit_text(text="Выбери размер изделия")
    await callback.message.edit_reply_markup(
        reply_markup=make_sizes_keyboard(sizes[:-1]).as_markup()
    )
    await state.set_state(Order.order_size)


@router.callback_query(F.data.startswith("size_"))
async def order_zone(callback: CallbackQuery, state: FSMContext):
    size = callback.data.replace("size_", "").upper()
    await state.update_data({"order_size": size})
    data = await state.get_data()
    item = data["order_type"]
    template_width, template_height = get_template_bounds(item)
    zones = zone_schemes.get(get_base_item(item), zone_schemes["shirt"])
    await callback.message.edit_text(
        text=f"Выбери зону нанесения принта для выбранного изделия 👕"
    )
    await callback.message.edit_reply_markup(
        reply_markup=make_zone_keyboard(zones).as_markup()
    )
    await state.set_state(Order.zone)


@router.message(Order.image_sent, F.document)
async def getting_image(message: Message, state: FSMContext):
    document_type = message.document.file_name.lower()
    user_id = message.from_user.id
    if message.document.file_size > 2000000:
        await message.answer("Файл слишком велик! Отправьте документ размером менее 2 МБ")
    else:
        if (document_type.endswith("png")) or (document_type.endswith("jpg")) or (document_type.endswith("jpeg")):
            document = await message.bot.download(message.document.file_id)
            data = await state.get_data()
            item = data["order_type"]
            color = data.get("color")
            with Image.open(document) as image:
                image.save(f"prints/{user_id}.png", "PNG")
                template_width, template_height = get_template_bounds(item)
                centre_pos = [(template_width - image.size[0]) // 2,
                              (template_height - image.size[1]) // 2]
                await state.update_data(
                    {"pos": [centre_pos, [-1, -1]], "size": [image.size, image.size], "angle": [0, 0],
                     "bg_deleted": [False, False]})
                template = paste(image, color, centre_pos, item, 0, 0)
                file = image_to_bytes(template)

            await message.answer_photo(file, reply_markup=confirm_or_setting_keyboard().as_markup())
            await message.answer("Фото принято ✅\nКак зовут твоего хвостика?", disable_notification=True)
            await state.set_state(Order.pet_name)
        else:
            await message.answer(
                text="Формат документа не поддерживается!"
            )


@router.message(Order.image_sent, F.photo)
async def photo_sent(message: Message):
    await message.answer("Отправьте фото документом, так не потеряется качество изображения")


async def _start_sticker_flow(target, state: FSMContext):
    data = await state.get_data()
    item = data.get("order_type")
    zones = [("К фото", "photo")] + zone_schemes.get(get_base_item(item), zone_schemes["shirt"])
    text = "Выбери зону нанесения стикера:"
    if isinstance(target, Message):
        await target.answer(text, reply_markup=make_sticker_zone_keyboard(zones).as_markup())
    else:
        await target.message.edit_text(text)
        await target.message.edit_reply_markup(make_sticker_zone_keyboard(zones).as_markup())
    await state.set_state(Order.sticker_zone)


@router.message(Order.pet_name)
async def pet_name_received(message: Message, state: FSMContext):
    pet_name = message.text.strip()
    await state.update_data({"pet_name": pet_name})
    data = await state.get_data()
    if data.get("stickers_planned"):
        await _start_sticker_flow(message, state)
    else:
        await message.answer(
            "Хочешь добавить фирменные стикеры AIVADOG к фото? 🎨",
            reply_markup=make_yes_no_keyboard("stickers_yes", "stickers_no").as_markup()
        )
        await state.set_state(Order.customization)


@router.callback_query(F.data == "stickers_yes")
async def stickers_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"stickers_planned": True})
    await _start_sticker_flow(callback, state)


@router.callback_query(F.data == "stickers_no")
async def stickers_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"stickers_planned": False})
    await callback.message.answer("Отлично! Проверь макет и нажми «Продолжить», когда всё понравится ✅")
    await state.set_state(Order.customization)


@router.callback_query(Order.sticker_zone, F.data.startswith("sticker_zone_"))
async def sticker_zone_selected(callback: CallbackQuery, state: FSMContext):
    zone = callback.data.replace("sticker_zone_", "")
    await state.update_data({"sticker_zone": zone, "stickers": []})
    await callback.message.edit_text("Выбери стикеры, которые хочешь добавить 🐾")
    await callback.message.edit_reply_markup(make_sticker_keyboard(sticker_catalog).as_markup())
    await state.set_state(Order.sticker_choice)


@router.callback_query(Order.sticker_choice, F.data.startswith("sticker_"))
async def sticker_added(callback: CallbackQuery, state: FSMContext):
    sticker_code = callback.data.replace("sticker_", "")
    data = await state.get_data()
    stickers = data.get("stickers", [])
    if sticker_code not in stickers:
        stickers.append(sticker_code)
        await state.update_data({"stickers": stickers})
        await callback.answer("Добавили стикер", show_alert=False)
    else:
        await callback.answer("Этот стикер уже выбран", show_alert=True)


@router.callback_query(F.data == "stickers_done")
async def stickers_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stickers = data.get("stickers", [])
    if not stickers:
        await callback.answer("Выбери хотя бы один стикер", show_alert=True)
        return
    await callback.message.answer("Супер! Проверь макет и нажми «Продолжить», когда всё понравится ✅")
    await state.set_state(Order.customization)


@router.callback_query(F.data == "stickers_back")
async def stickers_back(callback: CallbackQuery, state: FSMContext):
    await _start_sticker_flow(callback, state)


@router.callback_query(F.data == "stickers_cancel")
async def stickers_cancel(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"stickers": [], "stickers_planned": False})
    await callback.message.answer("Вернулись к макету. Нажми «Продолжить», когда будешь готов.")
    await state.set_state(Order.customization)


@router.callback_query(F.data == "settings_back")
async def confirm_or_settings(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=confirm_or_setting_keyboard().as_markup())


@router.callback_query(F.data == "settings")
async def print_settings(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data == "delete_bg")
async def remove_print_bg(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    image = Image.open(f"prints/{user_id}.png")
    item = data["order_type"]
    template_width, template_height = get_template_bounds(item)
    color = data.get("color")
    side = data["side"]
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    bg_deleted = data["bg_deleted"]
    if bg_deleted[side]:
        await callback.answer("Фон уже удален!")
    else:
        bg_deleted[side] = True
        await state.update_data({"bg_deleted": bg_deleted})
        image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
        image = print_remove_bg(image)
        image.save(f"prints/{user_id}_bg_deleted.png", "PNG")
        template = paste(image, color, print_pos[side], item, side, angle[side], True)
        file = image_to_bytes(template)
        file = InputMediaPhoto(media=file)
        await callback.message.edit_media(file, reply_markup=make_remove_bg_keyboard().as_markup())


@router.callback_query(F.data == "restore_bg")
async def restore_print_bg(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    image = Image.open(f"prints/{user_id}.png")
    item = data["order_type"]
    color = data.get("color")
    side = data["side"]
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    bg_deleted = data["bg_deleted"]
    bg_deleted[side] = False
    await state.update_data({"bg_deleted": bg_deleted})
    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template = paste(image, color, print_pos[side], item, side, angle[side], False)
    file = image_to_bytes(template)
    file = InputMediaPhoto(media=file)
    await callback.message.edit_media(file, reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data == "change_size")
async def print_size_main(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=make_print_size_keyboard().as_markup())


@router.callback_query(F.data.in_({"decrease_size", "increase_size"}))
async def print_size(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    if bg_deleted[side]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    item = data["order_type"]
    template_width, template_height = get_template_bounds(item)
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    x_size = size[side][0]
    y_size = size[side][1]
    new_size = 0
    size_changed = False
    if callback.data == "decrease_size":
        decrease_k = 5 / 6
        if (x_size * decrease_k > size_step) and (y_size * decrease_k > size_step):
            new_size = (int(x_size * decrease_k), int(y_size * decrease_k))
            size_changed = True
        else:
            await callback.answer("Достигнут минимум разрешения изображения")
    else:
        increase_k = 1.2
        if (x_size * increase_k < template_width) and (y_size * increase_k < template_height):
            new_size = (int(x_size * increase_k), int(y_size * increase_k))
            size_changed = True
        else:
            await callback.answer("Достигнут максимум разрешения изображения")
    if size_changed:
        size[side] = new_size
        image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
        template = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
        file = image_to_bytes(template)
        await state.update_data({"size": size})
        file = InputMediaPhoto(media=file)
        await callback.message.edit_media(file, reply_markup=make_print_size_keyboard().as_markup())


@router.callback_query(F.data == "move_print")
async def move_print_main(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=make_move_print_keyboard().as_markup())


@router.callback_query(F.data.in_({"move_up", "move_down", "move_right", "move_left", "move_centre"}))
async def move_print(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    if bg_deleted[side]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    item = data["order_type"]
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    pos_changed = False
    if callback.data == "move_right":
        if (print_pos[side][0] + size_step) < template_width:
            print_pos[side][0] = print_pos[side][0] + size_step
            pos_changed = True
        else:
            await callback.answer("Достигнут максимум сдвига вправо")
    elif callback.data == "move_left":
        if (print_pos[side][0] - size_step) > 0:
            print_pos[side][0] = print_pos[side][0] - size_step
            pos_changed = True
        else:
            await callback.answer("Достигнут максимум сдвига влево")
    elif callback.data == "move_up":
        if (print_pos[side][1] - size_step) > 0:
            print_pos[side][1] = print_pos[side][1] - size_step
            pos_changed = True
        else:
            await callback.answer("Достигнут максимум сдвига вверх")
    elif callback.data == "move_down":
        if (print_pos[side][1] + size_step) < template_height:
            print_pos[side][1] = print_pos[side][1] + size_step
            pos_changed = True
        else:
            await callback.answer("Достигнут максимум сдвига вниз")
    elif callback.data == "move_centre":
        rotations = angle[side] % 180
        if rotations == 0:
            print_pos[side] = [(template_width - size[side][0]) // 2,
                               (template_height - size[side][1]) // 2]
        else:
            print_pos[side] = [(template_width - size[side][1]) // 2,
                               (template_height - size[side][0]) // 2]
        pos_changed = True
    if pos_changed:
        image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
        template = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
        file = image_to_bytes(template)
        await state.update_data({"pos": print_pos})
        file = InputMediaPhoto(media=file)
        try:
            await callback.message.edit_media(file, reply_markup=make_move_print_keyboard().as_markup())
        except TelegramBadRequest:
            await callback.answer("Изображение находится в центре")


@router.callback_query(F.data == "rotate_print")
async def rotate_print_main(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=make_rotate_keyboard().as_markup())


@router.callback_query(F.data.in_({"rotate_right", "rotate_left"}))
async def rotate_print(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    if bg_deleted[side]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    item = data["order_type"]
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    if callback.data == "rotate_right":
        angle[side] = angle[side] + 270
    else:
        angle[side] = angle[side] + 90
    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
    file = image_to_bytes(template)
    await state.update_data({"angle": angle})
    file = InputMediaPhoto(media=file)
    await callback.message.edit_media(file, reply_markup=make_rotate_keyboard().as_markup())


@router.callback_query(F.data == "change_side")
async def change_side(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]

    item = data["order_type"]
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    if side == 0:
        side = 1
    else:
        side = 0
    if bg_deleted[side]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    if print_pos[side][0] == -1:
        print_pos[side] = [(template_width - image.size[0]) // 2,
                           (template_height - image.size[1]) // 2]
        size[side] = list(image.size)
        angle[side] = 0
    elif print_pos[side] != "deleted":
        image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
    file = image_to_bytes(template)
    file = InputMediaPhoto(media=file)
    await state.update_data({"pos": print_pos, "side": side, "bg_deleted": bg_deleted, "angle": angle, "size": size})
    await callback.message.edit_media(file, reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data == "delete_print")
async def delete_print(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item = data["order_type"]
    color = data.get("color")
    side = data["side"]
    print_pos = data["pos"]
    bg_deleted = data["bg_deleted"]
    angle = data["angle"]
    if print_pos[side] == "deleted":
        await callback.answer("Нечего удалять!")
    else:
        print_pos[side] = "deleted"
        template = paste(None, color, print_pos[side], item, side, angle[side], bg_deleted[side])
        file = image_to_bytes(template)
        file = InputMediaPhoto(media=file)
        await state.update_data({"pos": print_pos})
        await callback.message.edit_media(file, reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data.startswith("confirm"))
async def confirm_print(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    item = data["order_type"]
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    size_order = data["order_size"]
    if len(callback.data) > 7:
        change = callback.data[callback.data.index("_") + 1:callback.data.rfind("_")]
        value = callback.data[callback.data.rfind("_") + 1:]
        if change == "size":
            size_order = value
            await state.update_data({"order_size": size_order})
        elif change == "type":
            item = value
            await state.update_data({"order_type": item})
    base_image = Image.open(f"prints/{user_id}_bg_deleted.png") if bg_deleted[0] else Image.open(
        f"prints/{user_id}.png")
    image1 = base_image.resize(tuple(size[0]), Image.Resampling.BICUBIC)
    front = paste(image1, color, print_pos[0], item, 0, angle[0], bg_deleted[0])
    file1 = InputMediaPhoto(media=image_to_bytes(front))

    if isinstance(print_pos[1], list) and print_pos[1][0] == -1:
        print_pos[1] = "deleted"

    base_back_image = Image.open(f"prints/{user_id}_bg_deleted.png") if bg_deleted[1] else Image.open(
        f"prints/{user_id}.png")
    image2 = base_back_image.resize(tuple(size[1]), Image.Resampling.BICUBIC)
    back = paste(image2, color, print_pos[1], item, 1, angle[1], bg_deleted[1])
    file2 = InputMediaPhoto(media=image_to_bytes(back))

    await callback.message.delete()
    try:
        album_id = data["album_id"]
        chat_id = data["chat_id"]
        if album_id != -1:
            await callback.bot.delete_message(chat_id=chat_id, message_id=album_id)
            await callback.bot.delete_message(chat_id=chat_id, message_id=(album_id + 1))
    except KeyError:
        pass
    media_group = await callback.message.answer_media_group([file1, file2])
    front_id = media_group[0].photo[-1].file_id
    back_id = media_group[1].photo[-1].file_id
    await state.update_data({"album_id": media_group[0].message_id, "front_id": front_id, "back_id": back_id})
    order_label = next((label for label, code in order_types.items() if code == item), "Изделие")
    zone = zone_label(data.get("order_zone", "chest"))
    stickers_codes = data.get("stickers", [])
    titles_map = {code: text for text, code in sticker_catalog}
    stickers_text = ", ".join(titles_map.get(code, code) for code in stickers_codes) if stickers_codes else "Без стикеров"
    customization_code = data.get("customization", "photo")
    customization_text = {
        "ready": "Готовый дизайн AIVADOG",
        "photo": "Фото питомца",
        "stickers": "Фото + стикеры",
    }.get(customization_code, "Фото питомца")
    pet_name = data.get("pet_name", "—")
    notes = {}
    if data.get("selected_design_id"):
        notes["ready_design_id"] = data["selected_design_id"]
    if data.get("selected_design_title"):
        notes["ready_design_title"] = data["selected_design_title"]

    user_row = storage.get_user_by_tg(user_id)
    if not user_row:
        user_db_id = storage.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    else:
        user_db_id = user_row["id"]
    order_id = data.get("order_id")
    if not order_id:
        order_id, order_number = storage.create_order(
            user_db_id,
            item_code=item,
            size=size_order.upper(),
            zone=data.get("order_zone", "chest"),
            customization=customization_code,
            stickers=stickers_codes,
            sticker_zone=data.get("sticker_zone"),
            pet_name=pet_name,
            notes=notes,
        )
        await state.update_data({"order_id": order_id, "order_number": order_number})
    else:
        order_number = data.get("order_number")
        storage.update_order(
            order_id,
            item_code=item,
            size=size_order.upper(),
            zone=data.get("order_zone", "chest"),
            customization=customization_code,
            stickers=json.dumps(stickers_codes, ensure_ascii=False),
            sticker_zone=data.get("sticker_zone"),
            pet_name=pet_name,
        )
        if notes:
            storage.update_order_notes(order_id, **notes)
    storage.attach_preview(order_id, front_id, back_id)

    summary = (
        f"Заказ #{order_number or order_id}\n"
        f"Изделие: {order_label}\n"
        f"Размер: {size_order.upper()}\n"
        f"Зона нанесения: {zone}\n"
        f"Кастомизация: {customization_text}\n"
        f"Имя питомца: {pet_name}\n"
    )
    if data.get("selected_design_title"):
        summary += f"Дизайн: {data['selected_design_title']}\n"
    summary += (
        f"Стикеры: {stickers_text}\n\n"
        "Всё нравится?"
    )
    await callback.message.answer(summary, reply_markup=final_preview_keyboard().as_markup())


@router.callback_query(F.data == "preview_ok")
async def preview_ok(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_row = storage.get_user_by_tg(callback.from_user.id)
    if not user_row:
        user_id = storage.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user_row = storage.get_user_by_tg(callback.from_user.id)
    reward = storage.get_active_discount(user_row["id"])
    discount_percent = reward.percent if reward else 0
    price_info = calculate_order_price(data, discount_percent)
    addons_total = sum(value for _, value in price_info["addons"])
    storage.update_order(
        data.get("order_id"),
        base_price=price_info["base"],
        addons_price=addons_total,
        discount_percent=discount_percent,
        total_price=price_info["total"],
    )
    await state.update_data({"price": price_info, "discount_reward_id": reward.id if reward else None})
    text = build_price_message(price_info)
    if reward:
        text += "\n\nСкидка по твоей ссылке уже применена 💛"
    await callback.message.answer(text, reply_markup=checkout_or_edit_keyboard().as_markup())
    await state.set_state(Order.price)


@router.callback_query(F.data == "preview_designer")
async def preview_designer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_number = data.get("order_number", "—")
    await callback.bot.send_message(
        ADMIN_ID,
        f"Новая заявка на доработку #{order_number}\n"
        f"Изделие: {next((label for label, code in order_types.items() if code == data.get('order_type')), '—')}\n"
        f"Размер: {data.get('order_size', '').upper()}\n"
        f"Имя питомца: {data.get('pet_name', '—')}"
    )
    await callback.answer("Сообщение дизайнеру отправлено 💬", show_alert=True)


@router.callback_query(F.data == "preview_more")
async def preview_more(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    zones = zone_schemes.get(get_base_item(data.get("order_type")), zone_schemes["shirt"])
    await callback.message.answer("Выбери новую зону нанесения 👇", reply_markup=make_zone_keyboard(zones).as_markup())
    await state.set_state(Order.zone)


@router.callback_query(F.data == "preview_share")
async def preview_share(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_row = storage.get_user_by_tg(callback.from_user.id)
    if not user_row:
        user_id = storage.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user_row = storage.get_user_by_tg(callback.from_user.id)
    code = storage.create_referral_link(user_row["id"], data.get("order_id"), percent=3)
    link = await create_start_link(callback.bot, code)
    await state.update_data({"referral_code": code})
    await callback.message.answer(
        "Поделись ссылкой и получи −3% за каждого друга, который начнёт заказ:\n"
        f"{link}\n\nСкидка активна 48 часов после первого перехода."
    )


@router.callback_query(F.data == "edit")
async def edit_order(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=edit_keyboard().as_markup())


@router.callback_query(F.data == "ask_item")
async def edit_type(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    for item, code in order_types.items():
        builder.add(InlineKeyboardButton(
            text=str(item),
            callback_data="confirm_type_" + str(code)
        ))
    builder.adjust(3, 2)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data == "ask_order_size")
async def edit_order_size(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    for elem in sizes[:-1]:
        builder.add(InlineKeyboardButton(
            text=str(elem),
            callback_data="confirm_size_" + elem.lower()
        ))
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data == "start_again")
async def start_again(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.clear()
    await callback.message.answer(
        text='<b>Привет!</b>\nДобро пожаловать в бота по заказу принтов!\n\n'
             '<b>Выбери изделие, на которое хочешь нанести принт</b>',
        reply_markup=make_type_keyboard(order_types).as_markup()
    )


@router.callback_query(F.data == "edit_back")
async def edit_back(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=checkout_or_edit_keyboard().as_markup())


@router.callback_query(F.data == "edit_settings")
async def edit_settings(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    if bg_deleted[0]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    item = data["order_type"]
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    image1 = image.resize(tuple(size[0]), Image.Resampling.BICUBIC)
    front = paste(image1, color, print_pos[0], item, 0, angle[0], bg_deleted[0])
    file = image_to_bytes(front)
    await callback.message.delete()
    try:
        album_id = data["album_id"]
        chat_id = data["chat_id"]
        if album_id != -1:
            await callback.bot.delete_message(chat_id=chat_id, message_id=album_id)
            await callback.bot.delete_message(chat_id=chat_id, message_id=(album_id + 1))
    except KeyError:
        pass
    await state.update_data({"album_id": -1, "side": 0})
    await callback.message.answer_photo(file, reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data == "mailing_unsubscribe")
async def mailing_unsubscribe(callback: CallbackQuery):
    user = storage.get_user_by_tg(callback.from_user.id)
    if user:
        storage.set_subscription(user["id"], False)
    await callback.answer("Рассылки отключены 💛", show_alert=True)
    await callback.message.answer(
        "Вы отписались от рассылок AIVADOG 💛. Чтобы снова получать новости, просто отправь /start"
    )


@router.callback_query(F.data.in_(set(DELIVERY_RESPONSES)))
async def delivery_choice(callback: CallbackQuery):
    text = DELIVERY_RESPONSES.get(callback.data)
    if not text:
        await callback.answer()
        return
    await callback.answer()
    await callback.message.answer(text)


@router.message(Order.contact_name, F.text)
async def collect_contact_name(message: Message, state: FSMContext):
    await state.update_data({"contact_name": message.text.strip()})
    await message.answer("Теперь укажи номер телефона:")
    await state.set_state(Order.contact_phone)


@router.message(Order.contact_phone, F.text)
async def collect_contact_phone(message: Message, state: FSMContext):
    await state.update_data({"contact_phone": message.text.strip()})
    await message.answer("И последнее — e-mail (или отправь «—», если не хочешь делиться):")
    await state.set_state(Order.contact_email)


@router.message(Order.contact_email, F.text)
async def collect_contact_email(message: Message, state: FSMContext):
    email = message.text.strip()
    if email == "—":
        email = None
    data = await state.get_data()
    await state.update_data({"contact_email": email})
    order_id = data.get("order_id")
    user = storage.get_user_by_tg(message.from_user.id)
    if order_id:
        storage.update_order(
            order_id,
            contact_name=data.get("contact_name"),
            contact_phone=data.get("contact_phone"),
            contact_email=email,
        )
    if user:
        storage.update_user_contacts(
            user["id"],
            phone=data.get("contact_phone"),
            email=email,
            name=data.get("contact_name"),
        )
    await message.answer(
        "Отлично! Данные сохранены 💛\n\n"
        "Дизайнер получил твой заказ и приступит к созданию финального макета в течение 1–2 рабочих дней. "
        "Как только он будет готов — бот отправит тебе предпросмотр перед печатью.\n\n"
        "💬 Подписывайся на наш Telegram-канал https://t.me/aivadog_custom — там вдохновение, новые дизайны и скидки 🩶"
    )
    await state.clear()


@router.callback_query(F.data.startswith("ugc_start_"))
async def ugc_start(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.replace("ugc_start_", ""))
    user = storage.get_user_by_tg(callback.from_user.id)
    if not user:
        await callback.answer("Сначала запусти бота командой /start", show_alert=True)
        return
    order = storage.get_order(order_id)
    if not order or order["user_id"] != user["id"]:
        await callback.answer("Не нашли этот заказ 😔", show_alert=True)
        return
    if storage.has_ugc_submission(order_id):
        await callback.answer("По этому заказу скидка уже выдана", show_alert=True)
        return
    await state.set_state(UGCSubmission.waiting_photo)
    await state.update_data({"ugc_order_id": order_id})
    await callback.message.answer(
        "Хочешь скидку на следующий заказ? Пришли фото своего изделия 📸"
    )
    await callback.answer()


@router.message(UGCSubmission.waiting_photo, F.photo | F.document)
async def ugc_photo_received(message: Message, state: FSMContext):
    if message.photo:
        file_id = message.photo[-1].file_id
    else:
        if not message.document.mime_type or not message.document.mime_type.startswith("image/"):
            await message.answer("Нужен файл с изображением. Попробуй ещё раз 📎")
            return
        file_id = message.document.file_id
    await state.update_data({"ugc_photo_id": file_id})
    await message.answer("Отлично! Теперь введи номер заказа (формат AVD-XXXXXX):")
    await state.set_state(UGCSubmission.waiting_order_number)


@router.message(UGCSubmission.waiting_photo)
async def ugc_waiting_photo_text(message: Message):
    await message.answer("Пришли, пожалуйста, фото изделия 📸")


@router.message(UGCSubmission.waiting_order_number, F.text)
async def ugc_order_number(message: Message, state: FSMContext):
    order_number = message.text.strip().upper()
    data = await state.get_data()
    order = storage.get_order(data.get("ugc_order_id"))
    user = storage.get_user_by_tg(message.from_user.id)
    if not order or not user:
        await message.answer("Не удалось сопоставить заказ. Напиши менеджеру, мы поможем 🙏")
        await state.clear()
        return
    if order["order_number"] != order_number:
        await message.answer("Номер заказа не совпадает. Проверь формат и попробуй ещё раз.")
        return
    if storage.has_ugc_submission(order["id"]):
        await message.answer("По этому заказу уже выдавали скидку. Спасибо за отзыв! 💛")
        await state.clear()
        return
    promo_code = f"UGC-{order_number[-4:]}"
    storage.create_ugc_submission(order["id"], user["id"], data.get("ugc_photo_id"), percent=3, promo_code=promo_code)
    storage.grant_discount(user["id"], percent=3, source="ugc", metadata={"order_id": order["id"]})
    await message.answer("Спасибо! Фото отправлено менеджеру, а скидка −3% уже активна на следующий заказ ✨")
    if data.get("ugc_photo_id"):
        await message.bot.send_photo(
            ADMIN_ID,
            data["ugc_photo_id"],
            caption=f"UGC от @{message.from_user.username or message.from_user.id} по заказу #{order_number}",
        )
    await state.clear()
