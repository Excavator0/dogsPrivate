import json
import os
import time
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Union

from PIL import Image

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
from image_processing import _resolve_template_path, _get_centered_position_in_zone, _get_zone_mask_for_overlay, \
    _clamp_position_with_mask, _get_zone_mask_bbox
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
        ("Левый рукав", "sleeve_left"),
        ("Правый рукав", "sleeve_right"),
        ("Капюшон слева", "hood_left"),
        ("Капюшон справа", "hood_right"),
    ],
    "sweatshirt": [
        ("Грудь", "chest"),
        ("Спина", "back"),
        ("Левый рукав", "sleeve_left"),
        ("Правый рукав", "sleeve_right"),
    ],
    "pants": [
        ("Перед — левая штанина", "pant_front_left"),
        ("Перед — правая штанина", "pant_front_right"),
        ("Зад — левая штанина", "pant_back_left"),
        ("Зад — правая штанина", "pant_back_right"),
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
    return f"{design.title} — фирменный макет AIVADOG. Добавим твоего питомца, дизайнер адаптирует его под стиль макета и покажем предпросмотр"


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
        f"Ты выбрал макет {design_title}. Теперь загрузи фото питомца документом (PNG/JPG до 2 МБ) "
        "Ракурс должен быть похож на пример.",
        reply_markup=builder.as_markup(),
    )
    await state.update_data({"preferred_customization": None, "customization": "ready"})
    await state.set_state(Order.image_sent)

@router.callback_query(F.data.startswith("zone_"))
async def choose_customization(callback: CallbackQuery, state: FSMContext):
    zone = callback.data.replace("zone_", "")
    # Определяем сторону по выбранной зоне: спина / зад штанов -> back (1), остальное -> front (0)
    side = 1 if zone == "back" or zone in ("pant_back_left", "pant_back_right") else 0
    await state.update_data({"order_zone": zone, "side": side})
    data = await state.get_data()
    if data.get("preferred_customization") == "ready":
        await _handle_preselected_ready(callback, state)
        return
    zone_title = zone_label(zone)
    await callback.message.edit_text(
        text=f"Выбери вариант кастомизации для зоны {zone_title}:"
    )
    await callback.message.edit_reply_markup(
        reply_markup=make_customization_keyboard(show_ready_design=designs_available()).as_markup()
    )
    await state.set_state(Order.customization)


@router.callback_query(F.data == "back_to_items")
async def back_to_items(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"zone_return": None})
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


