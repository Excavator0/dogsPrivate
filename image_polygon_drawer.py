import copy
import math
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError as exc:
    raise SystemExit(" Требуется Pillow: pip install pillow") from exc


class PolygonDrawerApp:
    EDGE_INSERT_THRESHOLD = 8  # px
    POINT_HIT_RADIUS = 6  # px

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Polygon Drawer")

        self.points: list[tuple[int, int]] = []
        self.undo_stack: list[list[tuple[int, int]]] = []
        self.redo_stack: list[list[tuple[int, int]]] = []

        self.base_image = None
        self.image = None
        self.photo = None
        self.image_id = None
        self.scale = 1.0
        self.image_offset = (0, 0)
        self.display_size = (0, 0)
        self.canvas_width = 800
        self.canvas_height = 600
        self.dragging_index: int | None = None
        self.drag_snapshot: list[tuple[int, int]] | None = None
        self.dragging = False

        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=8, pady=4)

        tk.Button(toolbar, text="Загрузить изображение", command=self.load_image).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="Undo", command=self.undo).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="Redo", command=self.redo).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="Морфинг", command=self.morph_image_to_polygon).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="Очистить точки", command=self.clear_points).pack(side=tk.LEFT, padx=4)

        self.status_var = tk.StringVar(value="Загрузите изображение")
        tk.Label(toolbar, textvariable=self.status_var).pack(side=tk.RIGHT, padx=8)

        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(main_frame, bg="#222222", width=self.canvas_width, height=self.canvas_height)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        side_panel = tk.Frame(main_frame, width=220)
        side_panel.pack(side=tk.RIGHT, fill=tk.Y)
        tk.Label(side_panel, text="Координаты точек").pack(anchor="w", padx=6, pady=(8, 2))
        self.points_text = scrolledtext.ScrolledText(side_panel, width=24, height=30, state=tk.DISABLED)
        self.points_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

    def load_image(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[("Изображения", "*.png;*.jpg;*.jpeg;*.bmp;*.gif"), ("Все файлы", "*.*")],
        )
        if not filepath:
            return

        try:
            self.base_image = Image.open(filepath).convert("RGBA")
            self.image = self.base_image.copy()
        except OSError as err:
            messagebox.showerror("Ошибка загрузки", f"Не удалось открыть файл:\n{err}")
            return

        self._fit_image_to_canvas()
        self.clear_points()
        self.status_var.set("Изображение загружено. Кликните для добавления точек.")
        self._refresh_point_list()

    def on_canvas_press(self, event: tk.Event) -> None:
        if not self.photo:
            self.status_var.set("Сначала загрузите изображение.")
            return

        canvas_point = (event.x, event.y)
        image_point = self._canvas_to_image_coords(canvas_point)

        hit_index = self._point_near(canvas_point)
        if hit_index is not None:
            self.dragging_index = hit_index
            self.drag_snapshot = copy.deepcopy(self.points)
            self.dragging = False
            return

        insert_index = self._edge_index_for_insertion(canvas_point)

        self._record_state_for_undo()
        self.redo_stack.clear()

        if insert_index is None:
            self.points.append(image_point)
        else:
            self.points.insert(insert_index, image_point)

        self.status_var.set(f"Точек: {len(self.points)}")
        self._redraw_overlay()

    def on_canvas_drag(self, event: tk.Event) -> None:
        if self.dragging_index is None or not self.photo:
            return

        image_point = self._canvas_to_image_coords((event.x, event.y))
        clamped_point = self._clamp_to_image_bounds(image_point)
        self.points[self.dragging_index] = clamped_point
        self.dragging = True
        self.status_var.set(f"Перетаскивание точки {self.dragging_index + 1}")
        self._redraw_overlay()

    def on_canvas_release(self, event: tk.Event) -> None:
        if self.dragging_index is None:
            return

        if self.dragging and self.drag_snapshot is not None and self.drag_snapshot != self.points:
            self.undo_stack.append(self.drag_snapshot)
            if len(self.undo_stack) > 100:
                self.undo_stack.pop(0)
            self.redo_stack.clear()
            self.status_var.set(f"Перемещение завершено. Точек: {len(self.points)}")

        self.dragging_index = None
        self.drag_snapshot = None
        self.dragging = False

    def _edge_index_for_insertion(self, canvas_point: tuple[int, int]) -> int | None:
        if len(self.points) < 2:
            return None

        x, y = canvas_point
        best_index = None
        best_dist = float("inf")

        def squared_distance(px: float, py: float, qx: float, qy: float) -> float:
            return (px - qx) ** 2 + (py - qy) ** 2

        for i in range(len(self.points)):
            p1 = self._image_to_canvas_coords(self.points[i])
            p2 = self._image_to_canvas_coords(self.points[(i + 1) % len(self.points)])

            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                continue

            t = max(0.0, min(1.0, ((x - p1[0]) * dx + (y - p1[1]) * dy) / seg_len_sq))
            proj_x = p1[0] + t * dx
            proj_y = p1[1] + t * dy
            dist = math.sqrt(squared_distance(x, y, proj_x, proj_y))

            if dist <= self.EDGE_INSERT_THRESHOLD and dist < best_dist:
                best_dist = dist
                best_index = i + 1

        return best_index

    def _point_near(self, canvas_point: tuple[int, int]) -> int | None:
        if not self.points:
            return None
        x, y = canvas_point
        for idx, point in enumerate(self.points):
            px, py = self._image_to_canvas_coords(point)
            if math.hypot(px - x, py - y) <= self.POINT_HIT_RADIUS:
                return idx
        return None

    def undo(self) -> None:
        if not self.undo_stack:
            self.status_var.set("История пуста.")
            return
        self.redo_stack.append(copy.deepcopy(self.points))
        self.points = self.undo_stack.pop()
        self.status_var.set(f"Undo. Точек: {len(self.points)}")
        self._redraw_overlay()

    def redo(self) -> None:
        if not self.redo_stack:
            self.status_var.set("Redo недоступен.")
            return
        self.undo_stack.append(copy.deepcopy(self.points))
        self.points = self.redo_stack.pop()
        self.status_var.set(f"Redo. Точек: {len(self.points)}")
        self._redraw_overlay()

    def clear_points(self) -> None:
        self.points.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dragging_index = None
        self.drag_snapshot = None
        self.dragging = False
        self.canvas.delete("overlay")
        self.status_var.set("Точки очищены.")
        self._refresh_point_list()

    def _record_state_for_undo(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.points))
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)

    def _redraw_overlay(self) -> None:
        self.canvas.delete("overlay")
        if not self.points:
            return

        for i, point in enumerate(self.points):
            next_point = self.points[(i + 1) % len(self.points)]
            canvas_point = self._image_to_canvas_coords(point)
            next_canvas = self._image_to_canvas_coords(next_point)
            self.canvas.create_line(
                *canvas_point,
                *next_canvas,
                fill="#ef4444",
                width=2,
                tags="overlay",
            )

        for point in self.points:
            x, y = self._image_to_canvas_coords(point)
            self.canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill="#f97316",
                outline="#ffffff",
                width=1,
                tags="overlay",
            )
        self._refresh_point_list()

    def morph_image_to_polygon(self) -> None:
        if not self.base_image:
            self.status_var.set("Сначала загрузите изображение.")
            return
        if len(self.points) < 3:
            self.status_var.set("Нужно минимум 3 точки для морфинга.")
            return

        if len(self.points) == 4:
            self._morph_with_perspective()
        else:
            if cv2 is None:
                self.status_var.set("Требуется opencv-python: pip install opencv-python")
                return
            try:
                self._morph_with_triangulation()
            except ValueError as exc:
                self.status_var.set(f"Ошибка морфинга: {exc}")
                return

        self._render_image_on_canvas()
        self._redraw_overlay()
        self.status_var.set("Изображение проецировано на фигуру.")

    def _refresh_point_list(self) -> None:
        if not hasattr(self, "points_text"):
            return
        self.points_text.config(state=tk.NORMAL)
        self.points_text.delete("1.0", tk.END)
        for idx, (x, y) in enumerate(self.points, start=1):
            self.points_text.insert(tk.END, f"{idx}: ({x}, {y})\n")
        self.points_text.config(state=tk.DISABLED)

    def _canvas_to_image_coords(self, canvas_point: tuple[int, int]) -> tuple[int, int]:
        if not self.image:
            return canvas_point
        x, y = canvas_point
        if self.scale == 0:
            return canvas_point
        rel_x = (x - self.image_offset[0]) / self.scale
        rel_y = (y - self.image_offset[1]) / self.scale
        return int(round(rel_x)), int(round(rel_y))

    def _image_to_canvas_coords(self, image_point: tuple[int, int]) -> tuple[int, int]:
        x, y = image_point
        canvas_x = self.image_offset[0] + x * self.scale
        canvas_y = self.image_offset[1] + y * self.scale
        return canvas_x, canvas_y

    def _clamp_to_image_bounds(self, image_point: tuple[int, int]) -> tuple[int, int]:
        if not self.image:
            return image_point
        x, y = image_point
        max_w, max_h = self.image.size
        x = max(0, min(max_w - 1, x))
        y = max(0, min(max_h - 1, y))
        return x, y

    def _fit_image_to_canvas(self) -> None:
        if not self.image:
            return
        self.canvas.update_idletasks()
        canvas_w = self.canvas.winfo_width() or self.canvas_width
        canvas_h = self.canvas.winfo_height() or self.canvas_height
        img_w, img_h = self.image.size
        self.scale = min(1.0, canvas_w / img_w, canvas_h / img_h)
        self.display_size = (max(1, int(img_w * self.scale)), max(1, int(img_h * self.scale)))
        offset_x = max((canvas_w - self.display_size[0]) // 2, 0)
        offset_y = max((canvas_h - self.display_size[1]) // 2, 0)
        self.image_offset = (offset_x, offset_y)
        self._render_image_on_canvas()

    def _render_image_on_canvas(self) -> None:
        if not self.image:
            return
        display_image = (
            self.image
            if self.scale == 1.0
            else self.image.resize(self.display_size, Image.LANCZOS)
        )
        self.photo = ImageTk.PhotoImage(display_image)
        if self.image_id:
            self.canvas.delete(self.image_id)
        self.canvas.delete("overlay")
        self.image_id = self.canvas.create_image(
            self.image_offset[0], self.image_offset[1], image=self.photo, anchor=tk.NW
        )

    def _morph_with_perspective(self) -> None:
        try:
            coeffs = self._compute_perspective_coeffs(
                [tuple(map(float, pt)) for pt in self.points],
                [
                    (0.0, 0.0),
                    (float(self.base_image.width), 0.0),
                    (float(self.base_image.width), float(self.base_image.height)),
                    (0.0, float(self.base_image.height)),
                ],
            )
        except ValueError as exc:
            raise ValueError(f"Не удалось вычислить проекцию: {exc}") from exc

        warped = self.base_image.transform(
            self.base_image.size,
            Image.PERSPECTIVE,
            coeffs,
            Image.BICUBIC,
        )

        mask = Image.new("L", self.base_image.size, 0)
        ImageDraw.Draw(mask).polygon(self.points, fill=255)
        transparent_bg = Image.new("RGBA", self.base_image.size, (0, 0, 0, 0))
        self.image = Image.composite(warped, transparent_bg, mask)

    def _morph_with_triangulation(self) -> None:
        if not cv2:
            raise ValueError("Отсутствует зависимость opencv-python")
        dest_pts = [tuple(map(float, pt)) for pt in self.points]
        src_ring = self._generate_source_ring_points(len(dest_pts))
        triangles = self._triangulate_polygon(dest_pts)
        if not triangles:
            raise ValueError("Не удалось триангулировать фигуру.")

        src_np = np.array(self.base_image.convert("RGBA"))
        dst_np = np.zeros_like(src_np)

        for tri in triangles:
            src_tri = np.float32([src_ring[idx] for idx in tri])
            dst_tri = np.float32([dest_pts[idx] for idx in tri])
            self._warp_triangle(src_np, dst_np, src_tri, dst_tri)

        mask = np.zeros(dst_np.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [np.int32(dest_pts)], 255)
        for c in range(4):
            dst_np[:, :, c] = cv2.bitwise_and(dst_np[:, :, c], mask)

        self.image = Image.fromarray(dst_np)

    def _warp_triangle(
        self,
        src_np: np.ndarray,
        dst_np: np.ndarray,
        src_tri: np.ndarray,
        dst_tri: np.ndarray,
    ) -> None:
        rect = cv2.boundingRect(dst_tri)
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return

        dst_tri_rect = np.array(
            [[pt[0] - x, pt[1] - y] for pt in dst_tri], dtype=np.float32
        )

        M = cv2.getAffineTransform(src_tri, dst_tri_rect)
        warped = cv2.warpAffine(
            src_np,
            M,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )

        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillConvexPoly(mask, np.int32(dst_tri_rect), 255)

        roi = dst_np[y : y + h, x : x + w]
        if roi.shape[0] != h or roi.shape[1] != w:
            return

        bg = cv2.bitwise_and(roi, roi, mask=cv2.bitwise_not(mask))
        fg = cv2.bitwise_and(warped, warped, mask=mask)
        dst_np[y : y + h, x : x + w] = cv2.add(bg, fg)

    def _generate_source_ring_points(self, count: int) -> list[tuple[float, float]]:
        width = float(self.base_image.width)
        height = float(self.base_image.height)
        if count <= 0:
            return []

        perimeter = self._polygon_perimeter(self.points)
        if perimeter <= 0:
            perimeter = 1.0

        fractions = []
        cumulative = 0.0
        for i in range(len(self.points)):
            fractions.append(cumulative / perimeter)
            p1 = self.points[i]
            p2 = self.points[(i + 1) % len(self.points)]
            cumulative += math.hypot(p2[0] - p1[0], p2[1] - p1[1])

        return [
            self._point_on_rectangle_perimeter(width, height, frac % 1.0)
            for frac in fractions
        ]

    @staticmethod
    def _point_on_rectangle_perimeter(width: float, height: float, fraction: float) -> tuple[float, float]:
        perimeter = 2 * (width + height)
        distance = fraction * perimeter
        edges = [
            (width, (1, 0)),  # top edge
            (height, (0, 1)),  # right edge
            (width, (-1, 0)),  # bottom edge
            (height, (0, -1)),  # left edge
        ]

        x, y = 0.0, 0.0
        direction_index = 0
        positions = [
            (0.0, 0.0),
            (width, 0.0),
            (width, height),
            (0.0, height),
        ]
        x, y = positions[direction_index]

        for length, direction in edges:
            if distance <= length:
                dx, dy = direction
                return (x + dx * distance, y + dy * distance)
            distance -= length
            direction_index = (direction_index + 1) % 4
            x, y = positions[direction_index]

        return positions[0]

    def _triangulate_polygon(self, points: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
        if len(points) < 3:
            return []

        remaining = list(range(len(points)))
        triangles: list[tuple[int, int, int]] = []
        orientation = self._polygon_area(points) > 0

        def is_convex(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            return cross > 0 if orientation else cross < 0

        def point_in_triangle(pt, ta, tb, tc) -> bool:
            def sign(p1, p2, p3):
                return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

            b1 = sign(pt, ta, tb) < 0.0
            b2 = sign(pt, tb, tc) < 0.0
            b3 = sign(pt, tc, ta) < 0.0
            return (b1 == b2) and (b2 == b3)

        iterations = 0
        while len(remaining) > 2 and iterations < 1000:
            ear_found = False
            for idx in range(len(remaining)):
                prev_idx = remaining[idx - 1]
                curr_idx = remaining[idx]
                next_idx = remaining[(idx + 1) % len(remaining)]

                a, b, c = points[prev_idx], points[curr_idx], points[next_idx]
                if not is_convex(a, b, c):
                    continue

                ear = True
                for other in remaining:
                    if other in (prev_idx, curr_idx, next_idx):
                        continue
                    if point_in_triangle(points[other], a, b, c):
                        ear = False
                        break

                if ear:
                    triangles.append((prev_idx, curr_idx, next_idx))
                    del remaining[idx]
                    ear_found = True
                    break

            if not ear_found:
                break
            iterations += 1

        if len(triangles) < len(points) - 2:
            raise ValueError("Не удалось найти разбиение на треугольники.")
        return triangles

    @staticmethod
    def _polygon_area(points: list[tuple[float, float]]) -> float:
        area = 0.0
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            area += x1 * y2 - x2 * y1
        return area / 2.0

    @staticmethod
    def _polygon_perimeter(points: list[tuple[float, float]]) -> float:
        perimeter = 0.0
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            perimeter += math.hypot(x2 - x1, y2 - y1)
        return perimeter

    def _compute_perspective_coeffs(
        self, dest_points: list[tuple[float, float]], src_points: list[tuple[float, float]]
    ) -> list[float]:
        if len(dest_points) != 4 or len(src_points) != 4:
            raise ValueError("Нужно по 4 точки.")

        matrix: list[list[float]] = []
        rhs: list[float] = []
        for (x_dst, y_dst), (x_src, y_src) in zip(dest_points, src_points):
            matrix.append([x_dst, y_dst, 1, 0, 0, 0, -x_src * x_dst, -x_src * y_dst])
            rhs.append(x_src)
            matrix.append([0, 0, 0, x_dst, y_dst, 1, -y_src * x_dst, -y_src * y_dst])
            rhs.append(y_src)

        solution = self._solve_linear_system(matrix, rhs)
        solution.append(1.0)
        return solution

    @staticmethod
    def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
        size = len(rhs)
        aug = [row[:] + [val] for row, val in zip(matrix, rhs)]

        for col in range(size):
            pivot = max(range(col, size), key=lambda r: abs(aug[r][col]))
            if abs(aug[pivot][col]) < 1e-9:
                raise ValueError("Система вырождена.")
            if pivot != col:
                aug[col], aug[pivot] = aug[pivot], aug[col]

            pivot_val = aug[col][col]
            aug[col] = [value / pivot_val for value in aug[col]]

            for row in range(size):
                if row == col:
                    continue
                factor = aug[row][col]
                if factor == 0.0:
                    continue
                aug[row] = [val - factor * base for val, base in zip(aug[row], aug[col])]

        return [row[-1] for row in aug]


def main() -> None:
    root = tk.Tk()
    app = PolygonDrawerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

