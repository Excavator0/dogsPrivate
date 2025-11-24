from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_FILE = Path(__file__).resolve().parent / "aivadog.db"


def utcnow() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


@dataclass
class DiscountReward:
    id: int
    user_id: int
    percent: int
    source: str
    status: str
    expires_at: Optional[str]


class Database:
    """
    Простая обёртка над SQLite: пользователи, заказы, скидки, рассылки.
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if isinstance(db_path, (str, Path)) else DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER UNIQUE,
                    username TEXT,
                    full_name TEXT,
                    phone TEXT,
                    email TEXT,
                    first_seen TEXT,
                    last_active TEXT,
                    is_subscribed INTEGER DEFAULT 1,
                    total_spent REAL DEFAULT 0,
                    orders_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    order_number TEXT UNIQUE,
                    item_code TEXT,
                    zone TEXT,
                    size TEXT,
                    customization TEXT,
                    stickers TEXT,
                    sticker_zone TEXT,
                    pet_name TEXT,
                    pet_photo_file_id TEXT,
                    preview_front_file_id TEXT,
                    preview_back_file_id TEXT,
                    mockup_file_id TEXT,
                    status TEXT,
                    base_price INTEGER,
                    addons_price INTEGER,
                    discount_percent INTEGER DEFAULT 0,
                    total_price INTEGER,
                    referral_code TEXT,
                    share_link_code TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    payment_payload TEXT,
                    shipping_option TEXT,
                    contact_name TEXT,
                    contact_phone TEXT,
                    contact_email TEXT,
                    notes_json TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS order_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    status TEXT,
                    created_at TEXT,
                    comment TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS referral_links (
                    code TEXT PRIMARY KEY,
                    owner_user_id INTEGER,
                    order_id INTEGER,
                    percent INTEGER,
                    created_at TEXT,
                    expires_at TEXT,
                    activated INTEGER DEFAULT 0,
                    activated_at TEXT,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id),
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS referral_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT,
                    invited_user_id INTEGER,
                    created_at TEXT,
                    UNIQUE (code, invited_user_id)
                );

                CREATE TABLE IF NOT EXISTS discount_rewards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    source TEXT,
                    percent INTEGER,
                    status TEXT,
                    created_at TEXT,
                    expires_at TEXT,
                    order_id INTEGER,
                    applied_order_id INTEGER,
                    metadata TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS mailings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    segment TEXT,
                    text TEXT,
                    buttons TEXT,
                    image_file_id TEXT,
                    scheduled_at TEXT,
                    sent_at TEXT,
                    delivered INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    test_run INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS mailing_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mailing_id INTEGER,
                    user_id INTEGER,
                    status TEXT,
                    created_at TEXT,
                    FOREIGN KEY (mailing_id) REFERENCES mailings(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ugc_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER,
                    user_id INTEGER,
                    photo_file_id TEXT,
                    promo_code TEXT,
                    percent INTEGER,
                    status TEXT,
                    created_at TEXT,
                    reviewed_at TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                """
            )
            conn.commit()

    # ---------------- Пользователи ----------------
    def upsert_user(self, tg_id: int, username: Optional[str], full_name: str) -> int:
        now = utcnow()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE users
                    SET username = ?, full_name = ?, last_active = ?
                    WHERE tg_id = ?
                    """,
                    (username, full_name, now, tg_id),
                )
                user_id = row["id"]
            else:
                cur.execute(
                    """
                    INSERT INTO users (tg_id, username, full_name, first_seen, last_active)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tg_id, username, full_name, now, now),
                )
                user_id = cur.lastrowid
            conn.commit()
            return user_id

    def get_user_by_tg(self, tg_id: int):
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
            return cur.fetchone()

    def get_user_by_id(self, user_id: int):
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            return cur.fetchone()

    def increment_user_stats(self, user_id: int, total_price: int):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET total_spent = COALESCE(total_spent, 0) + ?,
                    orders_count = COALESCE(orders_count, 0) + 1,
                    last_active = ?
                WHERE id = ?
                """,
                (total_price, utcnow(), user_id),
            )
            conn.commit()

    def update_user_contacts(
        self,
        user_id: int,
        *,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ):
        fields = []
        values: List[Any] = []
        if phone is not None:
            fields.append("phone = ?")
            values.append(phone)
        if email is not None:
            fields.append("email = ?")
            values.append(email)
        if name is not None:
            fields.append("full_name = ?")
            values.append(name)
        if not fields:
            return
        fields.append("last_active = ?")
        values.append(utcnow())
        values.append(user_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()

    def set_subscription(self, user_id: int, subscribed: bool):
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET is_subscribed = ?, last_active = ? WHERE id = ?",
                (1 if subscribed else 0, utcnow(), user_id),
            )
            conn.commit()

    # ---------------- Заказы ----------------
    def create_order(
        self,
        user_id: int,
        *,
        item_code: str,
        size: str,
        zone: str,
        customization: str,
        stickers: Optional[List[str]] = None,
        sticker_zone: Optional[str] = None,
        pet_name: Optional[str] = None,
        base_price: int = 4500,
        addons_price: int = 0,
        discount_percent: int = 0,
        total_price: Optional[int] = None,
        status: str = "draft",
        notes: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, str]:
        created = utcnow()
        stickers_json = json.dumps(stickers or [], ensure_ascii=False)
        total = total_price if total_price is not None else base_price + addons_price
        notes_json = json.dumps(notes or {}, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO orders (
                    user_id, item_code, zone, size, customization, stickers, sticker_zone,
                    pet_name, status, base_price, addons_price, discount_percent,
                    total_price, created_at, updated_at, notes_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    item_code,
                    zone,
                    size,
                    customization,
                    stickers_json,
                    sticker_zone,
                    pet_name,
                    status,
                    base_price,
                    addons_price,
                    discount_percent,
                    total,
                    created,
                    created,
                    notes_json,
                ),
            )
            order_id = cur.lastrowid
            order_number = self._format_order_number(order_id)
            cur.execute("UPDATE orders SET order_number = ? WHERE id = ?", (order_number, order_id))
            self._log_status(cur, order_id, status, "Создан черновик заказа")
            conn.commit()
            return order_id, order_number

    def update_order(self, order_id: int, **fields):
        if not fields:
            return
        fields["updated_at"] = utcnow()
        assignments = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [order_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE orders SET {assignments} WHERE id = ?", values)
            conn.commit()

    def attach_preview(self, order_id: int, front_id: str, back_id: str):
        self.update_order(order_id, preview_front_file_id=front_id, preview_back_file_id=back_id)

    def get_order(self, order_id: int):
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            return cur.fetchone()

    def get_order_with_user(self, order_id: int):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT orders.*, users.tg_id, users.username, users.full_name
                FROM orders
                JOIN users ON users.id = orders.user_id
                WHERE orders.id = ?
                """,
                (order_id,),
            )
            return cur.fetchone()

    def get_order_by_number(self, order_number: str):
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM orders WHERE order_number = ?", (order_number,))
            return cur.fetchone()

    def get_order_by_number_with_user(self, order_number: str):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT orders.*, users.tg_id, users.username, users.full_name
                FROM orders
                JOIN users ON users.id = orders.user_id
                WHERE orders.order_number = ?
                """,
                (order_number,),
            )
            return cur.fetchone()

    def list_recent_orders(self, limit: int = 10):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT orders.*, users.full_name, users.phone, users.tg_id
                FROM orders
                JOIN users ON users.id = orders.user_id
                ORDER BY orders.created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return cur.fetchall()

    def log_status(self, order_id: int, status: str, comment: Optional[str] = None):
        with self._connect() as conn:
            cur = conn.cursor()
            self._log_status(cur, order_id, status, comment)
            cur.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                (status, utcnow(), order_id),
            )
            conn.commit()

    def _log_status(self, cursor: sqlite3.Cursor, order_id: int, status: str, comment: Optional[str]):
        cursor.execute(
            """
            INSERT INTO order_status_history (order_id, status, created_at, comment)
            VALUES (?, ?, ?, ?)
            """,
            (order_id, status, utcnow(), comment),
        )

    def get_order_history(self, order_id: int):
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM order_status_history WHERE order_id = ? ORDER BY created_at ASC",
                (order_id,),
            )
            return cur.fetchall()

    def update_order_notes(self, order_id: int, **fields):
        with self._connect() as conn:
            cur = conn.execute("SELECT notes_json FROM orders WHERE id = ?", (order_id,))
            row = cur.fetchone()
            existing = json.loads(row["notes_json"]) if row and row["notes_json"] else {}
            # Интерпретируем значение None как «удалить это поле» из notes_json,
            # чтобы старые данные (например, о готовом дизайне) не оставались в заказе.
            for key, value in fields.items():
                if value is None:
                    existing.pop(key, None)
                else:
                    existing[key] = value
            conn.execute(
                "UPDATE orders SET notes_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(existing, ensure_ascii=False), utcnow(), order_id),
            )
            conn.commit()

    def has_ugc_submission(self, order_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("SELECT 1 FROM ugc_submissions WHERE order_id = ? LIMIT 1", (order_id,))
            return cur.fetchone() is not None

    # ---------------- Рефералы и скидки ----------------
    def create_referral_link(self, owner_user_id: int, order_id: int, percent: int, hours_valid: int = 48) -> str:
        code = f"ref-{order_id}-{owner_user_id}-{int(datetime.utcnow().timestamp())}"
        expires = (datetime.utcnow() + timedelta(hours=hours_valid)).replace(microsecond=0).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO referral_links (code, owner_user_id, order_id, percent, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (code, owner_user_id, order_id, percent, utcnow(), expires),
            )
            conn.commit()
            return code

    def register_referral_hit(self, code: str, invited_user_id: int) -> Tuple[bool, Optional[int]]:
        now = utcnow()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM referral_links WHERE code = ?", (code,))
            link = cur.fetchone()
            if not link or link["owner_user_id"] == invited_user_id:
                return False, None
            
            cur.execute(
                "INSERT OR IGNORE INTO referral_hits (code, invited_user_id, created_at) VALUES (?, ?, ?)",
                (code, invited_user_id, now),
            )
            
            activated_now = False
            owner_tg_id = None
            
            cur.execute("SELECT COUNT(*) as cnt FROM referral_hits WHERE code = ?", (code,))
            count = cur.fetchone()["cnt"]
            
            if count >= 1 and not link["activated"]:
                cur.execute(
                    "UPDATE referral_links SET activated = 1, activated_at = ? WHERE code = ?",
                    (now, code),
                )
                self._create_discount_reward(cur, user_id=link["owner_user_id"], percent=link["percent"], source="referral", metadata={"code": code})
                activated_now = True
                
                # Get owner tg_id
                cur.execute("SELECT tg_id FROM users WHERE id = ?", (link["owner_user_id"],))
                owner_row = cur.fetchone()
                if owner_row:
                    owner_tg_id = owner_row["tg_id"]

            conn.commit()
            return activated_now, owner_tg_id

    def _create_discount_reward(
        self,
        cursor: sqlite3.Cursor,
        *,
        user_id: int,
        percent: int,
        source: str,
        expires_in_hours: int = 48,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        expires = (datetime.utcnow() + timedelta(hours=expires_in_hours)).replace(microsecond=0).isoformat()
        cursor.execute(
            """
            INSERT INTO discount_rewards (user_id, source, percent, status, created_at, expires_at, metadata)
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (user_id, source, percent, utcnow(), expires, json.dumps(metadata or {}, ensure_ascii=False)),
        )

    def grant_discount(self, user_id: int, percent: int, source: str, expires_in_hours: int = 48, metadata: Optional[Dict[str, Any]] = None):
        with self._connect() as conn:
            cur = conn.cursor()
            self._create_discount_reward(cur, user_id=user_id, percent=percent, source=source, expires_in_hours=expires_in_hours, metadata=metadata)
            conn.commit()

    def get_active_discount(self, user_id: int) -> Optional[DiscountReward]:
        self.expire_discounts()
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM discount_rewards
                WHERE user_id = ? AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return DiscountReward(
                id=row["id"],
                user_id=row["user_id"],
                percent=row["percent"],
                source=row["source"],
                status=row["status"],
                expires_at=row["expires_at"],
            )

    def mark_discount_used(self, reward_id: int, order_id: int):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE discount_rewards
                SET status = 'applied', applied_order_id = ?, expires_at = ?, metadata = json_set(COALESCE(metadata,'{}'), '$.applied_at', ?)
                WHERE id = ?
                """,
                (order_id, utcnow(), utcnow(), reward_id),
            )
            conn.commit()

    def expire_discounts(self):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE discount_rewards
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?
                """,
                (utcnow(),),
            )
            conn.commit()

    # ---------------- Рассылки ----------------
    def create_mailing(
        self,
        *,
        segment: str,
        text: str,
        buttons: List[Dict[str, str]],
        image_file_id: Optional[str],
        scheduled_at: Optional[str],
        test_run: bool,
    ) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO mailings (segment, text, buttons, image_file_id, scheduled_at, test_run)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (segment, text, json.dumps(buttons, ensure_ascii=False), image_file_id, scheduled_at, 1 if test_run else 0),
            )
            mailing_id = cur.lastrowid
            conn.commit()
            return mailing_id

    def update_mailing_stats(self, mailing_id: int, *, delivered_delta: int = 0, failed_delta: int = 0):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mailings
                SET delivered = delivered + ?, failed = failed + ?, sent_at = COALESCE(sent_at, ?)
                WHERE id = ?
                """,
                (delivered_delta, failed_delta, utcnow(), mailing_id),
            )
            conn.commit()

    def log_mailing_delivery(self, mailing_id: int, user_id: int, status: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mailing_logs (mailing_id, user_id, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (mailing_id, user_id, status, utcnow()),
            )
            conn.commit()

    def list_users_for_segment(self, segment: str):
        now = datetime.utcnow()
        with self._connect() as conn:
            if segment == "all":
                cur = conn.execute("SELECT * FROM users WHERE is_subscribed = 1")
            elif segment == "active_90":
                threshold = (now - timedelta(days=90)).replace(microsecond=0).isoformat()
                cur = conn.execute(
                    "SELECT * FROM users WHERE is_subscribed = 1 AND last_active >= ?",
                    (threshold,),
                )
            elif segment == "ordered":
                cur = conn.execute(
                    "SELECT DISTINCT users.* FROM users "
                    "JOIN orders ON orders.user_id = users.id "
                    "WHERE users.is_subscribed = 1 AND orders.status IN ('Оплачен','В работе','На согласовании','В печати','Готов','Отправлен')"
                )
            elif segment == "new_30":
                threshold = (now - timedelta(days=30)).replace(microsecond=0).isoformat()
                cur = conn.execute(
                    "SELECT * FROM users WHERE is_subscribed = 1 AND first_seen >= ?",
                    (threshold,),
                )
            else:
                cur = conn.execute("SELECT * FROM users WHERE 1=0")
            return cur.fetchall()

    # ---------------- UGC ----------------
    def create_ugc_submission(self, order_id: int, user_id: int, photo_file_id: str, percent: int, promo_code: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ugc_submissions (order_id, user_id, photo_file_id, percent, promo_code, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (order_id, user_id, photo_file_id, percent, promo_code, utcnow()),
            )
            conn.commit()

    def update_ugc_status(self, submission_id: int, status: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ugc_submissions
                SET status = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (status, utcnow(), submission_id),
            )
            conn.commit()

    # ---------------- Экспорт ----------------
    def fetch_users_summary(self):
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT users.*, COALESCE(SUM(orders.total_price), 0) AS total_orders_sum,
                       COUNT(orders.id) AS orders_total
                FROM users
                LEFT JOIN orders ON orders.user_id = users.id
                GROUP BY users.id
                ORDER BY users.first_seen ASC
                """
            )
            return cur.fetchall()

    @staticmethod
    def _format_order_number(order_id: int) -> str:
        return f"AVD-{datetime.utcnow():%y%m}{order_id:05d}"