@router.callback_query(F.data == "back_to_customization")
async def back_to_customization(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    zone = data.get("order_zone", "chest")
    zone_title = zone_label(zone)
    text = f"Выбери вариант кастомизации для зоны «{zone_title}»:"
    keyboard = make_customization_keyboard(show_ready_design=designs_available()).as_markup()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer(text, reply_markup=keyboard)
    await state.update_data({"edit_history": None})
    await state.set_state(Order.customization)
    await callback.answer()


@router.callback_query(F.data == "back_to_zones")
async def back_to_zones(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    zones = zone_schemes.get(get_base_item(data.get("order_type")), zone_schemes["shirt"])
    await callback.message.edit_text("Выбери зону нанесения принта 👇")
    await callback.message.edit_reply_markup(reply_markup=make_zone_keyboard(zones).as_markup())
    await state.set_state(Order.zone)

@router.callback_query(F.data == "back_zone")
async def back_zone(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    return_mode = data.get("zone_return")
    if return_mode == "sizes":
        await state.update_data({"zone_return": None})
        await callback.message.edit_text("Выбери размер изделия")
        await callback.message.edit_reply_markup(
            reply_markup=make_sizes_keyboard(sizes[:-1]).as_markup()
        )
        await state.set_state(Order.order_size)
    elif return_mode == "preview":
        await state.update_data({"zone_return": None})
        await _show_order_summary(callback.message, state, edit=True)
        await state.set_state(Order.customization)
    else:
        await state.update_data({"zone_return": None})
        await callback.message.edit_text('Выбери изделие, на которое хочешь нанести принт')
        await callback.message.edit_reply_markup(make_type_keyboard(order_types).as_markup())
        await state.set_state(Order.order_type)
    await callback.answer()


def get_base_item(item_code: str) -> str:
    return item_code.split("_", 1)[0]


@lru_cache(maxsize=32)
def get_template_bounds(item_code: str) -> tuple[int, int]:
    """
    Обёртка вокруг image_processing.get_template_bounds для совместимости.
    """
    from image_processing import get_template_bounds as _gtb
    return _gtb(item_code)


def _make_edit_snapshot(data: dict) -> dict:
    """
    Сохраняет ключевые параметры текущего макета для отката изменений
    в режиме редактирования.
    """
    keys = [
        "pos",
        "size",
        "angle",
        "bg_deleted",
        "side",
        "order_zone",
        "current_zone_photo",
        "stickers",
        "sticker_items",
    ]
    snapshot = {}
    for key in keys:
        if key in data:
            snapshot[key] = deepcopy(data.get(key))
    return snapshot


async def _ensure_edit_snapshot(state: FSMContext) -> None:
    """
    Гарантирует, что в состоянии есть история изменений для отката.
    """
    data = await state.get_data()
    history = data.get("edit_history")
    if not isinstance(history, list) or not history:
        snapshot = _make_edit_snapshot(data)
        await state.update_data({"edit_history": [snapshot]})


async def _push_edit_snapshot(state: FSMContext) -> None:
    """
    Добавляет текущий снимок макета в историю изменений.
    """
    data = await state.get_data()
    history = data.get("edit_history")
    if not isinstance(history, list):
        history = []
    snapshot = _make_edit_snapshot(data)
    history.append(snapshot)
    if len(history) > 30:
        history = history[-30:]
    await state.update_data({"edit_history": history})


async def _restore_edit_snapshot(state: FSMContext) -> bool:
    """
    Откатывает последнее изменение. Возвращает True, если откат выполнен.
    """
    data = await state.get_data()
    history = data.get("edit_history")
    if not isinstance(history, list) or len(history) <= 1:
        return False

    history = history[:-1]
    snapshot = deepcopy(history[-1])

    updates = {}
    for key, value in snapshot.items():
        updates[key] = deepcopy(value)

    updates.setdefault("stickers", [])
    updates.setdefault("sticker_items", [])
    updates.setdefault("side", data.get("side", 0))
    updates.setdefault("order_zone", data.get("order_zone", "chest"))
    updates.setdefault("bg_deleted", data.get("bg_deleted") or [False, False])
    updates.setdefault("angle", data.get("angle") or [0, 0])
    updates.setdefault("size", data.get("size") or [[0, 0], [0, 0]])
    updates.setdefault("pos", data.get("pos") or [[-1, -1], [-1, -1]])

    updates["current_print_archived"] = False
    updates["edit_history"] = history
    await state.update_data(updates)
    return True


def _get_template_override_path(data: dict, side: int) -> str | None:
    overrides = data.get("template_overrides")
    if isinstance(overrides, list) and len(overrides) > side:
        path = overrides[side]
        if path and os.path.exists(path):
            return path
    return None


def _has_active_print(pos_list) -> bool:
    if not isinstance(pos_list, list):
        return False
    for pos in pos_list:
        if isinstance(pos, list) and pos and pos[0] != -1:
            return True
    return False


def _has_print_on_side(data: dict, side: int) -> bool:
    """
    Проверяет, есть ли принт или стикеры на указанной стороне.
    """
    # Проверяем позицию принта
    pos = data.get("pos") or [[-1, -1], [-1, -1]]
    if len(pos) > side:
        pos_side = pos[side]
        if isinstance(pos_side, list) and pos_side and pos_side[0] != -1:
            return True
    
    # Проверяем стикеры на этой стороне
    sticker_items = data.get("sticker_items") or []
    for item in sticker_items:
        if item.get("side", 0) == side:
            return True
    
    return False


def _load_user_photo(user_id: int, data: dict, side: int, for_bg_deleted: bool = False) -> Image.Image:
    """
    Загружает фото пользователя для текущей зоны.
    Если для зоны сохранено отдельное фото — использует его.
    Иначе пытается загрузить общее фото пользователя.
    """
    current_photo_path = data.get("current_zone_photo")
    
    # Для готового дизайна
    customization = data.get("customization", "photo")
    if customization == "ready" and data.get("selected_design_id"):
        design = find_design(data["selected_design_id"])
        from services.designs import _build_preview
        design_path = _build_preview(design) if design else None
        if design_path:
            return Image.open(design_path)
        elif current_photo_path and os.path.exists(current_photo_path):
            return Image.open(current_photo_path)
        elif os.path.exists(f"prints/{user_id}.png"):
            return Image.open(f"prints/{user_id}.png")
    
    # Для обычного фото
    if current_photo_path and os.path.exists(current_photo_path):
        if for_bg_deleted:
            bg_deleted_path = current_photo_path.replace(".png", "_nobg.png")
            if os.path.exists(bg_deleted_path):
                return Image.open(bg_deleted_path)
        return Image.open(current_photo_path)
    
    # Fallback на старые пути
    if for_bg_deleted and os.path.exists(f"prints/{user_id}_bg_deleted.png"):
        return Image.open(f"prints/{user_id}_bg_deleted.png")
    elif os.path.exists(f"prints/{user_id}.png"):
        return Image.open(f"prints/{user_id}.png")
    
    raise FileNotFoundError(f"Не найдено фото для пользователя {user_id}")


async def _archive_current_print(state: FSMContext):
    """
    Переносит текущий принт/стикеры в «зафиксированные» и подготавливает данные
    для следующего цикла (после «Хочу ещё выбрать принт»).
    
    Сохраняет данные о принте в zone_prints[zone_code] для последующей генерации макетов.
    Поддерживает несколько фото/дизайнов на одной зоне — хранит список prints.
    """
    data = await state.get_data()
    # Если текущий принт уже был сохранён (через confirm), повторно не архивируем,
    # чтобы не дублировать его в zone_prints
    if data.get("current_print_archived"):
        return
    zone = data.get("order_zone", "chest")
    side = data.get("side", 0)
    pos = data.get("pos") or [[-1, -1], [-1, -1]]
    size = data.get("size") or [[0, 0], [0, 0]]
    angle = data.get("angle") or [0, 0]
    bg_deleted = data.get("bg_deleted") or [False, False]
    sticker_items = data.get("sticker_items") or []
    
    # Проверяем, есть ли что сохранять
    has_print = isinstance(pos[side], list) and pos[side][0] != -1
    has_stickers = bool(sticker_items)
    
    if has_print or has_stickers:
        # Получаем или создаём словарь зон
        zone_prints = dict(data.get("zone_prints") or {})
        
        # Получаем существующие данные для этой зоны (если есть)
        existing_zone_data = zone_prints.get(zone, {})
        existing_prints = existing_zone_data.get("prints", [])
        existing_sticker_items = existing_zone_data.get("sticker_items", [])
        
        # Текущие стикеры для этой стороны
        current_sticker_items = [item for item in sticker_items if item.get("side", 0) == side]
        
        # Объединяем стикеры (добавляем новые к существующим)
        combined_sticker_items = existing_sticker_items + current_sticker_items
        
        # Создаём запись о текущем принте
        current_customization = data.get("customization")
        if has_print:
            current_print = {
                "pos": pos[side],
                "size": size[side],
                "angle": angle[side],
                "bg_deleted": bg_deleted[side],
                "customization": current_customization,
                "photo_path": data.get("current_zone_photo"),
                "selected_design_id": data.get("selected_design_id"),
                "selected_design_title": data.get("selected_design_title"),
            }
            combined_prints = existing_prints + [current_print]
        else:
            combined_prints = existing_prints
        
        # Собираем все типы кастомизации
        customization_types = set()
        for p in combined_prints:
            if p.get("customization"):
                customization_types.add(p["customization"])
        
        # Собираем все названия дизайнов
        design_titles = []
        for p in combined_prints:
            title = p.get("selected_design_title")
            if title and title not in design_titles:
                design_titles.append(title)
        
        # Сохраняем данные для этой зоны
        zone_prints[zone] = {
            "side": side,
            "prints": combined_prints,  # Список всех принтов на этой зоне
            "sticker_items": combined_sticker_items,
            "customization_types": list(customization_types),
            "design_titles": design_titles,
            "has_photo": any(p.get("customization") in ("photo", "stickers") for p in combined_prints),
            "has_design": any(p.get("customization") == "ready" for p in combined_prints),
        }
        
        await state.update_data({"zone_prints": zone_prints})
    
    # Сбрасываем ТОЛЬКО текущие данные для нового цикла, но НЕ удаляем zone_prints!
    # Устанавливаем флаг что текущий принт архивирован
    await state.update_data(
        {
            "stickers": [],
            "sticker_items": [],
            "active_sticker_index": None,
            "current_sticker_codes": [],
            "current_sticker_index": 0,
            "current_sticker_category": None,
            "pos": [[-1, -1], [-1, -1]],
            "size": [[0, 0], [0, 0]],
            "angle": [0, 0],
            "bg_deleted": [False, False],
            "side": 0,
            "order_zone": "chest",
            "customization": None,
            "selected_design_id": None,
            "selected_design_title": None,
            "stickers_planned": False,
            "current_zone_photo": None,
            "current_print_archived": True,  # Флаг что текущий принт уже сохранён
            "edit_history": None,
        }
    )


def zone_label(zone_code: str) -> str:
    mapping = {
        "chest": "Грудь",
        "back": "Спина",
        "sleeve_left": "Левый рукав",
        "sleeve_right": "Правый рукав",
        "hood": "Капюшон",
        "hood_left": "Капюшон слева",
        "hood_right": "Капюшон справа",
        "pant_left": "Левая штанина",
        "pant_right": "Правая штанина",
        "pant_front_left": "Перед — левая штанина",
        "pant_front_right": "Перед — правая штанина",
        "pant_back_left": "Зад — левая штанина",
        "pant_back_right": "Зад — правая штанина",
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


def _cleanup_user_files(user_id: int):
    """
    Удаляет все файлы пользователя из папки prints при начале нового взаимодействия.
    """
    prints_dir = "prints"
    if not os.path.exists(prints_dir):
        return
    
    user_prefix = str(user_id)
    for filename in os.listdir(prints_dir):
        if filename.startswith(user_prefix):
            try:
                os.remove(os.path.join(prints_dir, filename))
            except OSError:
                pass


@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    # Удаляем все файлы пользователя при начале нового взаимодействия
    _cleanup_user_files(message.from_user.id)
    
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
              "• передать макет дизайнеру\n"
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
        "template_overrides": [None, None],
        "applied_photos": 0,
        "applied_stickers": [],
        "zone_prints": {},
        "all_zones": [],
    })


@router.message(CommandStart(deep_link=False))
async def start_default(message: Message, state: FSMContext):
    await cmd_start(message, state)


@router.message(CommandStart(deep_link=True))
async def start_with_link(message: Message, command: CommandObject, state: FSMContext):
    # Удаляем все файлы пользователя при начале нового взаимодействия
    _cleanup_user_files(message.from_user.id)
    
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
    await state.clear()
    await state.update_data({"order_type": args, "order_label": order_label, "pos": [[-1, -1], [-1, -1]], "side": 0, "stickers": [], "zone_prints": {}})
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
        "AIVADOG – бренд, созданный из любви к питомцам\n\n"
        "Мы создаём одежду и аксессуары с уникальными принтами питомцев, чтобы ваш любимец всегда был рядом с вами, "
        "ведь каждый день с питомцем – это радость, уют и маленькие моменты, которые делают жизнь ярче\n\n"
        "С любовью к деталям, этике и качеству – каждый дизайн проходит ручную доработку, печать делается с вниманием к материалам и цветам\n\n"
        "Мы верим, что любовь к нашим хвостикам можно носить с собой – на худи, футболке, на брелке или шоппере\n\n"
        "AIVADOG – это не просто одежда, а способ показать, как сильно вы связаны со своим любимцем ❤️"
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
        f"Дизайн {design.title} сохранён! Теперь выбери изделие 👇",
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
        "current_print_archived": False,  # Сбрасываем флаг — новый дизайн ещё не архивирован
    })
    await callback.message.delete()
    await callback.message.answer(
        f"Отлично! Теперь загрузи фото своего питомца документом (PNG/JPG до 2 МБ), чтобы мы вставили его в макет {design.title}.\n\n"
        f"⚠️ Важно: ракурс питомца должен быть похож на пример в выбранном дизайне",
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
              "Здесь ты можешь:\n"
              "• выбрать изделие\n"
              "• загрузить фото своей собачки 🐶\n"
              "• добавить фирменные принты и стикеры\n"
              "• передать макет дизайнеру\n"
              "• увидеть предпросмотр и оплатить заказ\n\n"
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
        "template_overrides": [None, None],
        "applied_photos": 0,
        "applied_stickers": [],
        "zone_prints": {},
        "all_zones": [],
    })
    await callback.message.edit_text(text="Выбери размер изделия")
    await callback.message.edit_reply_markup(
        reply_markup=make_sizes_keyboard(sizes[:-1]).as_markup()
    )
    await state.set_state(Order.order_size)


