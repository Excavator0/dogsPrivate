from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InputMediaPhoto, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID
from database import db

router = Router()
order_types = {"shirt": "Футболка", "sweat": "Свитшот", "hoodie": "Худи", "cup": "Кружка", "cap": "Кепка"}
shipping_types = {"superspeed": "Супер быстрая", "post": "Почта Росии", "pickup": "Самовывоз"}
mg_id = -1


class AdminStates(StatesGroup):
    entries = State()
    details = State()
    editing = State()


@router.message((F.text == "/admin") & (F.from_user.id == ADMIN_ID))
async def cmd_admin(message: Message, state: FSMContext):
    await message.answer("Введите, сколько последних записей показать")
    await state.set_state(AdminStates.entries)


@router.message(AdminStates.entries, F.text.regexp(r"^(\d+)$"))
async def get_num_entries(message: Message, state: FSMContext):
    num = int(message.text)

    data = db.Database("database/example.db")
    data.cursor.execute("SELECT * FROM users")
    rows = data.cursor.fetchall()[-num:]
    data.close()
    for row in rows:
        text = "Номер заказа: " + str(row[0]) + "\n"
        text = text + "Имя пользователя: " + row[2] + "\n"
        text = text + "Номер телефона: " + row[6] + "\n"
        text = text + "Адрес: " + row[4] + ", " + row[3] + "\n"
        text = text + "Вид доставки: " + shipping_types.get(row[8]) + "\n"
        text = text + "Статус: " + row[9] + "\n"
        await message.answer(text)

    await message.answer("Введите номер заказа, чтобы посмотреть подробную информацию о нем")
    await state.set_state(AdminStates.details)


@router.message(AdminStates.details, F.text.regexp(r"^(\d+)$"))
async def get_details(message: Message, state: FSMContext):
    num = int(message.text)
    await state.update_data({"details": num})
    data = db.Database("database/example.db")
    data.cursor.execute("SELECT * FROM users WHERE id = ?", (num,))
    rows = data.cursor.fetchone()
    if rows is None:
        await message.answer("Не существует заказа с указанным номером")
    else:
        data.cursor.execute("SELECT * FROM users WHERE id = ?", (num,))
        row = data.cursor.fetchone()
        data.cursor.execute("SELECT * FROM orders WHERE id = ?", (num,))
        order_row = data.cursor.fetchone()
        data.cursor.execute("SELECT * FROM front_print WHERE id = ?", (num,))
        front_print_row = data.cursor.fetchone()
        data.cursor.execute("SELECT * FROM back_print WHERE id = ?", (num,))
        back_print_row = data.cursor.fetchone()
        data.close()
        file1 = InputMediaPhoto(media=front_print_row[8])
        file2 = InputMediaPhoto(media=back_print_row[8])
        await message.answer_media_group([file1, file2])

        bg_deleted = [front_print_row[6], back_print_row[6]]
        print_pos = [[front_print_row[2], front_print_row[3]], [back_print_row[2], back_print_row[3]]]

        if bg_deleted[0] and bg_deleted[1]:
            if print_pos[0][0] != -1 or print_pos[1][0] != -1:
                await message.answer_document(order_row[6])
        elif bg_deleted[0] or bg_deleted[1]:
            if print_pos[0][0] == -1:
                if print_pos[1][0] == -1:
                    pass
                else:
                    if bg_deleted[1]:
                        await message.answer_document(order_row[6])
                    else:
                        await message.answer_document(order_row[5])
            else:
                if print_pos[1][0] == -1:
                    if bg_deleted[0]:
                        await message.answer_document(order_row[6])
                    else:
                        await message.answer_document(order_row[5])
                else:
                    await message.answer_document(order_row[6])
                    await message.answer_document(order_row[5])
        else:
            if print_pos[0][0] != -1 or print_pos[1][0] != -1:
                await message.answer_document(order_row[5])

        text = "Номер заказа: " + str(row[0]) + "\n"
        text = text + "Имя пользователя: " + row[2] + "\n"
        text = text + "Номер телефона: " + row[6] + "\n"
        text = text + "Адрес: " + row[4] + ", " + row[3] + "\n"
        text = text + "Вид доставки: " + shipping_types.get(row[8]) + "\n"
        text = text + "Статус: " + row[9] + "\n\n"

        text = text + "Изделие: " + order_types.get(order_row[2]) + "\n" + "Размер: " + order_row[3] + "\n" + "Цвет: " + order_row[4] + "\n\n"
        text = text + "Информация о принтах" + "\n\n"
        text = text + "Передняя сторона" + "\n"
        text = text + "Позиция: " + f"({front_print_row[2]}, {front_print_row[3]})" + "\n"
        text = text + "Размер изображения: " + f"({front_print_row[4]}, {front_print_row[5]})" + "\n"
        if front_print_row[6]:
            deleted = "Да"
        else:
            deleted = "Нет"
        text = text + "Фон удален: " + deleted + "\n" + "Угол поворота: " + str(front_print_row[7]) + "\n\n"
        text = text + "Задняя сторона" + "\n"
        text = text + "Позиция: " + f"({back_print_row[2]}, {back_print_row[3]})" + "\n"
        text = text + "Размер изображения: " + f"({back_print_row[4]}, {back_print_row[5]})" + "\n"
        if back_print_row[6]:
            deleted = "Да"
        else:
            deleted = "Нет"
        text = text + "Фон удален: " + deleted + "\n" + "Угол поворота: " + str(back_print_row[7]) + "\n"

        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="Изменить статус",
            callback_data="admin_change_status"
        ))
        await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin_change_status")
async def change_status(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новый статус")
    await callback.message.delete_reply_markup()
    await state.set_state(AdminStates.editing)


@router.message(AdminStates.editing)
async def status_changed(message: Message, state: FSMContext):
    data = await state.get_data()
    num = data["details"]
    new_status = message.text
    await message.answer(f"Статус заказа {num} изменен на '{new_status}'")
    data = db.Database("database/example.db")
    data.cursor.execute("UPDATE users SET status = ? WHERE id = ?", (str(new_status), num,))
    data.conn.commit()
    data.close()
    await state.clear()


