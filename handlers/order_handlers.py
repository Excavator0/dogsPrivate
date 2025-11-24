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
from aiogram.types import CallbackQuery, InputMediaPhoto, InlineKeyboardButton, Message, FSInputFile
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards.order_keyboards
from config import ADMIN_ID
from database.db import Database
from image_processing import *
from image_processing import _resolve_template_path
from keyboards.confirmation_keyboards import *
from keyboards.order_keyboards import *
from keyboards.print_processing_keyboards import *
from services.designs import find_design, get_design_preview, list_ready_designs
from services.pricing import DEFAULT_PRICING, build_price_message, calculate_order_price
from services.stickers import list_stickers, list_sticker_categories, list_stickers_in_category, get_sticker_path

router = Router()
storage = Database()

order_types = {
    "Футболка • чёрная": "shirt_black",
    "Футболка • серая": "shirt_grey",
    "Футболка • зелёная": "shirt_green",
    "Футболка • розовая": "shirt_pink",
    "Худи": "hoodie",
    "Свитшот": "sweatshirt",
    "Штаны": "pants",
}

sizes = ["XS", "S", "M", "L", "XL", "2XL", "One size"]
size_step = 50

zone_schemes = {
    "shirt": [
        ("Грудь", "chest"),
        ("Спина", "back"),
    ],
    "hoodie": [
        ("Грудь", "chest"),
        ("Спина", "back"),
    ],
    "sweatshirt": [
        ("Грудь", "chest"),
        ("Спина", "back"),
    ],
    "zip": [
        ("Грудь", "chest"),
        ("Спина", "back"),
    ],
    "pants": [
        ("Левая штанина", "pant_left"),
        ("Правая штанина", "pant_right"),
    ],
}

sticker_catalog = list_stickers() or [
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
    # Отключаем кнопку «Хочу такой!» во вкладке макетов (example)
    if mode != "example":
        action_text = "Выбрать этот дизайн"
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
        reply_markup=make_customization_keyboard(show_ready_design=designs_available()).as_markup()
    )
    await state.set_state(Order.customization)