@router.callback_query(F.data.startswith("size_"))
async def order_zone(callback: CallbackQuery, state: FSMContext):
    size = callback.data.replace("size_", "").upper()
    await state.update_data({"order_size": size, "zone_return": "sizes"})
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
            zone = data.get("order_zone", "chest")
            side = data.get("side", 0)
            
            # Генерируем уникальный номер для этого фото (timestamp)
            photo_id = int(time.time() * 1000) % 1000000
            
            # Сохраняем фото с уникальным именем: user_item_zone_photoid.png
            # Это гарантирует что каждое загруженное фото сохраняется отдельно
            photo_filename = f"{user_id}_{item}_{zone}_{photo_id}.png"
            photo_path = f"prints/{photo_filename}"
            
            with Image.open(document) as image:
                image.save(photo_path, "PNG")
                template_width, template_height = get_template_bounds(item)
                
                # Получаем границы для размещения принта на нужной стороне
                centre_pos = _get_centered_position_in_zone(
                    item,
                    side,
                    zone,
                    image.size[0],
                    image.size[1],
                )
                
                # Устанавливаем позицию на правильную сторону (side)
                pos = [[-1, -1], [-1, -1]]
                pos[side] = centre_pos
                
                # Отслеживаем все загруженные фото пользователя
                user_photos = data.get("user_photos") or {}
                user_photos[f"{item}_{zone}"] = photo_path
                
                await state.update_data(
                    {
                        "pos": pos,
                        "size": [list(image.size), list(image.size)],
                        "angle": [0, 0],
                        "bg_deleted": [False, False],
                        "current_zone_photo": photo_path,
                        "user_photos": user_photos,
                        "current_print_archived": False,  # Сбрасываем флаг — новое фото ещё не архивировано
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
    zone = data.get("order_zone", "chest")
    color = data.get("color")
    side = data.get("side", 0)
    print_pos = data.get("pos") or [[-1, -1], [-1, -1]]
    angle = data.get("angle") or [0, 0]
    size = data.get("size") or [[0, 0], [0, 0]]
    bg_deleted = data.get("bg_deleted") or [False, False]
    
    # Путь к фото для текущей зоны
    current_photo_path = data.get("current_zone_photo")

    customization = data.get("customization", "photo")
    if customization == "ready" and data.get("selected_design_id"):
        design = find_design(data["selected_design_id"])
        from services.designs import _build_preview
        design_path = _build_preview(design) if design else None
        if design_path:
            image = Image.open(design_path)
        elif current_photo_path and os.path.exists(current_photo_path):
            image = Image.open(current_photo_path)
        else:
            image = Image.open(f"prints/{user_id}.png")
    else:
        # Используем фото для текущей зоны
        if current_photo_path and os.path.exists(current_photo_path):
            if bg_deleted[side]:
                # Проверяем версию без фона
                bg_deleted_path = current_photo_path.replace(".png", "_nobg.png")
                if os.path.exists(bg_deleted_path):
                    image = Image.open(bg_deleted_path)
                else:
                    image = Image.open(current_photo_path)
            else:
                image = Image.open(current_photo_path)
        elif bg_deleted[side] and os.path.exists(f"prints/{user_id}_bg_deleted.png"):
            image = Image.open(f"prints/{user_id}_bg_deleted.png")
        else:
            image = Image.open(f"prints/{user_id}.png")

    # Если размеры ещё не были сохранены, используем исходный размер изображения
    if not size[side] or size[side][0] == 0 or size[side][1] == 0:
        size[side] = list(image.size)

    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, side)
    
    # Сначала накладываем архивные принты на пустой шаблон
    base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
    base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
    
    # Затем накладываем текущее фото поверх
    base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
    
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


def _overlay_current_print(base_image: Image.Image, print_image: Image.Image, pos, angle_val: int, item: str, side: int, zone: str) -> Image.Image:
    """
    Накладывает текущее фото/дизайн на макет с обрезкой по границам зоны.
    """
    if pos == "deleted" or (isinstance(pos, list) and pos[0] == -1):
        return base_image
    
    zone_mask = _get_zone_mask_for_overlay(item, side, zone, base_image.size)
    
    composed = base_image.copy().convert("RGBA")
    
    # Поворачиваем если нужно
    if angle_val:
        print_image = print_image.rotate(angle_val, expand=True)
    
    # Создаём слой для принта
    print_image = print_image.convert("RGBA")
    print_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    print_layer.paste(print_image, tuple(pos), print_image)
    
    # Применяем маску зоны для обрезки
    if zone_mask:
        masked_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
        masked_layer.paste(print_layer, (0, 0), zone_mask)
        print_layer = masked_layer
    
    # Накладываем на макет
    return Image.alpha_composite(composed, print_layer)


def _apply_archived_prints_overlay(base_image: Image.Image, data: dict, item: str, zone: str, side: int, color) -> Image.Image:
    """
    Накладывает ранее сохранённые принты (из zone_prints) на макет.
    Используется в редакторе, чтобы показывать предыдущие фото/дизайны при добавлении новых.
    """
    zone_prints = data.get("zone_prints") or {}
    zone_data = zone_prints.get(zone)
    
    if not zone_data:
        return base_image
    
    prints = zone_data.get("prints", [])
    if not prints:
        return base_image
    
    # Получаем маску для обрезки по границам зоны
    zone_mask = _get_zone_mask_for_overlay(item, side, zone, base_image.size)
    
    composed = base_image.copy().convert("RGBA")
    
    for print_data in prints:
        pos = print_data.get("pos", [-1, -1])
        size = print_data.get("size", [0, 0])
        angle_val = print_data.get("angle", 0)
        bg_deleted_val = print_data.get("bg_deleted", False)
        customization = print_data.get("customization", "photo")
        design_id = print_data.get("selected_design_id")
        photo_path = print_data.get("photo_path")
        
        # Пропускаем если позиция не задана
        if not isinstance(pos, list) or pos[0] == -1:
            continue
        
        # Загружаем изображение
        print_image = None
        if customization == "ready" and design_id:
            design = find_design(design_id)
            from services.designs import _build_preview
            design_path = _build_preview(design) if design else None
            if design_path and os.path.exists(design_path):
                print_image = Image.open(design_path)
            elif photo_path and os.path.exists(photo_path):
                print_image = Image.open(photo_path)
        else:
            if photo_path and os.path.exists(photo_path):
                if bg_deleted_val:
                    bg_deleted_path = photo_path.replace(".png", "_nobg.png")
                    if os.path.exists(bg_deleted_path):
                        print_image = Image.open(bg_deleted_path)
                    else:
                        print_image = Image.open(photo_path)
                else:
                    print_image = Image.open(photo_path)
        
        if print_image is None:
            continue
        
        # Если размер не задан, используем исходный
        if not size or size[0] == 0 or size[1] == 0:
            size = list(print_image.size)
        
        # Изменяем размер
        print_image = print_image.resize(tuple(size), Image.Resampling.BICUBIC)
        
        # Поворачиваем если нужно
        if angle_val:
            print_image = print_image.rotate(angle_val, expand=True)
        
        # Создаём слой для принта
        print_image = print_image.convert("RGBA")
        print_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
        print_layer.paste(print_image, tuple(pos), print_image)
        
        # Применяем маску зоны для обрезки
        if zone_mask:
            masked_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
            masked_layer.paste(print_layer, (0, 0), zone_mask)
            print_layer = masked_layer
        
        # Накладываем на макет
        composed = Image.alpha_composite(composed, print_layer)
    
    # Накладываем стикеры из архива
    archived_sticker_items = zone_data.get("sticker_items", [])
    if archived_sticker_items:
        composed = _apply_stickers_to_mockup(composed, archived_sticker_items)
    
    return composed


async def _show_mockup_after_stickers(callback: CallbackQuery, state: FSMContext, reply_markup=None):
    """
    Восстанавливает макет в том же сообщении после работы со стикерами.
    Используется, когда пользователь закончил или отменил выбор стикеров.
    """
    data = await state.get_data()
    user_id = callback.from_user.id
    item = data["order_type"]
    zone = data.get("order_zone", "chest")
    color = data.get("color")
    side = data.get("side", 0)
    print_pos = data.get("pos") or [[-1, -1], [-1, -1]]
    angle = data.get("angle") or [0, 0]
    size = data.get("size") or [[0, 0], [0, 0]]
    bg_deleted = data.get("bg_deleted") or [False, False]
    
    # Путь к фото для текущей зоны
    current_photo_path = data.get("current_zone_photo")

    customization = data.get("customization", "photo")
    if customization == "ready" and data.get("selected_design_id"):
        design = find_design(data["selected_design_id"])
        from services.designs import _build_preview
        design_path = _build_preview(design) if design else None
        if design_path:
            image = Image.open(design_path)
        elif current_photo_path and os.path.exists(current_photo_path):
            image = Image.open(current_photo_path)
        else:
            image = Image.open(f"prints/{user_id}.png")
    else:
        # Используем фото для текущей зоны
        if current_photo_path and os.path.exists(current_photo_path):
            if bg_deleted[side]:
                bg_deleted_path = current_photo_path.replace(".png", "_nobg.png")
                if os.path.exists(bg_deleted_path):
                    image = Image.open(bg_deleted_path)
                else:
                    image = Image.open(current_photo_path)
            else:
                image = Image.open(current_photo_path)
        elif bg_deleted[side] and os.path.exists(f"prints/{user_id}_bg_deleted.png"):
            image = Image.open(f"prints/{user_id}_bg_deleted.png")
        else:
            image = Image.open(f"prints/{user_id}.png")

    if not size[side] or size[side][0] == 0 or size[side][1] == 0:
        size[side] = list(image.size)

    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, side)
    
    # Сначала накладываем архивные принты на пустой шаблон
    base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
    base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
    
    # Затем накладываем текущее фото поверх
    base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
    
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
    """
    Запуск выбора стикеров — сразу показываем категории.
    Стикеры автоматически добавляются на ту же сторону, что и принт/дизайн.
    """
    categories = list_sticker_categories()
    if not categories:
        if isinstance(target, CallbackQuery):
            await target.answer("Стикеры скоро появятся 💛", show_alert=True)
        else:
            await target.answer("Стикеры скоро появятся 💛")
        return

    text = "Выбери категорию стикеров 🐾"
    if isinstance(target, Message):
        await target.answer(text, reply_markup=make_sticker_categories_keyboard(categories).as_markup())
    else:
        # Для callback работаем с текущим сообщением
        try:
            await target.message.edit_caption(caption=text)
            await target.message.edit_reply_markup(
                reply_markup=make_sticker_categories_keyboard(categories).as_markup()
            )
        except TelegramBadRequest:
            pass
    await state.set_state(Order.sticker_category)


