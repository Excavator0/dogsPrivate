import os
import time

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.utils.deep_linking import create_start_link

import keyboards.order_keyboards
from image_processing import *
from keyboards.confirmation_keyboards import *
from keyboards.order_keyboards import *
from keyboards.print_processing_keyboards import *

router = Router()
order_types = {"Футболка": "shirt", "Флаг": "flag", "Стакан": "cup", "Рюкзак": "bag", "Кепка": "cap"}
template_sizes = {"shirt": (1099, 1389), "flag": (1653, 2339), "cup": (1653, 2339), "bag": (1653, 2339),
                  "cap": (1653, 2339)}
sizes = ["XS", "S", "M", "L", "XL", "2XL", "One size"]
size_step = 50
colors = {"black": (20, 20, 20), "white": (232, 232, 232), "red": (176, 37, 37), "yellow": (224, 208, 58),
          "blue": (24, 54, 122), "magenta": (104, 31, 135)}
print_actions = ["Далее", "Удалить фон", "Изменить размер", "Сдвинуть", "Сменить сторону"]


class Order(StatesGroup):
    order_type = State()
    order_size = State()
    color = State()
    color_approval = State()
    image_sent = State()
    bg_deleted = State()
    pos = State()
    side = State()
    angle = State()
    size = State()
    album_id = State()
    chat_id = State()
    front_id = State()
    back_id = State()


@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    # path = "prints/"
    # now = time.time()
    #
    # for filename in os.listdir(path):
    #     filestamp = os.stat(os.path.join(path, filename)).st_mtime
    #     seven_days_ago = now - 7 * 86400
    #     if filestamp < seven_days_ago:
    #         os.remove(f"{path}/{filename}")

    chat_id = message.chat.id
    await message.answer(
        text='<b>Привет!</b>\nДобро пожаловать в бота по заказу принтов!\n\n'
             '<b>Выбери изделие, на которое хочешь нанести принт</b>',
        reply_markup=make_type_keyboard(order_types).as_markup()
    )
    await state.update_data({"chat_id": chat_id})
    await state.set_state(Order.order_type)


@router.message(CommandStart(deep_link=True))
async def start_with_link(message: Message, command: CommandObject, state: FSMContext):
    item = command.args
    await state.update_data({"order_type": item, "pos": [[-1, -1], [-1, -1]]})
    await state.update_data({"side": 0})
    order_type = ""
    for name, code in order_types.items():
        if code == item:
            order_type = name
    if item == "cap" or item == "cup" or item == "flag" or item == "bag":
        await message.answer(text=f"Товар: {order_type}\nТеперь, выберите размер изделия",
                             reply_markup=make_sizes_keyboard([sizes[-1]]).as_markup())
    else:
        await message.answer(text=f"Товар: {order_type}\nТеперь, выберите размер изделия",
                             reply_markup=make_sizes_keyboard(sizes[:-1]).as_markup())
    await state.set_state(Order.order_size)


@router.callback_query(F.data.in_(set(order_types.values())))
async def order_size(callback: CallbackQuery, state: FSMContext):
    item = callback.data
    await state.update_data({"order_type": item, "pos": [[-1, -1], [-1, -1]]})
    await state.update_data({"side": 0})
    if item == "cap" or item == "cup" or item == "flag" or item == "bag":
        await callback.message.edit_text(text="Теперь, выберите размер изделия")
        await callback.message.edit_reply_markup(
            reply_markup=make_sizes_keyboard([sizes[-1]]).as_markup()
        )
    else:
        await callback.message.edit_text(text="Теперь, выберите размер изделия")
        await callback.message.edit_reply_markup(
            reply_markup=make_sizes_keyboard(sizes[:-1]).as_markup()
        )
    await state.set_state(Order.order_size)


@router.callback_query(F.data.in_({size.lower() for size in sizes} | {"change_color"}))
async def order_color(callback: CallbackQuery, state: FSMContext):
    if callback.data != "change_color":
        size = callback.data
        await state.update_data({"order_size": size})
        await callback.message.edit_text(text="Выберите цвет изделия")
        await callback.message.edit_reply_markup(
            reply_markup=make_colors_keyboard().as_markup()
        )
        await state.set_state(Order.color)
    else:
        await callback.message.edit_reply_markup(
            reply_markup=make_colors_keyboard().as_markup()
        )


@router.callback_query(F.data.in_(set(keyboards.order_keyboards.colors.values())))
async def show_color(callback: CallbackQuery, state: FSMContext):
    color = colors.get(callback.data)
    await state.update_data({"color": color})
    data = await state.get_data()
    item = data["order_type"]
    template = paste(None, color, None, item, 0, None, None)
    file = image_to_bytes(template)
    await callback.message.delete()
    await callback.message.answer_photo(file, "", reply_markup=make_color_confirm_keyboard().as_markup())
    await state.set_state(Order.color_approval)