@router.callback_query(F.data == "back_to_items")
async def back_to_items(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text('Выбери изделие, на которое хочешь нанести принт')
    await callback.message.edit_reply_markup(reply_markup=make_type_keyboard(order_types).as_markup())
    await state.set_state(Order.order_type)


@router.callback_query(F.data.in_({"custom_ready", "custom_photo", "custom_stickers"}))
async def customization_selected(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.replace("custom_", "")
    # При смене варианта кастомизации сбрасываем неподходящие данные,
    # чтобы они не попадали в итоговый расчёт/сообщения
    update_payload = {
        "customization": choice,
        "stickers_planned": choice == "stickers",
    }
    # Если пользователь уходит с готового дизайна на фото/стикеры — очищаем выбранный макет
    if choice != "ready":
        update_payload.update(
            {
                "selected_design_id": None,
                "selected_design_title": None,
                "preferred_customization": None,
            }
        )
    await state.update_data(update_payload)
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
    await callback.message.edit_reply_markup(reply_markup=make_zone_keyboard(zones).as_markup())
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
    sticker_category = State()
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
        "sticker_items": [],
        "active_sticker_index": None,
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
            activated, owner_tg_id = storage.register_referral_hit(args, user["id"])
            if activated:
                # Notify the owner (who shared)
                if owner_tg_id:
                    try:
                        await message.bot.send_message(
                            owner_tg_id,
                            "Ура! По твоей ссылке пришёл новый пользователь — ты получил(а) скидку −3%!"
                        )
                    except Exception:
                        pass  # Owner might have blocked the bot
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
        await callback.message.edit_text(text="Галерея готовых дизайнов скоро появится, а пока можно сразу выбрать изделие 👇")
        await callback.message.edit_reply_markup(reply_markup=make_back_to_main_keyboard().as_markup())
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
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
    # Полностью выходим из сценария готового дизайна и чистим выбор макета,
    # чтобы он не учитывался в заказе
    await state.update_data(
        {
            "selected_design_id": None,
            "selected_design_title": None,
            "preferred_customization": None,
        }
    )
    await callback.message.delete()
    await callback.message.answer(
        "Выбери вариант кастомизации:",
        reply_markup=make_customization_keyboard(show_ready_design=designs_available()).as_markup()
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
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        text=("Привет! Я — AIVADOG-бот! 🐾\n\n"
              "Добро пожаловать в AIVADOG — место, где твой питомец становится частью твоего стиля 💛\n\n"
              "Здесь ты можешь:\n\n"
              "• выбрать изделие (футболку, худи, свитшот, штаны, брелок или шоппер),\n\n"
              "• загрузить фото своей собачки 🐶,\n\n"
              "• добавить фирменные принты и стикеры,\n\n"
              "• увидеть готовый предпросмотр перед заказом!\n\n"
              "С чего начнём?👇"),
        reply_markup=make_main_menu_keyboard().as_markup()
    )


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
        "sticker_items": [],
        "active_sticker_index": None,
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
            with Image.open(document) as image:
                image.save(f"prints/{user_id}.png", "PNG")
                template_width, template_height = get_template_bounds(item)
                centre_pos = [(template_width - image.size[0]) // 2,
                              (template_height - image.size[1]) // 2]
                await state.update_data(
                    {
                        "pos": [centre_pos, [-1, -1]],
                        "size": [image.size, image.size],
                        "angle": [0, 0],
                        "bg_deleted": [False, False],
                    }
                )

            # После загрузки изображения сначала спрашиваем кличку питомца,
            # а уже потом показываем фото с макетом
            data = await state.get_data()
            if not data.get("pet_name"):
                await message.answer("Фото принято ✅\nКак зовут твоего хвостика?")
                await state.set_state(Order.pet_name)
            else:
                # Если кличка уже известна (например, при редактировании заказа),
                # сразу показываем макет
                await _send_initial_mockup(message, state)
        else:
            await message.answer(
                text="Формат документа не поддерживается!"
            )


@router.message(Order.image_sent, F.photo)
async def photo_sent(message: Message):
    await message.answer("Отправьте фото документом, так не потеряется качество изображения")


async def _send_initial_mockup(message: Message, state: FSMContext):
    """Генерирует и отправляет первое фото с макетом после загрузки изображения."""
    data = await state.get_data()
    user_id = message.from_user.id
    item = data["order_type"]
    color = data.get("color")
    side = data.get("side", 0)
    print_pos = data.get("pos") or [[-1, -1], [-1, -1]]
    angle = data.get("angle") or [0, 0]
    size = data.get("size") or [[0, 0], [0, 0]]
    bg_deleted = data.get("bg_deleted") or [False, False]

    if bg_deleted[side]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")

    # Если размеры ещё не были сохранены, используем исходный размер изображения
    if not size[side] or size[side][0] == 0 or size[side][1] == 0:
        size[side] = list(image.size)

    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    base = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
    await message.answer_photo(file, reply_markup=confirm_or_setting_keyboard().as_markup())


def _apply_stickers_overlay(base_image: Image.Image, data: dict, side: int) -> Image.Image:
    """
    Накладывает выбранные стикеры на итоговый макет для нужной стороны.
    """
    sticker_items = data.get("sticker_items") or []
    if not sticker_items:
        return base_image
    composed = base_image.copy()
    width, height = composed.size
    for idx, item in enumerate(sticker_items):
        if item.get("side", 0) != side:
            continue
        code = item.get("code")
        path = get_sticker_path(code)
        if not path or not path.exists():
            continue
        try:
            sticker = Image.open(path).convert("RGBA")
        except Exception:
            continue
        size = item.get("size")
        angle = int(item.get("angle", 0)) % 360
        pos = item.get("pos") or [0, 0]
        if size and size[0] > 0 and size[1] > 0:
            sticker = sticker.resize(tuple(size), Image.Resampling.BICUBIC)
        if angle:
            sticker = sticker.rotate(angle, expand=True)
        # Пеpестрахуем позицию в пределах шаблона
        x = max(0, min(pos[0], width - 1))
        y = max(0, min(pos[1], height - 1))
        # Накладываем с сохранением альфы
        composed.paste(sticker, (x, y), sticker)
    return composed


async def _show_mockup_after_stickers(callback: CallbackQuery, state: FSMContext, reply_markup=None):
    """
    Восстанавливает макет в том же сообщении после работы со стикерами.
    Используется, когда пользователь закончил или отменил выбор стикеров.
    """
    data = await state.get_data()
    user_id = callback.from_user.id
    item = data["order_type"]
    color = data.get("color")
    side = data.get("side", 0)
    print_pos = data.get("pos") or [[-1, -1], [-1, -1]]
    angle = data.get("angle") or [0, 0]
    size = data.get("size") or [[0, 0], [0, 0]]
    bg_deleted = data.get("bg_deleted") or [False, False]

    if bg_deleted[side]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")

    if not size[side] or size[side][0] == 0 or size[side][1] == 0:
        size[side] = list(image.size)

    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    base = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
    media = InputMediaPhoto(media=file, caption=None)
    if reply_markup is None:
        reply_markup = make_settings_keyboard().as_markup()
    try:
        await callback.message.edit_media(media, reply_markup=reply_markup)
    except TelegramBadRequest:
        pass


async def _start_sticker_flow(target, state: FSMContext):
    data = await state.get_data()
    item = data.get("order_type")
    zones = [("К фото", "photo")] + zone_schemes.get(get_base_item(item), zone_schemes["shirt"])
    text = "Выбери зону нанесения стикера:"
    if isinstance(target, Message):
        # На всякий случай поддерживаем запуск из текстового сообщения
        await target.answer(text, reply_markup=make_sticker_zone_keyboard(zones).as_markup())
    else:
        # Для callback работаем всегда с одним сообщением:
        # меняем подпись и клавиатуру у текущего сообщения (с макетом или стикером)
        await target.message.edit_caption(caption=text)
        await target.message.edit_reply_markup(
            reply_markup=make_sticker_zone_keyboard(zones).as_markup()
        )
    await state.set_state(Order.sticker_zone)


async def _show_order_summary(message: Message, state: FSMContext):
    """Показывает итоговую информацию о заказе после confirm"""
    data = await state.get_data()
    item = data.get("order_type")
    size_order = data.get("order_size")
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
    
    order_id = data.get("order_id")
    order_number = data.get("order_number")
    
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
    await message.answer(summary, reply_markup=final_preview_keyboard().as_markup())


@router.message(Order.pet_name)
async def pet_name_received(message: Message, state: FSMContext):
    pet_name = message.text.strip()
    await state.update_data({"pet_name": pet_name})
    data = await state.get_data()
    customization = data.get("customization", "photo")
    
    # Если это был вызов после confirm для готового дизайна, показываем summary
    if customization == "ready" and data.get("front_id"):
        await _show_order_summary(message, state)
        return

    # После того как узнали кличку, показываем первое фото с макетом
    await _send_initial_mockup(message, state)

    # Дальше пользователь сам может открыть настройки и перейти к стикерам при необходимости


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
    await state.update_data({"sticker_zone": zone, "stickers": [], "sticker_items": [], "active_sticker_index": None})

    categories = list_sticker_categories()
    if not categories:
        await callback.answer("Стикеры скоро появятся 💛", show_alert=True)
        await _start_sticker_flow(callback, state)
        return

    # Меняем текст и клавиатуру в текущем сообщении (остается прежнее изображение)
    await callback.message.edit_caption("Выбери категорию стикеров 🐾")
    await callback.message.edit_reply_markup(
        reply_markup=make_sticker_categories_keyboard(categories).as_markup()
    )
    await state.set_state(Order.sticker_category)


@router.callback_query(Order.sticker_category, F.data.startswith("sticker_cat_"))
async def sticker_category_selected(callback: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал категорию стикеров — показываем первый стикер в виде карусели.
    """
    category_code = callback.data.replace("sticker_cat_", "")
    stickers = list_stickers_in_category(category_code)
    if not stickers:
        await callback.answer("В этой категории пока нет стикеров", show_alert=True)
        return

    codes = [code for _, code in stickers]
    await state.update_data(
        {
            "current_sticker_category": category_code,
            "current_sticker_codes": codes,
            "current_sticker_index": 0,
        }
    )

    first_code = codes[0]
    path = get_sticker_path(first_code)
    if not path or not path.exists():
        await callback.answer("Не удалось загрузить стикер", show_alert=True)
        return

    file = FSInputFile(path)
    media = InputMediaPhoto(media=file, caption="Листай стикеры и нажми «Добавить», чтобы выбрать 🐾")
    # Показываем первый стикер в том же сообщении, где был макет
    await callback.message.edit_media(
        media, reply_markup=make_sticker_view_keyboard(0, len(codes)).as_markup()
    )
    await callback.answer()
    await state.set_state(Order.sticker_choice)


@router.callback_query(
    Order.sticker_choice, F.data.in_({"sticker_prev", "sticker_next", "sticker_add"})
)
async def sticker_browse(callback: CallbackQuery, state: FSMContext):
    """
    Навигация по стикерам внутри выбранной категории и добавление текущего стикера.
    """
    data = await state.get_data()
    codes = data.get("current_sticker_codes") or []
    if not codes:
        await callback.answer("Сначала выбери категорию стикеров", show_alert=True)
        return

    index = int(data.get("current_sticker_index", 0)) % len(codes)

    if callback.data == "sticker_add":
        stickers = data.get("stickers", [])
        sticker_items = data.get("sticker_items") or []
        current_code = codes[index]
        if len(sticker_items) >= 10:
            await callback.answer("Можно добавить не больше 10 стикеров", show_alert=True)
            return
        # Добавляем код для summary
        stickers.append(current_code)
        # Создаём инстанс стикера со значениями по умолчанию
        item_code = data.get("order_type")
        template_width, template_height = get_template_bounds(item_code)
        # Рассчитываем базовый размер — 25% от ширины макета
        path = get_sticker_path(current_code)
        try:
            with Image.open(path) as st_img:
                w, h = st_img.size
        except Exception:
            w, h = (400, 400)
        max_w = max(50, template_width // 4)
        scale = min(max_w / float(w), 1.0)
        size_w = max(50, int(w * scale))
        size_h = max(50, int(h * scale))
        # Центрируем
        pos = [(template_width - size_w) // 2, (template_height - size_h) // 2]
        side = data.get("side", 0)
        sticker_items.append({
            "code": current_code,
            "pos": pos,
            "size": [size_w, size_h],
            "angle": 0,
            "side": side,
        })
        active_index = len(sticker_items) - 1
        await state.update_data({"stickers": stickers, "sticker_items": sticker_items, "active_sticker_index": active_index})
        # Переходим в меню редактирования стикеров в том же сообщении
        from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
        await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(active_index, len(sticker_items)).as_markup())
        await callback.answer("Стикер добавлен ✅", show_alert=False)
        return

    # Навигация влево/вправо
    if callback.data == "sticker_prev":
        index = (index - 1) % len(codes)
    elif callback.data == "sticker_next":
        index = (index + 1) % len(codes)

    await state.update_data({"current_sticker_index": index})
    code = codes[index]
    path = get_sticker_path(code)
    if not path or not path.exists():
        await callback.answer("Не удалось загрузить стикер", show_alert=True)
        return

    file = FSInputFile(path)
    media = InputMediaPhoto(
        media=file,
        caption="Листай стикеры и нажми «Добавить», чтобы выбрать 🐾",
    )
    try:
        await callback.message.edit_media(
            media, reply_markup=make_sticker_view_keyboard(index, len(codes)).as_markup()
        )
    except TelegramBadRequest:
        # На всякий случай, если Telegram не позволяет изменить медиа
        await callback.answer()


# === Редактирование добавленных стикеров ===
@router.callback_query(F.data == "st_manage")
async def stickers_manage(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(active, len(items)).as_markup())
    await callback.answer()


@router.callback_query(F.data == "st_select")
async def stickers_select(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_stickers_select_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    try:
        await callback.message.edit_caption(
            caption="Выбери стикер для редактирования",
            reply_markup=make_stickers_select_keyboard(len(items)).as_markup()
        )
    except TelegramBadRequest:
        await callback.message.edit_reply_markup(
            reply_markup=make_stickers_select_keyboard(len(items)).as_markup()
        )
    await callback.answer()


@router.callback_query(F.data.startswith("st_pick_"))
async def sticker_pick(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
    index = int(callback.data.replace("st_pick_", ""))
    data = await state.get_data()
    items = data.get("sticker_items") or []
    if not (0 <= index < len(items)):
        await callback.answer()
        return
    await state.update_data({"active_sticker_index": index})
    await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(index, len(items)).as_markup())
    await callback.answer("Стикер выбран", show_alert=False)


@router.callback_query(F.data == "st_move")
async def sticker_move_main(callback: CallbackQuery):
    from keyboards.print_processing_keyboards import make_sticker_move_keyboard
    await callback.message.edit_reply_markup(reply_markup=make_sticker_move_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data.in_({"st_move_up", "st_move_down", "st_move_left", "st_move_right", "st_move_centre"}))
async def sticker_move(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_sticker_move_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    item_code = data.get("order_type")
    template_width, template_height = get_template_bounds(item_code)
    sticker = items[active]
    pos = sticker.get("pos") or [0, 0]
    size = sticker.get("size") or [100, 100]
    angle = int(sticker.get("angle", 0))
    changed = False
    if callback.data == "st_move_right":
        if (pos[0] + size_step) < template_width:
            pos[0] += size_step
            changed = True
    elif callback.data == "st_move_left":
        if (pos[0] - size_step) > 0:
            pos[0] -= size_step
            changed = True
    elif callback.data == "st_move_up":
        if (pos[1] - size_step) > 0:
            pos[1] -= size_step
            changed = True
    elif callback.data == "st_move_down":
        if (pos[1] + size_step) < template_height:
            pos[1] += size_step
            changed = True
    elif callback.data == "st_move_centre":
        # учитываем поворот на 90/270
        rotations = angle % 180
        if rotations == 0:
            pos[0] = (template_width - size[0]) // 2
            pos[1] = (template_height - size[1]) // 2
        else:
            pos[0] = (template_width - size[1]) // 2
            pos[1] = (template_height - size[0]) // 2
        changed = True
    if changed:
        sticker["pos"] = pos
        items[active] = sticker
        await state.update_data({"sticker_items": items})
        await _show_mockup_after_stickers(callback, state, reply_markup=make_sticker_move_keyboard().as_markup())
    else:
        await callback.answer()


@router.callback_query(F.data == "st_size")
async def sticker_size_main(callback: CallbackQuery):
    from keyboards.print_processing_keyboards import make_sticker_size_keyboard
    await callback.message.edit_reply_markup(reply_markup=make_sticker_size_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data.in_({"st_increase_size", "st_decrease_size"}))
async def sticker_size(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_sticker_size_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    item_code = data.get("order_type")
    template_width, template_height = get_template_bounds(item_code)
    sticker = items[active]
    size = sticker.get("size") or [100, 100]
    x_size, y_size = size
    changed = False
    if callback.data == "st_decrease_size":
        decrease_k = 5 / 6
        if (x_size * decrease_k > size_step) and (y_size * decrease_k > size_step):
            size = [int(x_size * decrease_k), int(y_size * decrease_k)]
            changed = True
        else:
            await callback.answer("Достигнут минимум размера стикера")
    else:
        increase_k = 1.2
        if (x_size * increase_k < template_width) and (y_size * increase_k < template_height):
            size = [int(x_size * increase_k), int(y_size * increase_k)]
            changed = True
        else:
            await callback.answer("Достигнут максимум размера стикера")
    if changed:
        sticker["size"] = size
        items[active] = sticker
        await state.update_data({"sticker_items": items})
        await _show_mockup_after_stickers(callback, state, reply_markup=make_sticker_size_keyboard().as_markup())
    else:
        await callback.answer()


@router.callback_query(F.data == "st_rotate")
async def sticker_rotate_main(callback: CallbackQuery):
    from keyboards.print_processing_keyboards import make_sticker_rotate_keyboard
    await callback.message.edit_reply_markup(reply_markup=make_sticker_rotate_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data.in_({"st_rotate_left", "st_rotate_right"}))
async def sticker_rotate(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_sticker_rotate_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    sticker = items[active]
    angle = int(sticker.get("angle", 0))
    if callback.data == "st_rotate_right":
        angle += 270
    else:
        angle += 90
    sticker["angle"] = angle
    items[active] = sticker
    await state.update_data({"sticker_items": items})
    await _show_mockup_after_stickers(callback, state, reply_markup=make_sticker_rotate_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data == "st_change_side")
async def sticker_change_side(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    sticker = items[active]
    # меняем сторону и сбрасываем позицию/угол, центруем
    new_side = 0 if sticker.get("side", 0) == 1 else 1
    item_code = data.get("order_type")
    template_width, template_height = get_template_bounds(item_code)
    w, h = sticker.get("size") or [100, 100]
    pos = [(template_width - w) // 2, (template_height - h) // 2]
    sticker.update({"side": new_side, "pos": pos, "angle": 0})
    items[active] = sticker
    await state.update_data({"sticker_items": items})
    await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(active, len(items)).as_markup())
    await callback.answer()


@router.callback_query(F.data == "st_delete")
async def sticker_delete(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    # Удаляем инстанс и одну запись кода из summary списков (первое вхождение)
    sticker_code = items[active].get("code")
    items.pop(active)
    codes = data.get("stickers") or []
    if sticker_code in codes:
        codes.remove(sticker_code)
    new_active = None if not items else min(active, len(items) - 1)
    await state.update_data({"sticker_items": items, "stickers": codes, "active_sticker_index": new_active})
    if not items:
        await _show_mockup_after_stickers(callback, state, reply_markup=make_settings_keyboard().as_markup())
        await callback.answer("Стикер удалён", show_alert=False)
        return
    await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(new_active, len(items)).as_markup())
    await callback.answer("Стикер удалён", show_alert=False)


@router.callback_query(F.data == "stickers_done")
async def stickers_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stickers = data.get("stickers", [])
    if not stickers:
        await callback.answer("Выбери хотя бы один стикер", show_alert=True)
        return
    # После выбора стикеров возвращаемся к макету в этом же сообщении
    from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(active, len(items)).as_markup())
    await callback.answer("Стикеры добавлены. Проверь макет и продолжай настройки ✅", show_alert=False)
    # Состояние можно не менять жёстко — пользователь продолжает работу через настройки / confirm


@router.callback_query(F.data == "stickers_back")
async def stickers_back(callback: CallbackQuery, state: FSMContext):
    # Возвращаемся к выбору зоны в этом же сообщении
    await _start_sticker_flow(callback, state)


@router.callback_query(F.data == "stickers_cancel")
async def stickers_cancel(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"stickers": [], "sticker_items": [], "active_sticker_index": None, "stickers_planned": False})
    # Отмена — возвращаем макет и настройки в том же сообщении
    await _show_mockup_after_stickers(callback, state)
    await callback.answer("Вернулись к макету. Стикеры очищены.", show_alert=False)


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
        base = paste(image, color, print_pos[side], item, side, angle[side], True)
        data = await state.get_data()
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
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
    base = paste(image, color, print_pos[side], item, side, angle[side], False)
    data = await state.get_data()
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
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
        base = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
        data = await state.get_data()
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
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
    template_width, template_height = get_template_bounds(item)
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
        base = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
        data = await state.get_data()
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
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
    base = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
    data = await state.get_data()
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
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
    template_width, template_height = get_template_bounds(item)
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
    base = paste(image, color, print_pos[side], item, side, angle[side], bg_deleted[side])
    data = await state.get_data()
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
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
        base = paste(None, color, print_pos[side], item, side, angle[side], bg_deleted[side])
        data = await state.get_data()
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
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
    data_for_overlay = await state.get_data()
    front = _apply_stickers_overlay(front, data_for_overlay, 0)
    file1 = InputMediaPhoto(media=image_to_bytes(front))

    if isinstance(print_pos[1], list) and print_pos[1][0] == -1:
        print_pos[1] = "deleted"

    base_back_image = Image.open(f"prints/{user_id}_bg_deleted.png") if bg_deleted[1] else Image.open(
        f"prints/{user_id}.png")
    image2 = base_back_image.resize(tuple(size[1]), Image.Resampling.BICUBIC)
    back = paste(image2, color, print_pos[1], item, 1, angle[1], bg_deleted[1])
    back = _apply_stickers_overlay(back, data_for_overlay, 1)
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
    # После нажатия «Продолжить» спрашиваем имя питомца (если ещё не задано)
    # Для варианта "ready" (готовый дизайн) спрашиваем имя здесь
    if not data.get("pet_name") and data.get("customization") == "ready":
        await callback.message.answer("Фото принято ✅\nКак зовут твоего хвостика?", disable_notification=True)
        await state.set_state(Order.pet_name)
        return
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
    # Сохраняем информацию о выбранном готовом дизайне (если он есть)
    design_id = data.get("selected_design_id")
    design_title = data.get("selected_design_title")
    notes = {}
    if design_id:
        notes["ready_design_id"] = design_id
    if design_title:
        notes["ready_design_title"] = design_title

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
        # Обновляем / очищаем данные о готовом дизайне в notes_json:
        # если макет снят, в БД не должно оставаться старой записи.
        storage.update_order_notes(
            order_id,
            ready_design_id=design_id,
            ready_design_title=design_title,
        )
    storage.attach_preview(order_id, front_id, back_id)
    await state.update_data({"order_id": order_id, "order_number": order_number})

    # Показываем итоговый summary через общую функцию
    await _show_order_summary(callback.message, state)


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
    # Явно показываем выбранный готовый дизайн в итоговом сообщении перед оплатой
    design_title = data.get("selected_design_title")
    if design_title:
        text = f"Выбранный дизайн: {design_title}\n\n" + text
    if reward:
        text += "\n\nСкидка по твоей ссылке уже применена 💛"
    await callback.message.answer(text, reply_markup=checkout_or_edit_keyboard().as_markup())
    await state.set_state(Order.price)


@router.callback_query(F.data == "preview_designer")
async def preview_designer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_number = data.get("order_number", "—")
    
    text = (
        f"Новая заявка на доработку #{order_number}\n"
        f"Изделие: {next((label for label, code in order_types.items() if code == data.get('order_type')), '—')}\n"
        f"Размер: {data.get('order_size', '').upper()}\n"
        f"Имя питомца: {data.get('pet_name', '—')}"
    )
    
    front_id = data.get("front_id")
    back_id = data.get("back_id")
    user_id = callback.from_user.id
    user_photo_path = f"prints/{user_id}.png"
    
    media = []
    if front_id:
        media.append(InputMediaPhoto(media=front_id, caption="Макет (перед)"))
    if back_id:
        media.append(InputMediaPhoto(media=back_id, caption="Макет (зад)"))
    
    if os.path.exists(user_photo_path):
        # For local file we use FSInputFile
        user_photo = FSInputFile(user_photo_path)
        media.append(InputMediaPhoto(media=user_photo, caption="Фото клиента"))
        
    if media:
        # Set caption only for first element to avoid duplicates if we wanted one caption for group, 
        # but here we used individual captions. Telegram might only show the first one or combine.
        # To be safe, let's put the main text in a separate message or attached to the first photo.
        # Let's send text first.
        await callback.bot.send_message(ADMIN_ID, text)
        await callback.bot.send_media_group(ADMIN_ID, media)
    else:
        await callback.bot.send_message(ADMIN_ID, text)

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
    base_front = paste(image1, color, print_pos[0], item, 0, angle[0], bg_deleted[0])
    base_front = _apply_stickers_overlay(base_front, data, 0)
    file = image_to_bytes(base_front)
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


@router.callback_query(F.data == "edit_stickers")
async def edit_stickers(callback: CallbackQuery, state: FSMContext):
    """
    Переход в режим выбора/редактирования стикеров из настроек принта.
    """
    data = await state.get_data()
    items = data.get("sticker_items") or []
    if items:
        from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
        active = data.get("active_sticker_index")
        await _show_mockup_after_stickers(callback, state, reply_markup=make_stickers_manage_keyboard(active, len(items)).as_markup())
    else:
        await _start_sticker_flow(callback, state)


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