async def _show_order_summary(message: Message, state: FSMContext, edit: bool = False):
    """Показывает итоговую информацию о заказе после confirm"""
    data = await state.get_data()
    item = data.get("order_type")
    size_order = data.get("order_size")
    order_label = next((label for label, code in order_types.items() if code == item), "Изделие")
    
    # Получаем все зоны из zone_prints
    zone_prints = data.get("zone_prints") or {}
    all_zones = data.get("all_zones") or list(zone_prints.keys())
    if not all_zones:
        all_zones = [data.get("order_zone", "chest")]
    
    # Формируем текст зон
    zones_text = ", ".join(zone_label(z) for z in all_zones)
    
    # Собираем все стикеры со всех зон — используем sticker_items для точного подсчёта
    stickers_total = 0
    for zp in zone_prints.values():
        # Считаем по sticker_items — это точное количество добавленных стикеров
        zone_sticker_items = zp.get("sticker_items", [])
        stickers_total += len(zone_sticker_items)
    
    # НЕ добавляем current_sticker_items — они уже в zone_prints после confirm
    stickers_text = str(stickers_total) if stickers_total else "0"
    
    # Собираем все типы кастомизации со всех зон
    customization_types = set()
    design_titles = []
    for zp in zone_prints.values():
        # Проверяем сохранённые типы кастомизации
        zone_cust_types = zp.get("customization_types", [])
        for ct in zone_cust_types:
            customization_types.add(ct)
        # Проверяем флаги has_photo и has_design
        if zp.get("has_photo"):
            customization_types.add("photo")
        if zp.get("has_design"):
            customization_types.add("ready")
        # Берём design_titles из нового формата
        zone_design_titles = zp.get("design_titles", [])
        for title in zone_design_titles:
            if title and title not in design_titles:
                design_titles.append(title)
    # Добавляем текущую кастомизацию
    current_cust = data.get("customization")
    if current_cust:
        customization_types.add(current_cust)
    current_design = data.get("selected_design_title")
    if current_design and current_design not in design_titles:
        design_titles.append(current_design)
    
    # Подсчитываем количество фото и дизайнов
    photo_count = 0
    design_count = 0
    for zp in zone_prints.values():
        prints = zp.get("prints", [])
        for p in prints:
            cust = p.get("customization", "photo")
            if cust == "ready":
                design_count += 1
            else:
                photo_count += 1
    
    # Формируем текст кастомизации с количеством
    cust_labels = []
    if photo_count > 0:
        label = "Фото питомца"
        if photo_count > 1:
            label += f" ×{photo_count}"
        cust_labels.append(label)
    if design_count > 0:
        label = "Готовый дизайн AIVADOG"
        if design_count > 1:
            label += f" ×{design_count}"
        cust_labels.append(label)
    customization_text = ", ".join(cust_labels) if cust_labels else "Фото питомца"
    
    pet_name = data.get("pet_name", "—")
    
    order_id = data.get("order_id")
    order_number = data.get("order_number")
    
    summary = (
        f"Заказ #{order_number or order_id}\n\n"
        f"Изделие: {order_label}\n"
        f"Размер: {size_order.upper()}\n"
        f"Зоны нанесения: {zones_text}\n"
        f"Кастомизация: {customization_text}\n"
        f"Имя питомца: {pet_name}\n"
    )
    if design_titles:
        summary += f"Дизайн: {', '.join(design_titles)}\n"
    summary += (
        f"Стикеры: {stickers_text}\n\n"
        "Всё нравится?"
    )
    if edit:
        try:
            await message.edit_text(summary, reply_markup=final_preview_keyboard().as_markup())
        except TelegramBadRequest:
            await message.answer(summary, reply_markup=final_preview_keyboard().as_markup())
    else:
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
    media = InputMediaPhoto(media=file, caption="Листай стикеры и нажми «Готово ✅», чтобы выбрать 🐾")
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
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    codes = data.get("current_sticker_codes") or []
    if not codes:
        await callback.answer("Сначала выбери категорию стикеров", show_alert=True)
        return

    index = int(data.get("current_sticker_index", 0)) % len(codes)

    if callback.data == "sticker_add":
        stickers = list(data.get("stickers", []))
        sticker_items = deepcopy(data.get("sticker_items") or [])
        current_code = codes[index]
        if len(sticker_items) >= 10:
            await callback.answer("Можно добавить не больше 10 стикеров", show_alert=True)
            return
        await _push_edit_snapshot(state)
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
        caption="Листай стикеры и нажми «Готово ✅», чтобы выбрать 🐾",
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


@router.callback_query(F.data == "st_add_new")
async def sticker_add_new(callback: CallbackQuery, state: FSMContext):
    """Добавление нового стикера из меню редактирования — переход к выбору категории."""
    await _start_sticker_flow(callback, state)


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
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    item_code = data.get("order_type")
    template_width, template_height = get_template_bounds(item_code)
    sticker = deepcopy(items[active])
    pos = list(sticker.get("pos") or [0, 0])
    size = list(sticker.get("size") or [100, 100])
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
        await _push_edit_snapshot(state)
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
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    item_code = data.get("order_type")
    template_width, template_height = get_template_bounds(item_code)
    sticker = deepcopy(items[active])
    size = list(sticker.get("size") or [100, 100])
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
        await _push_edit_snapshot(state)
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
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    items = data.get("sticker_items") or []
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    sticker = deepcopy(items[active])
    angle = int(sticker.get("angle", 0))
    if callback.data == "st_rotate_right":
        angle += 270
    else:
        angle += 90
    await _push_edit_snapshot(state)
    sticker["angle"] = angle
    items[active] = sticker
    await state.update_data({"sticker_items": items})
    await _show_mockup_after_stickers(callback, state, reply_markup=make_sticker_rotate_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data == "st_delete")