@router.callback_query(F.data == "getting_print")
async def ask_color(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer(text="Отправьте документ форматов .png, .jpg, .jpeg, который хотели бы вставить")
    await state.set_state(Order.image_sent)


@router.message(Order.image_sent, F.document)
async def getting_image(message: Message, state: FSMContext):
    document_type = message.document.file_name.lower()
    user_id = message.from_user.id
    if message.document.file_size > 2000000:
        await message.answer("Файл слишком велик! Отправьте документ размером менее 2 МБ")
    else:
        if (document_type[-3:] == "png") or (document_type[-3:] == "jpg") or (document_type[-4:] == "jpeg"):
            document = await message.bot.download(message.document.file_id)
            data = await state.get_data()
            item = data["order_type"]
            color = data["color"]
            with Image.open(document) as image:
                image.save(f"prints/{user_id}.png", "PNG")
                centre_pos = [(template_sizes.get(item)[0] - image.size[0]) // 2,
                              (template_sizes.get(item)[1] - image.size[1]) // 2]
                await state.update_data(
                    {"pos": [centre_pos, [-1, -1]], "size": [image.size, image.size], "angle": [0, 0],
                     "bg_deleted": [False, False]})
                template = paste(image, color, centre_pos, item, 0, 0)
                file = image_to_bytes(template)

            await message.answer_photo(file, reply_markup=confirm_or_setting_keyboard().as_markup())
            await state.set_state(Order.pos)
        else:
            await message.answer(
                text="Формат документа не поддерживается!"
            )


@router.message(Order.image_sent, F.photo)
async def photo_sent(message: Message):
    await message.answer("Отправьте фото документом, так не потеряется качество изображения")


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
    color = data["color"]
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
    color = data["color"]
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
    color = data["color"]
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
        if (x_size * increase_k < template_sizes.get(item)[0]) and (y_size * increase_k < template_sizes.get(item)[1]):
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
    color = data["color"]
    print_pos = data["pos"]
    angle = data["angle"]
    size = data["size"]
    pos_changed = False
    if callback.data == "move_right":
        if (print_pos[side][0] + size_step) < template_sizes.get(item)[0]:
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
        if (print_pos[side][1] + size_step) < template_sizes.get(item)[1]:
            print_pos[side][1] = print_pos[side][1] + size_step
            pos_changed = True
        else:
            await callback.answer("Достигнут максимум сдвига вниз")
    elif callback.data == "move_centre":
        rotations = angle[side] % 180
        if rotations == 0:
            print_pos[side] = [(template_sizes.get(item)[0] - size[side][0]) // 2,
                               (template_sizes.get(item)[1] - size[side][1]) // 2]
        else:
            print_pos[side] = [(template_sizes.get(item)[0] - size[side][1]) // 2,
                               (template_sizes.get(item)[1] - size[side][0]) // 2]
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
    color = data["color"]
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
    color = data["color"]
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
        print_pos[side] = [(template_sizes.get(item)[0] - image.size[0]) // 2,
                           (template_sizes.get(item)[1] - image.size[1]) // 2]
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
    color = data["color"]
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
    color = data["color"]
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
        elif change == "color":
            color = colors.get(value)
            await state.update_data({"color": color})
        else:
            item = value
            await state.update_data({"order_type": item})
    if bg_deleted[0]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    image1 = image.resize(tuple(size[0]), Image.Resampling.BICUBIC)
    front = paste(image1, color, print_pos[0], item, 0, angle[0], bg_deleted[0])
    file1 = image_to_bytes(front)
    file1 = InputMediaPhoto(media=file1)

    if print_pos[1][0] == -1:
        print_pos[1] = "deleted"

    if bg_deleted[1]:
        image = Image.open(f"prints/{user_id}_bg_deleted.png")
    else:
        image = Image.open(f"prints/{user_id}.png")
    image2 = image.resize(tuple(size[1]), Image.Resampling.BICUBIC)
    back = paste(image2, color, print_pos[1], item, 1, angle[1], bg_deleted[1])
    file2 = image_to_bytes(back)
    file2 = InputMediaPhoto(media=file2)

    order_type = ""
    color_name = ""
    for name, code in order_types.items():
        if code == item:
            order_type = name
    for name, code in colors.items():
        if code == color:
            color_name = name
    for name, code in keyboards.order_keyboards.colors.items():
        if code == color_name:
            color_name = name
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
    await callback.message.answer(
        text=f"Ваш заказ: \n{order_type} \nЦвет {color_name} \nРазмер {size_order.upper()} "
             f"\nПерейти к оплате?", reply_markup=checkout_or_edit_keyboard().as_markup())


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
    data = await state.get_data()
    item = data["order_type"]
    if item == "cap" or item == "cup":
        size_list = [sizes[-1]]
    else:
        size_list = sizes[:-1]
    builder = InlineKeyboardBuilder()
    for elem in size_list:
        builder.add(InlineKeyboardButton(
            text=str(elem),
            callback_data="confirm_size_" + elem.lower()
        ))
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data == "ask_color")
async def edit_color(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    for color, code in keyboards.order_keyboards.colors.items():
        builder.add(InlineKeyboardButton(
            text=str(color),
            callback_data="confirm_color_" + str(code)
        ))
    builder.adjust(3, 3)
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
    color = data["color"]
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