async def sticker_delete(callback: CallbackQuery, state: FSMContext):
    from keyboards.print_processing_keyboards import make_stickers_manage_keyboard
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    items = deepcopy(data.get("sticker_items") or [])
    active = data.get("active_sticker_index")
    if active is None or not (0 <= active < len(items)):
        await callback.answer("Сначала выбери стикер", show_alert=True)
        return
    # Удаляем инстанс и одну запись кода из summary списков (первое вхождение)
    await _push_edit_snapshot(state)
    sticker_code = items[active].get("code")
    items.pop(active)
    codes = list(data.get("stickers") or [])
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
    """
    Возвращаемся назад из выбора стикеров.
    Если мы в категориях — возвращаемся к макету.
    Если мы в просмотре стикеров — возвращаемся к категориям.
    """
    current_state = await state.get_state()
    # Если мы на этапе выбора категорий — возвращаемся к макету
    if current_state == Order.sticker_category.state:
        await _show_mockup_after_stickers(callback, state)
        await callback.answer()
        return
    # Если мы на этапе выбора стикера — возвращаемся к категориям
    await _start_sticker_flow(callback, state)


@router.callback_query(F.data == "stickers_cancel")
async def stickers_cancel(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    await _push_edit_snapshot(state)
    await state.update_data({"stickers": [], "sticker_items": [], "active_sticker_index": None, "stickers_planned": False})
    # Отмена — возвращаем макет и настройки в том же сообщении
    await _show_mockup_after_stickers(callback, state)
    await callback.answer("Вернулись к макету. Стикеры очищены.", show_alert=False)


@router.callback_query(F.data == "settings_back")
async def settings_back(callback: CallbackQuery, state: FSMContext):
    await state.update_data({"edit_history": None})
    await callback.message.edit_reply_markup(reply_markup=confirm_or_setting_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data == "settings")
async def print_settings(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    await callback.message.edit_reply_markup(reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data == "reset_edit")
async def reset_edit(callback: CallbackQuery, state: FSMContext):
    restored = await _restore_edit_snapshot(state)
    if not restored:
        await callback.answer("Нет изменений для отката", show_alert=True)
        return
    from keyboards.print_processing_keyboards import make_settings_keyboard

    await _show_mockup_after_stickers(
        callback,
        state,
        reply_markup=make_settings_keyboard().as_markup(),
    )
    await callback.answer("Изменения отменены", show_alert=False)


@router.callback_query(F.data == "delete_bg")
async def remove_print_bg(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    user_id = callback.from_user.id
    current_photo_path = data.get("current_zone_photo")
    
    # Загружаем оригинальное фото
    if current_photo_path and os.path.exists(current_photo_path):
        image = Image.open(current_photo_path)
    else:
        image = Image.open(f"prints/{user_id}.png")
    
    item = data["order_type"]
    color = data.get("color")
    side = data["side"]
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    bg_deleted = data["bg_deleted"]
    if bg_deleted[side]:
        await callback.answer("Фон уже удален!")
    else:
        await _push_edit_snapshot(state)
        bg_deleted[side] = True
        await state.update_data({"bg_deleted": bg_deleted})
        image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
        image = print_remove_bg(image)
        
        # Сохраняем версию без фона рядом с оригиналом
        if current_photo_path:
            bg_deleted_path = current_photo_path.replace(".png", "_nobg.png")
        else:
            bg_deleted_path = f"prints/{user_id}_bg_deleted.png"
        image.save(bg_deleted_path, "PNG")
        
        zone = data.get("order_zone", "chest")
        template_override = _get_template_override_path(data, side)
        
        # Сначала архивные, потом текущее фото
        base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
        data = await state.get_data()
        base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
        base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
        file = InputMediaPhoto(media=file)
        await callback.message.edit_media(file, reply_markup=make_remove_bg_keyboard().as_markup())


@router.callback_query(F.data == "restore_bg")
async def restore_print_bg(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    user_id = callback.from_user.id
    current_photo_path = data.get("current_zone_photo")
    
    # Загружаем оригинальное фото (без удалённого фона)
    if current_photo_path and os.path.exists(current_photo_path):
        image = Image.open(current_photo_path)
    else:
        image = Image.open(f"prints/{user_id}.png")
    
    item = data["order_type"]
    color = data.get("color")
    side = data["side"]
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    bg_deleted = data["bg_deleted"]
    bg_deleted[side] = False
    await _push_edit_snapshot(state)
    await state.update_data({"bg_deleted": bg_deleted})
    zone = data.get("order_zone", "chest")
    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, side)
    
    # Сначала архивные, потом текущее фото
    base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
    data = await state.get_data()
    base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
    base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
    file = InputMediaPhoto(media=file)
    await callback.message.edit_media(file, reply_markup=make_settings_keyboard().as_markup())


@router.callback_query(F.data == "change_size")
async def print_size_main(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    await callback.message.edit_reply_markup(reply_markup=make_print_size_keyboard().as_markup())


@router.callback_query(F.data.in_({"decrease_size", "increase_size"}))
async def print_size(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    
    try:
        image = _load_user_photo(user_id, data, side, for_bg_deleted=bg_deleted[side])
    except FileNotFoundError:
        await callback.answer("Фото не найдено", show_alert=True)
        return
    
    item = data["order_type"]
    zone = data.get("order_zone", "chest")
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    x_size = size[side][0]
    y_size = size[side][1]
    
    # Получаем границы для размещения принта
    x_min, y_min, x_max, y_max = _get_zone_mask_bbox(item, side, zone)
    max_width = max(1, x_max - x_min)
    max_height = max(1, y_max - y_min)
    
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
        new_width = int(x_size * increase_k)
        new_height = int(y_size * increase_k)
        # Проверяем, что новый размер помещается в границы
        if new_width < max_width and new_height < max_height:
            new_size = (new_width, new_height)
            # Корректируем позицию, если принт выходит за границы
            size_changed = True
        else:
            await callback.answer("Достигнут максимум разрешения изображения")
    if size_changed:
        await _push_edit_snapshot(state)
        size[side] = new_size
        print_pos[side] = _clamp_position_with_mask(
            print_pos[side][0],
            print_pos[side][1],
            size[side][0],
            size[side][1],
            item,
            side,
            zone,
        )
        image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
        template_override = _get_template_override_path(data, side)
        
        # Сначала архивные, потом текущее фото
        base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
        data = await state.get_data()
        base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
        base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
        await state.update_data({"size": size, "pos": print_pos})
        file = InputMediaPhoto(media=file)
        await callback.message.edit_media(file, reply_markup=make_print_size_keyboard().as_markup())


@router.callback_query(F.data == "move_print")
async def move_print_main(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    await callback.message.edit_reply_markup(reply_markup=make_move_print_keyboard().as_markup())


@router.callback_query(F.data.in_({"move_up", "move_down", "move_right", "move_left", "move_centre"}))
async def move_print(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    
    try:
        image = _load_user_photo(user_id, data, side, for_bg_deleted=bg_deleted[side])
    except FileNotFoundError:
        await callback.answer("Фото не найдено", show_alert=True)
        return
    
    item = data["order_type"]
    zone = data.get("order_zone", "chest")
    color = data.get("color")
    print_pos = deepcopy(data.get("pos") or [[-1, -1], [-1, -1]])
    angle = list(data.get("angle") or [0, 0])
    size = deepcopy(data.get("size") or [[0, 0], [0, 0]])
    
    current_pos = print_pos[side]
    if not isinstance(current_pos, list) or current_pos[0] == -1:
        await callback.answer("Нет активного принта", show_alert=True)
        return
    target_pos = current_pos
    if callback.data == "move_right":
        candidate = _clamp_position_with_mask(
            current_pos[0] + size_step,
            current_pos[1],
            size[side][0],
            size[side][1],
            item,
            side,
            zone,
        )
        if candidate == current_pos:
            await callback.answer("Достигнут максимум сдвига вправо")
            return
        target_pos = candidate
    elif callback.data == "move_left":
        candidate = _clamp_position_with_mask(
            current_pos[0] - size_step,
            current_pos[1],
            size[side][0],
            size[side][1],
            item,
            side,
            zone,
        )
        if candidate == current_pos:
            await callback.answer("Достигнут максимум сдвига влево")
            return
        target_pos = candidate
    elif callback.data == "move_up":
        candidate = _clamp_position_with_mask(
            current_pos[0],
            current_pos[1] - size_step,
            size[side][0],
            size[side][1],
            item,
            side,
            zone,
        )
        if candidate == current_pos:
            await callback.answer("Достигнут максимум сдвига вверх")
            return
        target_pos = candidate
    elif callback.data == "move_down":
        candidate = _clamp_position_with_mask(
            current_pos[0],
            current_pos[1] + size_step,
            size[side][0],
            size[side][1],
            item,
            side,
            zone,
        )
        if candidate == current_pos:
            await callback.answer("Достигнут максимум сдвига вниз")
            return
        target_pos = candidate
    elif callback.data == "move_centre":
        rotations = angle[side] % 180
        effective_width = size[side][0] if rotations == 0 else size[side][1]
        effective_height = size[side][1] if rotations == 0 else size[side][0]
        candidate = _get_centered_position_in_zone(
            item, side, zone, effective_width, effective_height
        )
        if candidate == current_pos:
            await callback.answer("Изображение находится в центре")
            return
        target_pos = candidate
    else:
        await callback.answer()
        return

    await _push_edit_snapshot(state)
    print_pos[side] = list(target_pos)

    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, side)

    # Сначала архивные, потом текущее фото
    base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
    data = await state.get_data()
    base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
    base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
    await state.update_data({"pos": print_pos})
    file = InputMediaPhoto(media=file)
    try:
        await callback.message.edit_media(file, reply_markup=make_move_print_keyboard().as_markup())
    except TelegramBadRequest:
        await callback.answer("Изображение находится в центре")
    else:
        await callback.answer()


@router.callback_query(F.data == "rotate_print")
async def rotate_print_main(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    await callback.message.edit_reply_markup(reply_markup=make_rotate_keyboard().as_markup())


@router.callback_query(F.data.in_({"rotate_right", "rotate_left"}))
async def rotate_print(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    side = data["side"]
    
    try:
        image = _load_user_photo(user_id, data, side, for_bg_deleted=bg_deleted[side])
    except FileNotFoundError:
        await callback.answer("Фото не найдено", show_alert=True)
        return
    
    item = data["order_type"]
    color = data.get("color")
    print_pos = deepcopy(data.get("pos") or [[-1, -1], [-1, -1]])
    angle = list(data.get("angle") or [0, 0])
    size = deepcopy(data.get("size") or [[0, 0], [0, 0]])
    await _push_edit_snapshot(state)
    if callback.data == "rotate_right":
        angle[side] = angle[side] + 270
    else:
        angle[side] = angle[side] + 90
    zone = data.get("order_zone", "chest")
    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, side)
    
    # Сначала архивные, потом текущее фото
    base = paste(None, color, "deleted", item, side, 0, False, zone, template_override=template_override)
    data = await state.get_data()
    base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
    base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, zone)
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
    await state.update_data({"angle": angle})
    file = InputMediaPhoto(media=file)
    await callback.message.edit_media(file, reply_markup=make_rotate_keyboard().as_markup())


@router.callback_query(F.data == "change_side")
async def change_side(callback: CallbackQuery, state: FSMContext):
    """
    Вместо простого переключения front/back показываем выбор стороны/зоны
    в зависимости от типа изделия (худи, свитшот, футболка и т.п.).
    """
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    item = data.get("order_type")
    if not item:
        await callback.answer()
        return
    base_item = get_base_item(item)
    zones = zone_schemes.get(base_item)
    # Если для изделия нет схемы зон — оставляем старое поведение (front/back)
    if not zones:
        await callback.answer()
        return

    current_zone = data.get("order_zone", "chest")
    builder = InlineKeyboardBuilder()
    for title, code in zones:
        if code == current_zone:
            continue
        builder.add(
            InlineKeyboardButton(
                text=title,
                callback_data=f"side_zone_{code}",
            )
        )
    builder.add(
        InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="settings",
        )
    )
    builder.adjust(2, 2)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()


def _zone_to_side(zone: str) -> int:
    """
    Маппинг зоны на индекс стороны:
    - грудь -> 0
    - спина -> 1
    - штаны: pant_back_* -> 1, остальные -> 0
    - остальные зоны считаем отдельными макетами, используем 0
    """
    if zone == "back" or zone in ("pant_back_left", "pant_back_right"):
        return 1
    return 0


@router.callback_query(F.data.startswith("side_zone_"))
async def change_side_zone(callback: CallbackQuery, state: FSMContext):
    """
    Переключение на другую сторону/зону из настроек.
    Пересчитываем позицию и показываем новый макет.
    """
    await _ensure_edit_snapshot(state)
    new_zone = callback.data.replace("side_zone_", "")
    data = await state.get_data()
    user_id = callback.from_user.id
    item = data["order_type"]
    color = data.get("color")
    bg_deleted = list(data.get("bg_deleted") or [False, False])
    print_pos = deepcopy(data.get("pos") or [[-1, -1], [-1, -1]])
    angle = list(data.get("angle") or [0, 0])
    size = deepcopy(data.get("size") or [[0, 0], [0, 0]])

    # Сторона, с которой мы уходим
    old_side = data.get("side", 0)
    # Новая сторона для выбранной зоны (грудь/спина/остальные)
    side = _zone_to_side(new_zone)

    await _push_edit_snapshot(state)

    # Отключаем принт на старой стороне, если он там был
    if isinstance(print_pos[old_side], list):
        print_pos[old_side] = "deleted"

    # Открываем исходное изображение пользователя / дизайн
    try:
        image = _load_user_photo(user_id, data, side, for_bg_deleted=bg_deleted[side])
    except FileNotFoundError:
        await callback.answer("Фото не найдено", show_alert=True)
        return

    # Если ещё нет размера для этой стороны — берём размеры исходника
    if not size[side] or size[side][0] == 0 or size[side][1] == 0:
        size[side] = list(image.size)

    pos = _get_centered_position_in_zone(
        item,
        side,
        new_zone,
        size[side][0],
        size[side][1],
    )
    print_pos[side] = pos
    angle[side] = 0

    image = image.resize(tuple(size[side]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, side)
    
    # Сначала архивные, потом текущее фото
    base = paste(None, color, "deleted", item, side, 0, False, new_zone, template_override=template_override)
    data = await state.get_data()
    base = _apply_archived_prints_overlay(base, data, item, new_zone, side, color)
    base = _overlay_current_print(base, image, print_pos[side], angle[side], item, side, new_zone)
    base = _apply_stickers_overlay(base, data, side)
    file = image_to_bytes(base)
    media = InputMediaPhoto(media=file)
    await state.update_data(
        {
            "order_zone": new_zone,
            "pos": print_pos,
            "side": side,
            "angle": angle,
            "size": size,
        }
    )
    await callback.message.edit_media(media, reply_markup=make_settings_keyboard().as_markup())
    await callback.answer()


@router.callback_query(F.data == "delete_print")
async def delete_print(callback: CallbackQuery, state: FSMContext):
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    item = data["order_type"]
    color = data.get("color")
    side = data["side"]
    print_pos = deepcopy(data.get("pos") or [[-1, -1], [-1, -1]])
    bg_deleted = list(data.get("bg_deleted") or [False, False])
    angle = list(data.get("angle") or [0, 0])
    if print_pos[side] == "deleted":
        await callback.answer("Нечего удалять!")
    else:
        await _push_edit_snapshot(state)
        print_pos[side] = "deleted"
        zone = data.get("order_zone", "chest")
        template_override = _get_template_override_path(data, side)
        base = paste(None, color, print_pos[side], item, side, angle[side], bg_deleted[side], zone, template_override=template_override)
        data = await state.get_data()
        base = _apply_archived_prints_overlay(base, data, item, zone, side, color)
        base = _apply_stickers_overlay(base, data, side)
        file = image_to_bytes(base)
        file = InputMediaPhoto(media=file)
        await state.update_data({"pos": print_pos})
        await callback.message.edit_media(file, reply_markup=make_settings_keyboard().as_markup())


def _generate_zone_mockup(user_id: int, item: str, zone: str, zone_data: dict, color) -> Image.Image:
    """
    Генерирует макет для одной зоны на основе сохранённых данных.
    Поддерживает несколько принтов на одной зоне.
    Использует маски для обрезки по границам зоны.
    """
    side = zone_data.get("side", 0)
    sticker_items = zone_data.get("sticker_items", [])
    
    # Новый формат: список принтов
    prints = zone_data.get("prints", [])
    
    # Если нет принтов в новом формате, проверяем старый формат (для совместимости)
    if not prints:
        pos = zone_data.get("pos", [-1, -1])
        size = zone_data.get("size", [0, 0])
        angle_val = zone_data.get("angle", 0)
        bg_deleted_val = zone_data.get("bg_deleted", False)
        customization = zone_data.get("customization", "photo")
        design_id = zone_data.get("selected_design_id")
        zone_photo_path = zone_data.get("photo_path")
        
        if isinstance(pos, list) and pos[0] != -1:
            prints = [{
                "pos": pos,
                "size": size,
                "angle": angle_val,
                "bg_deleted": bg_deleted_val,
                "customization": customization,
                "photo_path": zone_photo_path,
                "selected_design_id": design_id,
            }]
    
    # Начинаем с пустого шаблона
    mockup = paste(None, color, "deleted", item, side, 0, False, zone, template_override=None)
    
    # Получаем маску для обрезки по границам зоны
    zone_mask = _get_zone_mask_for_overlay(item, side, zone, mockup.size)
    
    # Накладываем каждый принт
    for print_data in prints:
        pos = print_data.get("pos", [-1, -1])
        size = print_data.get("size", [0, 0])
        angle_val = print_data.get("angle", 0)
        bg_deleted_val = print_data.get("bg_deleted", False)
        customization = print_data.get("customization", "photo")
        design_id = print_data.get("selected_design_id")
        photo_path = print_data.get("photo_path")
        
        # Пропускаем если позиция не задана
        if not isinstance(pos, list) or pos[0] == -1:
            continue
        
        # Загружаем изображение
        print_image = None
        if customization == "ready" and design_id:
            design = find_design(design_id)
            from services.designs import _build_preview
            design_path = _build_preview(design) if design else None
            if design_path and os.path.exists(design_path):
                print_image = Image.open(design_path)
            elif photo_path and os.path.exists(photo_path):
                print_image = Image.open(photo_path)
        else:
            if photo_path and os.path.exists(photo_path):
                if bg_deleted_val:
                    bg_deleted_path = photo_path.replace(".png", "_nobg.png")
                    if os.path.exists(bg_deleted_path):
                        print_image = Image.open(bg_deleted_path)
                    else:
                        print_image = Image.open(photo_path)
                else:
                    print_image = Image.open(photo_path)
        
        if print_image is None:
            continue
        
        # Если размер не задан, используем исходный
        if not size or size[0] == 0 or size[1] == 0:
            size = list(print_image.size)
        
        # Изменяем размер
        print_image = print_image.resize(tuple(size), Image.Resampling.BICUBIC)
        
        # Поворачиваем если нужно
        if angle_val:
            print_image = print_image.rotate(angle_val, expand=True)
        
        # Создаём слой для принта
        print_image = print_image.convert("RGBA")
        print_layer = Image.new("RGBA", mockup.size, (0, 0, 0, 0))
        print_layer.paste(print_image, tuple(pos), print_image)
        
        # Применяем маску зоны для обрезки
        if zone_mask:
            masked_layer = Image.new("RGBA", mockup.size, (0, 0, 0, 0))
            masked_layer.paste(print_layer, (0, 0), zone_mask)
            print_layer = masked_layer
        
        # Накладываем на макет
        mockup = Image.alpha_composite(mockup.convert("RGBA"), print_layer)
    
    # Накладываем стикеры для этой зоны
    if sticker_items:
        mockup = _apply_stickers_to_mockup(mockup, sticker_items)
    
    return mockup


def _apply_stickers_to_mockup(base_image: Image.Image, sticker_items: list) -> Image.Image:
    """
    Накладывает стикеры на макет.
    """
    if not sticker_items:
        return base_image
    composed = base_image.copy()
    width, height = composed.size
    for item in sticker_items:
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
        x = max(0, min(pos[0], width - 1))
        y = max(0, min(pos[1], height - 1))
        composed.paste(sticker, (x, y), sticker)
    return composed


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
    
    current_zone = data.get("order_zone", "chest")
    customization = data.get("customization", "photo")
    sticker_items = data.get("sticker_items") or []
    
    # Собираем все зоны: архивированные + текущая
    zone_prints = dict(data.get("zone_prints") or {})
    
    # Проверяем, есть ли что-то в текущей зоне
    has_current_print = isinstance(print_pos[side], list) and print_pos[side][0] != -1
    has_current_stickers = bool(sticker_items)
    
    # Проверяем, был ли текущий принт уже архивирован (через "Хочу ещё выбрать принт")
    current_print_archived = data.get("current_print_archived", False)
    
    if has_current_print or has_current_stickers:
        # Получаем существующие данные для этой зоны
        existing_zone_data = zone_prints.get(current_zone, {})
        existing_prints = existing_zone_data.get("prints", [])
        existing_sticker_items = existing_zone_data.get("sticker_items", [])
        
        # Текущие стикеры для этой стороны (добавляем только если не архивированы)
        if not current_print_archived:
            current_sticker_items = [item for item in sticker_items if item.get("side", 0) == side]
            combined_sticker_items = existing_sticker_items + current_sticker_items
        else:
            combined_sticker_items = existing_sticker_items
        
        # Создаём запись о текущем принте (только если не был архивирован)
        if has_current_print and not current_print_archived:
            current_print = {
                "pos": print_pos[side],
                "size": size[side],
                "angle": angle[side],
                "bg_deleted": bg_deleted[side],
                "customization": customization,
                "photo_path": data.get("current_zone_photo"),
                "selected_design_id": data.get("selected_design_id"),
                "selected_design_title": data.get("selected_design_title"),
            }
            combined_prints = existing_prints + [current_print]
        else:
            combined_prints = existing_prints
        
        # Собираем все типы кастомизации
        customization_types = set()
        design_titles = []
        for p in combined_prints:
            if p.get("customization"):
                customization_types.add(p["customization"])
            title = p.get("selected_design_title")
            if title and title not in design_titles:
                design_titles.append(title)
        
        zone_prints[current_zone] = {
            "side": side,
            "prints": combined_prints,
            "sticker_items": combined_sticker_items,
            "customization_types": list(customization_types),
            "design_titles": design_titles,
            "has_photo": any(p.get("customization") in ("photo", "stickers") for p in combined_prints),
            "has_design": any(p.get("customization") == "ready" for p in combined_prints),
        }
    
    # Если нет ни одной зоны — показываем пустой макет текущей зоны
    if not zone_prints:
        zone_prints[current_zone] = {
            "side": side,
            "prints": [],
            "sticker_items": [],
            "customization_types": [],
            "design_titles": [],
            "has_photo": False,
            "has_design": False,
        }
    
    # Сохраняем все зоны и помечаем текущий принт как архивированный,
    # чтобы _archive_current_print не добавлял его повторно при preview_more
    await state.update_data(
        {
            "zone_prints": zone_prints,
            "current_print_archived": True,
            "edit_history": None,
        }
    )
    
    # Генерируем макеты для каждой зоны
    media_files = []
    zone_file_ids = {}
    zone_paths = {}
    
    for zone_code, zone_data in zone_prints.items():
        mockup = _generate_zone_mockup(user_id, item, zone_code, zone_data, color)
        
        # Сохраняем макет
        path = f"prints/{user_id}_zone_{zone_code}.png"
        mockup.save(path, "PNG")
        zone_paths[zone_code] = path
        
        # Добавляем в список для отправки
        media_files.append(InputMediaPhoto(media=image_to_bytes(mockup)))
    
    await callback.message.delete()
    
    # Удаляем предыдущие сообщения альбома
    try:
        album_id = data.get("album_id")
        chat_id = data["chat_id"]
        if album_id and album_id != -1:
            # Пытаемся удалить несколько сообщений (максимум 10 для альбома)
            for i in range(10):
                try:
                    await callback.bot.delete_message(chat_id=chat_id, message_id=(album_id + i))
                except Exception:
                    break
    except KeyError:
        pass
    
    # Отправляем фото
    if len(media_files) == 1:
        sent_msg = await callback.message.answer_photo(media_files[0].media)
        zone_code = list(zone_prints.keys())[0]
        zone_file_ids[zone_code] = sent_msg.photo[-1].file_id
        await state.update_data({
            "album_id": sent_msg.message_id,
            "zone_file_ids": zone_file_ids,
            "zone_paths": zone_paths,
        })
    else:
        media_group = await callback.message.answer_media_group(media_files)
        for idx, zone_code in enumerate(zone_prints.keys()):
            zone_file_ids[zone_code] = media_group[idx].photo[-1].file_id
        await state.update_data({
            "album_id": media_group[0].message_id,
            "zone_file_ids": zone_file_ids,
            "zone_paths": zone_paths,
        })
    
    # Очищаем текущие стикеры после сохранения в zone_prints
    await state.update_data({"sticker_items": [], "stickers": []})
    
    # После нажатия «Продолжить» спрашиваем имя питомца (если ещё не задано)
    # Для варианта "ready" (готовый дизайн) спрашиваем имя здесь
    if not data.get("pet_name") and data.get("customization") == "ready":
        await callback.message.answer("Фото принято ✅\nКак зовут твоего хвостика?", disable_notification=True)
        await state.set_state(Order.pet_name)
        return
    
    # Собираем все зоны для отображения
    all_zones = list(zone_prints.keys())
    zones_text = ", ".join(zone_label(z) for z in all_zones)
    
    # Собираем все стикеры со всех зон
    all_stickers = []
    for zp in zone_prints.values():
        all_stickers.extend(zp.get("stickers", []))
    
    order_label = next((label for label, code in order_types.items() if code == item), "Изделие")
    titles_map = {code: text for text, code in sticker_catalog}
    stickers_text = ", ".join(titles_map.get(code, code) for code in all_stickers) if all_stickers else "Без стикеров"
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
    notes = {
        "zone_prints": {z: {"stickers": zp.get("stickers", [])} for z, zp in zone_prints.items()}
    }
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
            zone=zones_text,  # Сохраняем все зоны
            customization=customization_code,
            stickers=all_stickers,
            sticker_zone=None,
            pet_name=pet_name,
            notes=notes,
        )
        await state.update_data({"order_id": order_id, "order_number": order_number, "all_zones": all_zones})
    else:
        order_number = data.get("order_number")
        storage.update_order(
            order_id,
            item_code=item,
            size=size_order.upper(),
            zone=zones_text,  # Сохраняем все зоны
            customization=customization_code,
            stickers=json.dumps(all_stickers, ensure_ascii=False),
            sticker_zone=None,
            pet_name=pet_name,
        )
        # Обновляем / очищаем данные о готовом дизайне в notes_json:
        # если макет снят, в БД не должно оставаться старой записи.
        storage.update_order_notes(
            order_id,
            ready_design_id=design_id,
            ready_design_title=design_title,
        )
        await state.update_data({"all_zones": all_zones})
    # Сохраняем превью (первую зону как front_id для совместимости)
    first_zone_id = zone_file_ids.get(list(zone_prints.keys())[0]) if zone_file_ids else None
    storage.attach_preview(order_id, first_zone_id, None)
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
    # Собираем все названия дизайнов из всех зон
    zone_prints = data.get("zone_prints") or {}
    all_design_titles = []
    for zp in zone_prints.values():
        zone_titles = zp.get("design_titles", [])
        for title in zone_titles:
            if title and title not in all_design_titles:
                all_design_titles.append(title)
    # Также добавляем текущий дизайн если он есть
    current_design = data.get("selected_design_title")
    if current_design and current_design not in all_design_titles:
        all_design_titles.append(current_design)
    
    if all_design_titles:
        text = f"Выбранный дизайн: {', '.join(all_design_titles)}\n\n" + text
    if reward:
        text += "\n\nСкидка по твоей ссылке уже применена 💛"
    # Редактируем текущее сообщение вместо отправки нового
    try:
        await callback.message.edit_text(text, reply_markup=checkout_or_edit_keyboard().as_markup())
    except TelegramBadRequest:
        # Если не удалось отредактировать — отправляем новое
        await callback.message.answer(text, reply_markup=checkout_or_edit_keyboard().as_markup())
    await state.set_state(Order.price)


@router.callback_query(F.data == "preview_designer")
async def preview_designer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_number = data.get("order_number", "—")
    
    # Собираем все зоны
    zone_prints = data.get("zone_prints") or {}
    all_zones = data.get("all_zones") or list(zone_prints.keys())
    zones_text = ", ".join(zone_label(z) for z in all_zones) if all_zones else "—"
    
    text = (
        f"Новая заявка на доработку #{order_number}\n"
        f"Изделие: {next((label for label, code in order_types.items() if code == data.get('order_type')), '—')}\n"
        f"Размер: {data.get('order_size', '').upper()}\n"
        f"Зоны: {zones_text}\n"
        f"Имя питомца: {data.get('pet_name', '—')}"
    )
    
    # Получаем file_id для всех зон (макеты)
    zone_file_ids = data.get("zone_file_ids") or {}
    user_id = callback.from_user.id
    
    media = []
    # Добавляем макеты для каждой зоны
    for zone_code, file_id in zone_file_ids.items():
        if file_id:
            media.append(InputMediaPhoto(media=file_id, caption=f"Макет: {zone_label(zone_code)}"))
    
    # Собираем ВСЕ фото из нового формата prints
    added_photos = set()  # Чтобы не добавлять одно фото дважды
    for zone_code, zone_data in zone_prints.items():
        prints = zone_data.get("prints", [])
        for i, p in enumerate(prints):
            photo_path = p.get("photo_path")
            if photo_path and os.path.exists(photo_path) and photo_path not in added_photos:
                user_photo = FSInputFile(photo_path)
                cust = p.get("customization", "photo")
                label = "Фото" if cust != "ready" else "Для дизайна"
                media.append(InputMediaPhoto(media=user_photo, caption=f"{label}: {zone_label(zone_code)} #{i+1}"))
                added_photos.add(photo_path)
        
    if media:
        await callback.bot.send_message(ADMIN_ID, text)
        await callback.bot.send_media_group(ADMIN_ID, media)
    else:
        await callback.bot.send_message(ADMIN_ID, text)

    # Редактируем текущее сообщение, показывая что заявка отправлена
    try:
        current_text = callback.message.text or ""
        new_text = current_text + "\n\n✅ Заявка дизайнеру отправлена!"
        await callback.message.edit_text(new_text, reply_markup=final_preview_keyboard().as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer("Сообщение дизайнеру отправлено 💬", show_alert=True)


@router.callback_query(F.data == "preview_more")
async def preview_more(callback: CallbackQuery, state: FSMContext):
    await _archive_current_print(state)
    data = await state.get_data()
    zones = zone_schemes.get(get_base_item(data.get("order_type")), zone_schemes["shirt"])
    await state.update_data({"zone_return": "preview"})
    # Редактируем текущее сообщение вместо отправки нового
    try:
        await callback.message.edit_text("Выбери новую зону нанесения 👇", reply_markup=make_zone_keyboard(zones).as_markup())
    except TelegramBadRequest:
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
    # Редактируем текущее сообщение с информацией о реферальной ссылке
    try:
        current_text = callback.message.text or ""
        new_text = (
            current_text + "\n\n"
            "🔗 Поделись ссылкой и получи −3% за каждого друга:\n"
            f"{link}\n\nСкидка активна 48 часов после первого перехода."
        )
        await callback.message.edit_text(new_text, reply_markup=final_preview_keyboard().as_markup())
    except TelegramBadRequest:
        await callback.message.answer(
            "Поделись ссылкой и получи −3% за каждого друга, который начнёт заказ:\n"
            f"{link}\n\nСкидка активна 48 часов после первого перехода."
        )
    await callback.answer()


@router.callback_query(F.data == "edit")
async def edit_order(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=edit_keyboard().as_markup())


@router.callback_query(F.data == "back_to_preview")
async def back_to_preview(callback: CallbackQuery, state: FSMContext):
    """Возврат к финальному превью с кнопками (Хочу ещё выбрать принт и т.д.)"""
    await _show_order_summary(callback.message, state, edit=True)
    await callback.answer()


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
    await _ensure_edit_snapshot(state)
    data = await state.get_data()
    user_id = callback.from_user.id
    bg_deleted = data["bg_deleted"]
    
    try:
        image = _load_user_photo(user_id, data, 0, for_bg_deleted=bg_deleted[0])
    except FileNotFoundError:
        await callback.answer("Фото не найдено", show_alert=True)
        return
    
    item = data["order_type"]
    color = data.get("color")
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    zone = data.get("order_zone", "chest")
    image1 = image.resize(tuple(size[0]), Image.Resampling.BICUBIC)
    template_override = _get_template_override_path(data, 0)
    
    # Сначала архивные, потом текущее фото
    base_front = paste(None, color, "deleted", item, 0, 0, False, zone, template_override=template_override)
    base_front = _apply_archived_prints_overlay(base_front, data, item, zone, 0, color)
    base_front = _overlay_current_print(base_front, image1, print_pos[0], angle[0], item, 0, zone)
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
    await _ensure_edit_snapshot(state)
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
