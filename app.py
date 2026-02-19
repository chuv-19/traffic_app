import sys, os, json, random
import sqlite3
try:
    import serial
except Exception:
    serial = None
from PyQt5.QtWidgets import QApplication, QMainWindow, QGraphicsScene, QGraphicsView, QVBoxLayout, QGraphicsItem, QGraphicsPixmapItem, QGraphicsTextItem, QWidget, QHBoxLayout, QPushButton, QLineEdit, QComboBox, QFormLayout, QDockWidget, QLabel, QFileDialog, QButtonGroup, QRadioButton, QGroupBox, QDialog, QTableWidget, QTableWidgetItem # <<< ДОБАВЛЕНО: QDialog, QTableWidget, QTableWidgetItem и др.
from PyQt5.QtGui import QBrush, QPen, QColor, QIcon, QPixmap, QTransform
from PyQt5.QtCore import Qt, QTimer, QPointF
import math

MEDIA_DIR = r"C:\Users\elshi\Desktop\traffic_app\media"
MAP_FILE = "map.json"
CARS_FILE = "cars.json"
DB_NAME = "traffic_stats.db" 
GRID_SIZE = 35 # Размер сетки

class DbViewerWindow(QDialog): 
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Просмотр Таблиц БД")
        self.conn = conn
        self.cursor = self.conn.cursor()
        self.resize(800, 600)

        self.layout = QVBoxLayout(self)
        self.table_selector = QComboBox()
        self.table_selector.addItems(["Traffic_light", "Cars_stats"])
        self.layout.addWidget(self.table_selector)
        
        self.load_button = QPushButton("Отобразить таблицу")
        self.load_button.clicked.connect(self.load_table_data)
        self.layout.addWidget(self.load_button)

        self.table_widget = QTableWidget()
        self.layout.addWidget(self.table_widget)

        self.load_table_data()

    def load_table_data(self):
        table_name = self.table_selector.currentText()
        try:
            self.cursor.execute(f"SELECT * FROM {table_name}")
            data = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]

            self.table_widget.setRowCount(len(data))
            self.table_widget.setColumnCount(len(columns))
            self.table_widget.setHorizontalHeaderLabels(columns)

            for row_idx, row_data in enumerate(data):
                for col_idx, item in enumerate(row_data):
                    self.table_widget.setItem(row_idx, col_idx, QTableWidgetItem(str(item)))

            self.table_widget.resizeColumnsToContents()

        except Exception as e:
            self.table_widget.clear()
            self.table_widget.setRowCount(0)
            self.table_widget.setColumnCount(1)
            self.table_widget.setHorizontalHeaderLabels(["Ошибка"])
            self.table_widget.setItem(0, 0, QTableWidgetItem(f"Ошибка БД: {e}"))
            print(f"Error loading data from {table_name}: {e}")

class GridView(QGraphicsView):
    def __init__(self, scene, editor, grid_size=35):
        super().__init__(scene)
        self.editor = editor
        self.grid_size = grid_size

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.DotLine))
        left = int(rect.left()) - (int(rect.left()) % self.grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.grid_size)
        for x in range(left, int(rect.right()), self.grid_size):
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
        for y in range(top, int(rect.bottom()), self.grid_size):
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.editor.drawing_path and self.editor.selected_car:
                scene_pos = self.mapToScene(event.pos())
                snapped_x = int(scene_pos.x() // self.grid_size) * self.grid_size
                snapped_y = int(scene_pos.y() // self.grid_size) * self.grid_size

                if "Path" not in self.editor.selected_car.props:
                    self.editor.selected_car.props["Path"] = []
                    self.editor.selected_car.props["PathLines"] = []

                path = self.editor.selected_car.props["Path"]
                path.append((snapped_x, snapped_y))

                if len(path) > 1:
                    prev_x, prev_y = path[-2]
                    path_color = self.editor.selected_car.props.get("PathColor", QColor(0, 255, 0))
                    line = self.scene().addLine(prev_x + 17.5, prev_y + 17.5, snapped_x + 17.5, snapped_y + 17.5, QPen(path_color, 2))
                    self.editor.selected_car.props["PathLines"].append(line)
                event.accept()
            elif self.editor.selected_obj_type:
                scene_pos = self.mapToScene(event.pos())
                snapped_x = int(scene_pos.x() // self.grid_size) * self.grid_size
                snapped_y = int(scene_pos.y() // self.grid_size) * self.grid_size

                if self.is_valid_placement(snapped_x, snapped_y, self.editor.selected_obj_type):
                    self.editor.add_object(snapped_x, snapped_y, self.editor.selected_obj_type)
                    self.editor.selected_obj_type = None
                event.accept()
            else:
                # Check if clicked on a road and save its coordinates
                scene_pos = self.mapToScene(event.pos())
                clicked_items = self.scene().items(scene_pos)
                for item in clicked_items:
                    if isinstance(item, SceneObject) and item.obj_type.startswith("R"):
                        self.editor.save_road_click(item)
                        event.accept()
                        return
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def is_valid_placement(self, x, y, obj_type):
        if obj_type == "светофор":
            return self.is_near_intersection(x, y)
        elif obj_type == "пешеходный переход":
            return self.is_on_road(x, y)
        elif obj_type == "пешеход":
            return self.is_near_pedestrian_crossing(x, y)
        elif obj_type == "движение запрещено":
            return self.is_on_road(x, y)
        return True 

    def is_near_intersection(self, x, y):
        for item in self.scene().items():
            if isinstance(item, SceneObject) and item.obj_type == "Rcrossroads":
                dx = abs(item.x() - x)
                dy = abs(item.y() - y)
                if dx <= 35 and dy <= 35:
                    return True
        return False

    def is_on_road(self, x, y):
        for item in self.scene().items():
            if isinstance(item, SceneObject) and item.obj_type.startswith("R"):
                dx = abs(item.x() - x)
                dy = abs(item.y() - y)
                if dx <= 35 and dy <= 35:
                    return True
        return False

    def is_near_pedestrian_crossing(self, x, y):
        for item in self.scene().items():
            if isinstance(item, SceneObject) and item.obj_type == "пешеходный переход":
                dx = abs(item.x() - x)
                dy = abs(item.y() - y)
                if dx <= 35 and dy <= 35: 
                    return True
        return False

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        for item in self.scene().selectedItems():
            pos = item.pos()
            snapped_x = round(pos.x() / self.grid_size) * self.grid_size
            snapped_y = round(pos.y() / self.grid_size) * self.grid_size
            item.setPos(snapped_x, snapped_y)


class SceneObject(QGraphicsPixmapItem):
    def __init__(self,x,y, obj_type, props=None):
        super().__init__()

        self.obj_type = obj_type
        self.props = props if props else {}

        self.setPos(x,y)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable) if not self.obj_type in ["Rvertical", "Rcrossroads"] else ...

        if self.obj_type.startswith("R"):
            self.setAcceptHoverEvents(True)
            self.coord_label = QGraphicsTextItem("")
            self.coord_label.setZValue(100)
            self.coord_label.setDefaultTextColor(Qt.black)
            self.coord_label.hide()

        self.update_visuals()

    def _load_pix(self, filename_base):
        # Try several candidate paths/extensions and return a QPixmap (possibly null)
        candidates = [
            os.path.join(MEDIA_DIR, filename_base),
            os.path.join(MEDIA_DIR, filename_base + ".png"),
            os.path.join(MEDIA_DIR, filename_base + ".ico")
        ]
        for p in candidates:
            try:
                if os.path.exists(p):
                    return QPixmap(p)
            except Exception:
                continue
        return QPixmap()
    def update_visuals(self):
        pix = QPixmap()

        if self.obj_type == "светофор":
            state = self.props.get("State", "red")
            pix = self._load_pix(f"TL{state}")

        elif self.obj_type == "пешеходный переход":
            dir = self.props.get("Direction", "vertical")
            pix = self._load_pix(f"Z{dir}")

        elif self.obj_type == "пешеход":
            pix = self._load_pix("Pedestrain")

        elif self.obj_type == "движение запрещено":
            type = self.props.get("Type", "Stop")
            pix = self._load_pix(f"{type}")
        elif self.obj_type == "start":
            type = self.props.get("Type", "Start")
            pix = self._load_pix(f"{type}")

        elif self.obj_type == "block":
            type = self.props.get("Type", "Block")
            pix = self._load_pix(f"{type}")

        elif self.obj_type == "авто":
            direction = self.props.get("Direction", "Север")
            if direction in ["Север", "North"]: pix = self._load_pix("Cvertical")
            elif direction in ["Юг", "South"]: pix = self._load_pix("Cbottom")
            elif direction in ["Запад", "West"]: pix = self._load_pix("Cleft")
            elif direction in ["Восток", "East"]: pix = self._load_pix("Cright")
            else: pix = self._load_pix("Cvertical")
            if not pix.isNull(): pix = pix.scaled(35, 35, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        elif self.obj_type == "Rvertical":
            pix = self._load_pix("Rvertical")
            angle = int(self.props.get("Rotation", 0))
            if angle != 0:
                from PyQt5.QtGui import QTransform
                pix = pix.transformed(QTransform().rotate(angle))

        elif self.obj_type == "Rcrossroads":
            pix = self._load_pix("Rcrossroads")

        self.setPixmap(pix)

        if self.obj_type.startswith("R"):
            self.setZValue(-20)
        elif self.obj_type == "пешеходный переход":
            self.setZValue(-19)
        else:
            self.setZValue(-18)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            grid_size = 35
            new_pos = value
            new_pos.setX(round(new_pos.x() / grid_size) * grid_size)
            new_pos.setY(round(new_pos.y() / grid_size) * grid_size)
            return new_pos
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        if self.obj_type.startswith("R"):
            self.coord_label.setPlainText(f"({int(self.x())}, {int(self.y())})")
            self.coord_label.setPos(self.scenePos().x(), self.scenePos().y() + 30)
            self.coord_label.show()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        if self.obj_type.startswith("R"):
            self.coord_label.hide()
        super().hoverLeaveEvent(event)

    
class RoadEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        
# DB, Ticks, and Timer Setup <<< ИНИЦИАЛИЗАЦИЯ БД И ТИКОВ
        self.conn = sqlite3.connect(DB_NAME)
        self.cursor = self.conn.cursor()
        self.setup_db()
        self.tick_counter = 0

        self.global_timer = QTimer()
        self.global_timer.timeout.connect(self.increment_tick_counter)
        self.global_timer.start(50) # 50 ms per tick

        # Serial communication setup
        try:
            self.serial_port = serial.Serial('COM9', 9600, timeout=1)
            self.serial_timer = QTimer()
            self.serial_timer.timeout.connect(self.read_serial)
            self.serial_timer.start(100)  # Check every 100ms
            self.send_light_state_to_arduino("red")  # Send initial red state
        except Exception as e:
            print(f"Serial port error: {e}")
            self.serial_port = None
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 1000, 800)
        self.view = GridView(self.scene, self)
        self.setWindowTitle("Редактор ИИ-системы дорожного движения")
        self.setWindowIcon(QIcon(os.path.join(MEDIA_DIR, "TLgreen.png")))

        self.setGeometry(0,0,1000,800)

        self.show_btn = QPushButton("Добавить объект")
        self.show_btn.clicked.connect(lambda: self.show_hide_toolbar())
        self.scene.selectionChanged.connect(self.on_select)

        self.start_car_btn = QPushButton("Запуск")
        self.start_car_btn.clicked.connect(lambda: self.start_car_movement())

        # New DB Viewer button <<< КНОПКА "ТАБЛИЦЫ"
        self.db_viewer_btn = QPushButton("Таблицы")
        self.db_viewer_btn.clicked.connect(self.show_db_viewer)

        central_widget = QWidget()
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        hlayout.addWidget(self.show_btn)
        hlayout.addWidget(self.start_car_btn)
        hlayout.addWidget(self.db_viewer_btn)  # <<< ДОБАВЛЕНИЕ КНОПКИ В ЛЭЙАУТ
        layout.addLayout(hlayout)
        layout.addWidget(self.view)
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        self.selected_obj_type = None

        self.is_auto_mode = False
        self.failure_mode = False
        self.time_mode = False
        self.transport_mode = False
        self.test_random_mode = False
        self.test_template_mode = False
        self.traffic_timer = QTimer()
        self.traffic_timer.timeout.connect(self.next_traffic_phase)
        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.toggle_time_mode)
        self.transport_timer = QTimer()
        self.transport_timer.timeout.connect(self.check_transport_mode)
        self.test_template_timer = QTimer()
        self.test_template_timer.timeout.connect(self.add_test_car)
        self.test_cars = []
        self.car_id_counter = 0
        self.test_random_timer = QTimer()
        self.test_random_timer.timeout.connect(self.spawn_random_car)
        self.test_random_light_timer = QTimer()
        self.test_random_light_timer.timeout.connect(self.random_change_lights)
        self.random_spawn_points = []
        self.current_phase = 0
        self.phase_intervals = [1000, 1000, 1000, 1000]
        self.time_mode_state = "red"
        self.current_mode_label = None
        self.drawing_path = False
        self.selected_car = None
        self.car_movement_timer = QTimer()
        self.car_movement_timer.timeout.connect(self.move_cars)
        self.car_appear_timer = QTimer()
        self.car_appear_timer.timeout.connect(self.show_random_car)
        self.invisible_cars = []



        self.load_scene_from_file(MAP_FILE)

        self.init_ui()

        self.tb_state = 0
        self.toolbar.hide()
    
    def closeEvent(self, event): # Закрытие соединения БД
        self.conn.close()
        super().closeEvent(event)

    def show_db_viewer(self): # Открытие окна просмотра БД
        viewer = DbViewerWindow(self.conn, self)
        viewer.exec_()

    def setup_db(self): # Создание таблиц БД
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Traffic_light (
                Id_light INTEGER PRIMARY KEY,
                Car_count_full_run INTEGER DEFAULT 0,
                Car_average_in_minute REAL DEFAULT 0.0,
                Count_color_switches INTEGER DEFAULT 0
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Cars_stats (
                Car_id INTEGER PRIMARY KEY AUTOINCREMENT,
                Car_spawn_ticks INTEGER,
                Car_exit_ticks INTEGER
            )
        """)
        self.conn.commit()

    def reset_db_tables(self): # Сброс данных для тестов
        # Удаление данных
        self.cursor.execute("DELETE FROM Traffic_light")
        self.cursor.execute("DELETE FROM Cars_stats")
        # Сброс счетчиков в Traffic_light для существующих светофоров
        self.cursor.execute("""
            UPDATE Traffic_light SET Car_count_full_run = 0, Car_average_in_minute = 0.0, Count_color_switches = 0
        """)
        self.conn.commit()
        self.tick_counter = 0 # Сброс счетчика тиков
        self.car_id_counter = 0 # Сброс счетчика ID машин
        print("База данных сброшена.")

        def reset_database(conn):
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Cars_stats;")
            cursor.execute("""
                UPDATE Traffic_light 
                SET Car_count_full_run = 0, 
                Car_average_in_minute = 0.0, 
                Count_color_switches = 0;
            """)
        self.conn.commit()
    print("СБРОС ТЕСТА: Все данные в таблицах 'Traffic_light' и 'Cars_stats' обнулены.")
   

    def increment_tick_counter(self): # Инкремент тиков и расчет среднего
        self.tick_counter += 1
        
        # Расчет Car_average_in_minute (1200 тиков = 60 секунд при 50мс/тик)
        if self.tick_counter % 1200 == 0 and self.tick_counter > 0:
            minutes_passed = self.tick_counter / 1200
            self.cursor.execute("""
                UPDATE Traffic_light SET 
                Car_average_in_minute = CAST(Car_count_full_run AS REAL) / ?
            """, (minutes_passed,))
            self.conn.commit()

    def init_ui(self):
        self.create_toolbar()
        self.create_properties()
        self.create_control_panel()

    def create_toolbar(self):
        self.toolbar = QDockWidget("Добавить объект")
        self.addDockWidget(Qt.LeftDockWidgetArea, self.toolbar)
        toolbar_widget = QWidget()
        toolbar_layout = QVBoxLayout()

        self.btn_tl = QPushButton("")
        self.btn_tl.setIcon(QIcon(os.path.join(MEDIA_DIR, "TLgreen.png")))
        self.btn_tl.setStyleSheet("background-color: #e0f7fa; border: 1px solid #004d40;")
        self.btn_tl.clicked.connect(lambda: self.select_obj_type("светофор"))
        self.btn_zebra = QPushButton("")
        self.btn_zebra.setIcon(QIcon(os.path.join(MEDIA_DIR, "Zvertical.png")))
        self.btn_zebra.setStyleSheet("background-color: #A08C75; border: 1px solid #e65100;")
        self.btn_zebra.clicked.connect(lambda: self.select_obj_type("пешеходный переход"))
        self.btn_ped = QPushButton("")
        self.btn_ped.setIcon(QIcon(os.path.join(MEDIA_DIR, "Pedestrain.png")))
        self.btn_ped.setStyleSheet("background-color: #f3e5f5; border: 1px solid #4a148c;")
        self.btn_ped.clicked.connect(lambda: self.select_obj_type("пешеход"))
        self.btn_stop = QPushButton("")
        self.btn_stop.setIcon(QIcon(os.path.join(MEDIA_DIR, "Stop.png")))
        self.btn_stop.setStyleSheet("background-color: #ffebee; border: 1px solid #b71c1c;")
        self.btn_stop.clicked.connect(lambda: self.select_obj_type("движение запрещено"))
        self.btn_start_sign = QPushButton("")
        self.btn_start_sign.setIcon(QIcon(os.path.join(MEDIA_DIR, "Start.png")))
        self.btn_start_sign.setStyleSheet("background-color: #e8f5e8; border: 1px solid #2e7d32;")
        self.btn_start_sign.clicked.connect(lambda: self.select_obj_type("start"))
        
        self.btn_block_sign = QPushButton("")
        self.btn_block_sign.setIcon(QIcon(os.path.join(MEDIA_DIR, "Block.png")))
        self.btn_block_sign.setStyleSheet("background-color: #fff3e0; border: 1px solid #ef6c00;")
        self.btn_block_sign.clicked.connect(lambda: self.select_obj_type("block"))
        [toolbar_layout.addWidget(x) for x in [self.btn_tl, self.btn_zebra, self.btn_ped, self.btn_stop, self.btn_start_sign, self.btn_block_sign]]
        toolbar_layout.addStretch()
        toolbar_widget.setLayout(toolbar_layout)
        self.toolbar.setWidget(toolbar_widget)

    def show_hide_toolbar(self):
        if self.tb_state == 0:
            self.tb_state = 1
            self.toolbar.show()
        else:
            self.tb_state = 0
            self.toolbar.hide()

    def create_properties(self):
        self.prop_dock = QDockWidget("Свойства")
        self.addDockWidget(Qt.RightDockWidgetArea, self.prop_dock)
        self.prop_widget = QWidget()
        self.prop_layout = QFormLayout()
        self.prop_widget.setLayout(self.prop_layout)
        self.prop_dock.setWidget(self.prop_widget)
        

    def create_control_panel(self):
        self.control_dock = QDockWidget("Панель управления перекрёстком", self)
        # 1. Стилизация DockWidget
        self.control_dock.setStyleSheet("""
            QDockWidget {
                border: 1px solid #b0bec5;
            }
            QDockWidget::title {
                background: #90a4ae; /* Мягкий серо-синий заголовок */
                padding-left: 5px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.control_dock)

        main_widget = QWidget()
        # 2. Общая стилизация фона, кнопок и GroupBox'ов
        main_widget.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5; /* Светло-серый фон */
            }
            QPushButton {
                background-color: #e0e0e0; /* Светло-серый */
                border: 1px solid #b0b0b0;
                padding: 5px;
                border-radius: 3px;
                color: #333333;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #c0c0c0; /* Чуть темнее при наведении */
            }
            QPushButton:pressed {
                background-color: #a0a0a0; /* Темно-серый при нажатии */
                color: white;
            }
            QGroupBox {
                border: 2px solid #b0b0b0;
                border-radius: 5px;
                margin-top: 1ex;
                font-weight: bold;
                color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 8px;
                background-color: #b0b0b0; /* Серый заголовок группы */
                border-radius: 3px;
                color: white;
            }
        """)
        layout = QVBoxLayout()

        # Current mode label
        self.current_mode_label = QLabel("Текущий режим: Стандартный")
        # 3. Стилизация метки текущего режима (переопределяет общий стиль)
        self.current_mode_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #bb3e03; padding: 5px;")
        # self.current_mode_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #bb3e03; background-color: #e0fbfc; padding: 5px; border: 1px dashed #005f73;")

        layout.addWidget(self.current_mode_label)

        hlayout = QHBoxLayout()

        # Автоматический режим
        grp_auto = QGroupBox("Автоматический режим")
        vbox_auto = QVBoxLayout()
        self.btn_auto_start = QPushButton("Старт цикла")
        self.btn_auto_start.clicked.connect(self.start_auto_mode)
        self.btn_auto_stop = QPushButton("Стоп")
        self.btn_auto_stop.clicked.connect(self.stop_auto_mode)
        self.btn_auto_stop.setEnabled(False)
        vbox_auto.addWidget(self.btn_auto_start)
        vbox_auto.addWidget(self.btn_auto_stop)
        grp_auto.setLayout(vbox_auto)

        grp_manual = QGroupBox("Ручное управление")
        grid_manual = QVBoxLayout()
        btn_green = QPushButton("Зеленый всем")
        btn_green.clicked.connect(lambda: self.set_manual_phase("GREEN"))

        btn_yellow = QPushButton("Желтый всем")
        btn_yellow.clicked.connect(lambda: self.set_manual_phase("YELLOW"))

        btn_red = QPushButton("Красный всем")
        btn_red.clicked.connect(lambda: self.set_manual_phase("RED"))

        grid_manual.addWidget(btn_green)
        grid_manual.addWidget(btn_yellow)
        grid_manual.addWidget(btn_red)
        grp_manual.setLayout(grid_manual)

        grp_failure = QGroupBox("Режим сбоя")
        vbox_failure = QVBoxLayout()
        btn_failure_on = QPushButton("Активировать сбой")
        btn_failure_on.clicked.connect(self.activate_failure_mode)

        btn_failure_off = QPushButton("Деактивировать сбой")
        btn_failure_off.clicked.connect(self.deactivate_failure_mode)

        vbox_failure.addWidget(btn_failure_on)
        vbox_failure.addWidget(btn_failure_off)
        grp_failure.setLayout(vbox_failure)

        grp_modes = QGroupBox("Режимы")
        vbox_modes = QVBoxLayout()
        btn_time = QPushButton("Режим по времени")
        btn_time.clicked.connect(self.activate_time_mode)

        btn_transport = QPushButton("Режим по транспорту")
        btn_transport.clicked.connect(self.activate_transport_mode)

        btn_test_template = QPushButton("Тест-шаблон")
        btn_test_template.clicked.connect(self.activate_test_template)

        btn_test_random = QPushButton("Тест-рандом")
        btn_test_random.clicked.connect(self.activate_test_random)

        vbox_modes.addWidget(btn_time)
        vbox_modes.addWidget(btn_transport)
        vbox_modes.addWidget(btn_test_template)
        vbox_modes.addWidget(btn_test_random)
        grp_modes.setLayout(vbox_modes)

        hlayout.addWidget(grp_auto)
        hlayout.addWidget(grp_manual)
        hlayout.addWidget(grp_failure)
        hlayout.addWidget(grp_modes)

        layout.addLayout(hlayout)

        main_widget.setLayout(layout)
        self.control_dock.setWidget(main_widget)

    def on_select(self):
        items = self.scene.selectedItems()
        if items:
            self.update_props(items[0])
        else:
            self.update_props(None)

    def update_props(self, item: SceneObject):
        new_layout = QFormLayout()
        new_widget = QWidget()
        new_widget.setLayout(new_layout)

        if not item:
            new_layout.addRow(QLabel("Предмет не выбран"))
        else:
            if item.obj_type == "светофор":
                combo = QComboBox()
                combo.addItems(["red", "yellow", "green"])
                combo.setCurrentText(item.props.get("State", "red"))
                combo.currentTextChanged.connect(lambda val: self.change_prop(item, "State", val))

                new_layout.addRow("Состояние", combo)

                # Manual control buttons
                btn_green = QPushButton("Установить зеленый")
                btn_green.clicked.connect(lambda: self.set_manual_light_state(item, "green"))
                new_layout.addRow("", btn_green)

                btn_red = QPushButton("Установить красный")
                btn_red.clicked.connect(lambda: self.set_manual_light_state(item, "red"))
                new_layout.addRow("", btn_red)

                btn_standard = QPushButton("Стандартный режим")
                btn_standard.clicked.connect(lambda: self.set_manual_light_state(item, None))
                new_layout.addRow("", btn_standard)

            elif item.obj_type == "пешеходный переход":
                combo = QComboBox()
                combo.addItems(["vertical", "horizontal"])
                combo.setCurrentText(item.props.get("Direction", "vertical"))
                combo.currentTextChanged.connect(lambda val: self.change_prop(item, "Direction", val))

                new_layout.addRow("Направление", combo)

            # elif item.obj_type == "Rvertical":
            #     combo = QComboBox()
            #     combo.addItems(["0", "90", "180", "270"])
            #     combo.setCurrentText(item.props.get("Rotation", "0"))
            #     combo.currentTextChanged.connect(lambda val: self.change_prop(item, "Rotation", val))
            #     new_layout.addRow("Поворот", combo)

            elif item.obj_type == "пешеход":
                timer_label = QLabel(str(item.props.get("Timer", 0)))
                plus_btn = QPushButton("+1 сек.")
                plus_btn.clicked.connect(lambda: self.adjust_timer(item, 1, timer_label))
                minus_btn = QPushButton("-1 сек.")
                minus_btn.clicked.connect(lambda: self.adjust_timer(item, -1, timer_label))
                hbox = QHBoxLayout()
                hbox.addWidget(timer_label)
                hbox.addWidget(plus_btn)
                hbox.addWidget(minus_btn)
                new_layout.addRow("Таймер появления", hbox)

            elif item.obj_type == "движение запрещено":
                combo = QComboBox()
                combo.addItems(["Stop", "Start", "Block"])
                combo.setCurrentText(item.props.get("Type", "Stop"))
                combo.currentTextChanged.connect(lambda val: self.change_prop(item, "Type", val))

                new_layout.addRow("Тип знака", combo)

                group = QButtonGroup()
                vehicles = ["", "", ""]
                current = item.props.get("Vehicle", "")
                for v in vehicles:
                    rb = QRadioButton(v)
                    rb.setChecked(v == current)
                    rb.toggled.connect(lambda checked, v=v: self.change_prop(item, "Vehicle", v) if checked else None)
                    group.addButton(rb)
                    new_layout.addRow("", rb)

            elif item.obj_type == "авто":
                combo = QComboBox()
                combo.addItems(["Север", "Юг", "Запад", "Восток"])
                combo.setCurrentText(item.props.get("Direction", "Север"))
                combo.currentTextChanged.connect(lambda val: self.change_prop(item, "Direction", val))

                new_layout.addRow("Направление", combo)

                speed_label = QLabel(str(item.props.get("Speed", 60)))
                plus_btn = QPushButton("+10 км/ч")
                plus_btn.clicked.connect(lambda: self.adjust_speed(item, 10, speed_label))
                minus_btn = QPushButton("-10 км/ч")
                minus_btn.clicked.connect(lambda: self.adjust_speed(item, -10, speed_label))
                hbox = QHBoxLayout()
                hbox.addWidget(speed_label)
                hbox.addWidget(plus_btn)
                hbox.addWidget(minus_btn)
                new_layout.addRow("Скорость", hbox)

                draw_path_btn = QPushButton("нарисовать путь")
                draw_path_btn.clicked.connect(lambda: self.start_drawing_path(item))
                new_layout.addRow("", draw_path_btn)

            delete = QPushButton("Удалить")
            delete.clicked.connect(lambda: self.delete_obj(item))
            new_layout.addRow("Удалить объект", delete)

        self.prop_dock.setWidget(new_widget)
        self.prop_widget = new_widget
        self.prop_layout = new_layout        

    def delete_obj(self, item):
        # Remove path lines if the item has them
        if "PathLines" in item.props:
            for line in item.props["PathLines"]:
                self.scene.removeItem(line)
        self.scene.removeItem(item)
    
    def select_obj_type(self, obj_type):
        if obj_type:
            self.selected_obj_type = obj_type
        else:
            self.selected_obj_type = None
            pass

    def change_prop(self, item: SceneObject, props, prop):
        item.props[props] = prop
        if props == "State" and item.obj_type == "светофор":
            item.props["ManualState"] = prop
            self.stop_auto_mode()  # Stop auto mode when manually changing a light
            # Increment Count_color_switches for this light
            light_id = item.props.get("Id_light")
            if light_id:
                self.cursor.execute("UPDATE Traffic_light SET Count_color_switches = Count_color_switches + 1 WHERE Id_light = ?", (light_id,))
                self.conn.commit()
        item.update_visuals()

    def set_manual_light_state(self, item, state):
        if state is None:
            # Reset to standard mode, perhaps remove manual override
            if "ManualState" in item.props:
                del item.props["ManualState"]
        else:
            item.props["ManualState"] = state
            item.props["State"] = state
            self.stop_auto_mode()  # Stop auto mode when manually changing a light
            # Increment Count_color_switches for this light
            light_id = item.props.get("Id_light")
            if light_id:
                self.cursor.execute("UPDATE Traffic_light SET Count_color_switches = Count_color_switches + 1 WHERE Id_light = ?", (light_id,))
                self.conn.commit()
        item.update_visuals()

    def adjust_timer(self, item, delta, label):
        current = item.props.get("Timer", 0)
        new_val = max(0, current + delta)
        item.props["Timer"] = new_val
        label.setText(str(new_val))

    def adjust_speed(self, item, delta, label):
        current = item.props.get("Speed", 60)
        new_val = max(0, current + delta)
        item.props["Speed"] = new_val
        label.setText(str(new_val))

    def add_object(self, x, y, obj_type):
        props = None
        if obj_type == "авто":
            props = {"Speed": 60, "Direction": "Север"}
        elif obj_type == "светофор": # <<< ИЗМЕНЕНИЕ ЗДЕСЬ
            # Найти максимальный Id_light в БД и увеличить его
            self.cursor.execute("SELECT MAX(Id_light) FROM Traffic_light")
            max_id = self.cursor.fetchone()[0]
            new_id = (max_id if max_id is not None else 0) + 1
            props = {"State": "red", "Id_light": new_id}
            
            # Предварительная запись в БД (добавление нового светофора)
            # Используем INSERT OR IGNORE, чтобы избежать ошибок, если ID уже существует
            self.cursor.execute("INSERT OR IGNORE INTO Traffic_light (Id_light) VALUES (?)", (new_id,))
            self.conn.commit()
        else:
            props = None
            
        item = SceneObject(x, y, obj_type, props)
        self.scene.addItem(item)
        if item.obj_type.startswith("R"):
            self.scene.addItem(item.coord_label)

    def save_scene(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Scene", "", "JSON Files (*.json)")
        if file_path:
            scene_data = []
            for item in self.scene.items():
                if isinstance(item, SceneObject):
                    props_copy = item.props.copy()
                    if "PathLines" in props_copy:
                        del props_copy["PathLines"]
                    if "PathColor" in props_copy:
                        color = props_copy["PathColor"]
                        props_copy["PathColor"] = (color.red(), color.green(), color.blue())
                    scene_data.append({
                        "x": item.x(),
                        "y": item.y(),
                        "obj_type": item.obj_type,
                        "props": props_copy
                    })
            with open(file_path, 'w') as f:
                json.dump(scene_data, f)

    def save_road_click(self, road_item):
        """
        Saves clicked road coordinates and rotation to roads.json
        """
        roads_file = "roads.json"
        
        # Load existing roads or create new list
        try:
            with open(roads_file, 'r') as f:
                roads_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            roads_data = []
        
        # Create new road entry
        rotation = road_item.props.get("Rotation", 0)
        try:
            rotation = int(rotation)
        except (ValueError, TypeError):
            rotation = 0
        
        new_road = {
            "x": road_item.x(),
            "y": road_item.y(),
            "rotation": rotation,
            "obj_type": road_item.obj_type
        }
        
        # Check if this road already exists
        road_exists = False
        for road in roads_data:
            if road["x"] == new_road["x"] and road["y"] == new_road["y"]:
                road_exists = True
                break
        
        # Add only if it doesn't exist
        if not road_exists:
            roads_data.append(new_road)
            
            # Save to file
            with open(roads_file, 'w') as f:
                json.dump(roads_data, f, indent=2)
            
            print(f"Road saved: x={new_road['x']}, y={new_road['y']}, rotation={new_road['rotation']}")
        else:
            print(f"Road already exists: x={new_road['x']}, y={new_road['y']}")

    def load_scene_from_file(self, file_path, clear_scene=True):
        try:
            with open(file_path, 'r') as f:
                scene_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # Теперь обрабатывается как отсутствие файла, так и его повреждение
            print(f"Error loading file {file_path}: {e}")
            return
        
        if clear_scene:
            self.scene.clear()
            self.car_id_counter = 0 # Сброс счетчика машин

        for data in scene_data:
            # Handle old JSON format where "type" was used instead of "obj_type"
            obj_type = data.get("obj_type", data.get("type"))
            props = data["props"]
            if "PathColor" in props:
                r, g, b = props["PathColor"]
                props["PathColor"] = QColor(r, g, b)

            item = SceneObject(data["x"], data["y"], obj_type, props)
            self.scene.addItem(item)
            
            # --- ЛОГИКА ДЛЯ РЕГИСТРАЦИИ СВЕТОФОРОВ В БАЗЕ ДАННЫХ ---
            if item.obj_type == "светофор":
                # Initialize traffic light state to red if not already set
                if "State" not in item.props:
                    item.props["State"] = "red"
                
                light_id = item.props.get("Id_light")
                if light_id is None:
                    # Назначить новый ID, если он отсутствует в загруженных данных
                    self.cursor.execute("SELECT MAX(Id_light) FROM Traffic_light")
                    max_id = self.cursor.fetchone()[0]
                    light_id = (max_id if max_id is not None else 0) + 1
                    item.props["Id_light"] = light_id
                
                # Добавить или проигнорировать запись в БД (если ID уже есть, просто игнорируем)
                self.cursor.execute("INSERT OR IGNORE INTO Traffic_light (Id_light) VALUES (?)", (light_id,))
                self.conn.commit()
            # --------------------------------------------------------

            if item.obj_type.startswith("R"):
                self.scene.addItem(item.coord_label)
            # Recreate path lines if path exists
            if "Path" in item.props and len(item.props["Path"]) > 1:
                item.props["PathLines"] = []
                path = item.props["Path"]
                path_color = item.props.get("PathColor", QColor(0, 255, 0))
                for i in range(1, len(path)):
                    prev_x, prev_y = path[i-1]
                    curr_x, curr_y = path[i]
                    line = self.scene.addLine(prev_x + 17.5, prev_y + 17.5, curr_x + 17.5, curr_y + 17.5, QPen(path_color, 2))
                    item.props["PathLines"].append(line)

        if clear_scene:
            # Make cars with paths invisible and start timer
            self.invisible_cars = []
            for item in self.scene.items():
                if isinstance(item, SceneObject) and item.obj_type == "авто" and "Path" in item.props:
                    item.setOpacity(0)
                    if "PathLines" in item.props:
                        for line in item.props["PathLines"]:
                            line.setVisible(False)
                    self.invisible_cars.append(item)
            if self.invisible_cars:
                self.car_appear_timer.start(7000) # 7 seconds

    def load_scene(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Scene", "", "JSON Files (*.json)")
        if file_path:
            self.load_scene_from_file(file_path)

    def get_all_traffic_lights(self):
        lights = []
        for item in self.scene.items():
            if isinstance(item, SceneObject) and item.obj_type == "светофор":
                lights.append(item)
        return lights
    
    def show_all_static_objects(self):
        """Делает светофоры, пешеходов и знаки видимыми."""
        # Список типов объектов, которые нужно сделать видимыми
        target_types = ["светофор", "пешеходный переход", "пешеход", "движение запрещено"]
        
        for item in self.scene.items():
            if isinstance(item, SceneObject) and item.obj_type in target_types:
                # Установка прозрачности в 1 (полная видимость)
                item.setOpacity(1)
                item.setVisible(True) # На всякий случай

    def update_lights_visuals(self, state):
        """Обновляет все светофоры на сцене в зависимости от состояния"""
        lights = self.get_all_traffic_lights()
        for light in lights:
            if "ManualState" not in light.props:
                light.props["State"] = state
                light.update_visuals()
                # Отправляем состояние на Arduino
        self.send_light_state_to_arduino(state)

    def start_auto_mode(self):
        self.show_all_static_objects()
        self.is_auto_mode = True
        self.btn_auto_stop.setEnabled(True)
        self.btn_auto_start.setEnabled(False)
        self.log_to_db("Автопереключение", "Запущен автоматический цикл", "Успех")
        self.current_phase = 0
        self.next_traffic_phase()

    def stop_auto_mode(self):
        self.is_auto_mode = False
        self.btn_auto_stop.setEnabled(False)
        self.btn_auto_start.setEnabled(True)
        self.traffic_timer.stop()
        self.log_to_db("Автопереключение", "Цикл остановлен пользователем", "Инфо")

    def next_traffic_phase(self):
        try:
            if not self.is_auto_mode:
                return

            # 1. Определение состояния по фазе
            # Используем две фазы: 0 -> "green", 1 -> "red"
            phase_map = {0: "green", 1: "red"}
            
            # 2. Установка равного интервала (5000 мс = 5 секунд)
            interval = 5000
            
            # Проверка, что текущая фаза существует в map
            if self.current_phase not in phase_map:
                self.current_phase = 0 # Сброс на начало, если что-то пошло не так
            
            state = phase_map[self.current_phase]

            # 3. Применение состояния к светофорам
            self.update_lights_visuals(state)

            # 4. Логирование
            self.log_to_db("Автопереключение", f"Переключение на {state.upper()} фазу (фаза {self.current_phase + 1}/2)", "Событие")

            # 5. Перезапуск таймера
            self.traffic_timer.start(interval)

            # 6. Продвижение фазы
            self.current_phase += 1
            
            # Сброс фазы. Если фаза достигла 2 (что больше 1 - последней фазы), сброс до 0
            if self.current_phase > 1: 
                self.current_phase = 0
                
        except Exception as e:
            print(f"Error in next_traffic_phase: {e}")

    def log_to_db(self, evt_type, desc, status):
        print(f"[{evt_type}] {desc} - {status}")
        
        # Логика для записи количества переключений цвета светофора (Count_color_switches)
        if evt_type == "Автопереключение" and desc.startswith("Переключение на"):
            try:
                # Увеличиваем счетчик переключений для всех светофоров
                self.cursor.execute("""
                    UPDATE Traffic_light SET Count_color_switches = Count_color_switches + 1
                """)
                self.conn.commit()
            except Exception as e:
                print(f"DB Error on log_to_db (light switch): {e}")

    def set_manual_phase(self, phase_code):
        self.show_all_static_objects()
        self.stop_auto_mode()
        self.time_mode = False
        self.time_timer.stop()
        self.transport_mode = False
        self.transport_timer.stop()
        self.failure_mode = False
        self.current_mode_label.setText("Текущий режим: Стандартный")

        desc = ""
        if phase_code == "GREEN":
            self.update_lights_visuals("green")
            self.send_light_state_to_arduino("green")  # Добавить
            desc = "Включен зеленый всем"
        elif phase_code == "YELLOW":
            self.update_lights_visuals("yellow")
            self.send_light_state_to_arduino("yellow")  # Добавить
            desc = "Включен желтый всем"
        elif phase_code == "RED":
            self.update_lights_visuals("red")
            self.send_light_state_to_arduino("red")  # Добавить
            desc = "Включен красный всем"

            self.log_to_db("Ручное управление", desc, "Успех")
            # Increment Count_color_switches for all lights
            self.cursor.execute("""
                UPDATE Traffic_light SET Count_color_switches = Count_color_switches + 1
            """)
            self.conn.commit()

    def activate_failure_mode(self):
        self.show_all_static_objects()
        self.failure_mode = True
        self.stop_auto_mode()
        self.time_mode = False
        self.time_timer.stop()
        self.transport_mode = False
        self.transport_timer.stop()
        # Clear manual states
        lights = self.get_all_traffic_lights()
        for light in lights:
            if "ManualState" in light.props:
                del light.props["ManualState"]
        self.update_lights_visuals("yellow")
        self.send_light_state_to_arduino("yellow")  # Добавить эту строку
        self.current_mode_label.setText("Текущий режим: Сбой")
        self.log_to_db("Сбой", "Активирован сбой", "Предупреждение")

    def deactivate_failure_mode(self):
        self.failure_mode = False
        self.update_lights_visuals("red")
        self.send_light_state_to_arduino("red")  # Добавить эту строку
        self.log_to_db("Сбой", "Деактивирован сбой", "Инфо")

    def read_serial(self):
        if self.serial_port and self.serial_port.in_waiting > 0:
            try:
                # Читаем все доступные байты
                available = self.serial_port.in_waiting
                data_bytes = self.serial_port.read(available)
                
                try:
                    data = data_bytes.decode('utf-8')
                    print(f"Received from Arduino: {repr(data)}")  # Для отладки
                    
                    # Ищем ключевые сообщения
                    if "HW_FAIL" in data:
                        print("Received HW_FAIL from Arduino")
                        self.activate_failure_mode()
                    elif "HW_RESET" in data:
                        print("Received HW_RESET from Arduino")
                        self.deactivate_failure_mode()
                        
                except UnicodeDecodeError:
                    print(f"Could not decode serial data: {data_bytes}")
                    
            except Exception as e:
                print(f"Serial read error: {e}")

    def send_light_state_to_arduino(self, state):
        if self.serial_port:
            try:
                if state == "red":
                    self.serial_port.write(b'1')
                elif state == "yellow":
                    self.serial_port.write(b'2')
                elif state == "green":
                    self.serial_port.write(b'3')
                elif state == "off":  # Исправлено с 'E' на правильную обработку
                    self.serial_port.write(b'0')  # Arduino выключает все светодиоды
                # Дополнительно можно добавить символ новой строки для надежности
                # self.serial_port.write(b'\n')
            except Exception as e:
                print(f"Serial write error: {e}")

    def activate_time_mode(self):
        self.show_all_static_objects()
        self.stop_auto_mode()
        self.transport_timer.stop()
        self.test_random_timer.stop()
        self.test_template_timer.stop()
        self.time_mode = True
        self.transport_mode = False
        self.failure_mode = False
        self.test_random_mode = False
        self.test_template_mode = False
        # Clear manual states
        lights = self.get_all_traffic_lights()
        for light in lights:
            if "ManualState" in light.props:
                del light.props["ManualState"]
        self.time_timer.start(5000)
        self.update_lights_visuals("green")
        self.time_mode_state = "green"
        self.current_mode_label.setText("Текущий режим: По времени")
        self.log_to_db("Режим по времени", "Активирован режим по времени", "Успех")

    def toggle_time_mode(self):
        if self.time_mode:
            if self.time_mode_state == "red":
                self.update_lights_visuals("green")
                self.time_mode_state = "green"
            else:
                self.update_lights_visuals("red")
                self.time_mode_state = "red"

    

    def random_change_lights(self):
        lights = self.get_all_traffic_lights()
        for light in lights:
            light.props["State"] = random.choice(["red", "green"])
            light.update_visuals()

    

    def activate_transport_mode(self):
        self.stop_auto_mode()
        self.transport_mode = True
        self.show_all_static_objects()
        self.time_mode = False
        self.time_timer.stop()
        self.failure_mode = False
        # Clear manual states
        lights = self.get_all_traffic_lights()
        for light in lights:
            if "ManualState" in light.props:
                del light.props["ManualState"]
        # Transport mode only controls traffic lights, doesn't affect cars
        self.transport_timer.start(500)  # Check every 500ms to match car movement
        self.current_mode_label.setText("Текущий режим: По транспорту")
        self.log_to_db("Режим по транспорту", "Активирован режим по транспорту", "Успех")

    def activate_test_template(self):
        # 1. Остановка всех конфликтующих режимов
        self.reset_db_tables()
        self.stop_auto_mode()
        self.time_mode = False
        self.time_timer.stop()
        self.transport_mode = False
        self.transport_timer.stop()
        self.failure_mode = False
        self.test_random_mode = False
        self.test_random_timer.stop()
        

        self.test_template_mode = True 

        base_file = MAP_FILE
        self.load_scene_from_file(base_file, clear_scene=True) 

        cars_file = CARS_FILE
        self.load_scene_from_file(cars_file, clear_scene=False) 


        self.show_all_static_objects()
        self.update_lights_visuals("red") 

        self.invisible_cars = []
        for item in self.scene.items():
            if isinstance(item, SceneObject) and item.obj_type == "авто" and "Path" in item.props:
                item.setOpacity(0)
                if "PathLines" in item.props:
                    for line in item.props["PathLines"]:
                        line.setVisible(False)
                self.invisible_cars.append(item)

        if self.invisible_cars:

            self.car_appear_timer.start(7000)

        # 7. Запускаем физику движения машин
        self.car_movement_timer.start(500)
        
        # 8. Обновление интерфейса
        self.current_mode_label.setText("Текущий режим: Тест-шаблон")
        self.log_to_db("Тест-шаблон", "Загружены map.json и cars.json", "Успех")

    def activate_test_random(self):
        self.reset_db_tables()  # Reset DB to avoid UNIQUE constraint errors
        self.stop_auto_mode()
        self.time_mode = False
        self.time_timer.stop()
        self.transport_mode = False
        self.transport_timer.stop()
        self.failure_mode = False
        # Clear manual states
        lights = self.get_all_traffic_lights()
        for light in lights:
            if "ManualState" in light.props:
                del light.props["ManualState"]

        # 1. Загружаем чистую карту (дороги)
        base_file = MAP_FILE # Убедитесь, что путь верный
        self.load_scene_from_file(base_file, clear_scene=True)
        self.show_all_static_objects()
        # 2. Запускаем таймер спавна машин
        self.spawn_random_car() # Спавним первую сразу

        # 3. ВАЖНО: Запускаем таймер движения, иначе машины будут стоять!
        self.car_movement_timer.start(500)

        self.random_spawn_points = []
        for item in self.scene.items():
            if isinstance(item, SceneObject) and item.obj_type.startswith("R"):
                x, y = item.x(), item.y()
                # Check if top and left are empty
                top_empty = not any(isinstance(other, SceneObject) and other.x() == x and other.y() == y - 35 for other in self.scene.items())
                left_empty = not any(isinstance(other, SceneObject) and other.x() == x - 35 and other.y() == y for other in self.scene.items())
                # For right-sided, check if right is road (assuming right is x+35)
                right_road = any(isinstance(other, SceneObject) and other.obj_type.startswith("R") and other.x() == x + 35 and other.y() == y for other in self.scene.items())
                if top_empty and left_empty and right_road:
                    self.random_spawn_points.append((x, y))
        # Start spawning timer
        self.test_random_timer.start(random.randint(2000, 5000))
        # Start light change timer
        self.test_random_light_timer.start(random.randint(2000, 5000))
        self.test_random_mode = True
        self.current_mode_label.setText("Текущий режим: Тест-рандом")
        self.log_to_db("Тест-рандом", "Активирован тест-рандом", "Успех")

    def add_test_car(self):
        if self.car_id_counter < 11:
            # Add car at fixed position for now, say (0, 0)
            props = {"Speed": 60, "Direction": "Север", "ID": self.car_id_counter}
            car = SceneObject(0, 0, "авто", props)
            self.scene.addItem(car)
            self.test_cars.append(car)
            spawn_tick = self.tick_counter # Предполагается, что self.tick_counter доступен и отсчитывает время

            # Сохраняем время спавна в свойствах объекта
            car.props["Spawn_tick"] = spawn_tick

            # ОДИН РАЗ ВСТАВЛЯЕМ запись в базу, Car_id автоинкрементируется
            self.cursor.execute(
                "INSERT INTO Cars_stats (Car_spawn_ticks) VALUES (?)",
                (spawn_tick,)
            )
            car_id = self.cursor.lastrowid
            car.props["Car_id"] = car_id
            self.conn.commit()
            self.car_id_counter += 1
        else:
            self.test_template_timer.stop()
            self.log_to_db("Тест-шаблон", "Все 11 машин добавлены", "Успех")

    def spawn_random_car(self):
        spawn_candidates = []
        grid_size = 35
        
        # Проходим по всем дорогам на сцене
        for item in self.scene.items():
            if isinstance(item, SceneObject) and item.obj_type.startswith("R"):
                # Игнорируем перекрестки для спавна, спавнимся только на прямых участках
                if item.obj_type == "Rcrossroads":
                    continue

                x, y = item.x(), item.y()
                rotation = int(item.props.get("Rotation", 0))
                
                # Логика:
                # Если дорога смотрит на Север (0), то спавн возможен, если СНИЗУ (Юг) нет дороги.
                # Если дорога смотрит на Восток (90), то спавн возможен, если СЛЕВА (Запад) нет дороги.
                # И так далее.
                
                is_edge = False
                spawn_direction = ""

                if rotation == 0: # Направлена на Север
                    if not self.has_road_at(x, y + grid_size): # Проверяем "хвост" (Юг)
                        is_edge = True
                        spawn_direction = "Север"
                
                elif rotation == 90: # Направлена на Восток
                    if not self.has_road_at(x - grid_size, y): # Проверяем "хвост" (Запад)
                        is_edge = True
                        spawn_direction = "Восток"
                
                elif rotation == 180: # Направлена на Юг
                    if not self.has_road_at(x, y - grid_size): # Проверяем "хвост" (Север)
                        is_edge = True
                        spawn_direction = "Юг"
                
                elif rotation == 270: # Направлена на Запад
                    if not self.has_road_at(x + grid_size, y): # Проверяем "хвост" (Восток)
                        is_edge = True
                        spawn_direction = "Запад"

                if is_edge:
                    # Проверяем, не занята ли точка прямо сейчас
                    if self.is_cell_free_of_cars(x, y):
                        spawn_candidates.append(((x, y), spawn_direction))

        # Если нашли места для спавна
        if spawn_candidates:
            (spawn_x, spawn_y), direction = random.choice(spawn_candidates)
            
            # Создаем авто без жесткого пути (Path), оно будет ехать само по дороге
            props = {
                "Speed": random.randint(40, 80), 
                "Direction": direction
            }
            
            car = SceneObject(spawn_x, spawn_y, "авто", props)
            car.setOpacity(1) # Делаем видимым сразу
            self.scene.addItem(car)
            
            print(f"Car spawned at {spawn_x}, {spawn_y} dir: {direction}")
            self.test_random_timer.start(random.randint(2000, 4000))
        else:
            # Если мест нет, пробуем через 1 секунду
            self.test_random_timer.start(1000)
    
    def generate_path_to_edge(self, start_x, start_y, start_direction):
        """
        Generates a path from start position to the edge of the map.
        Follows roads according to their rotation constraints.
        Rotation mapping:
        - 0 = only up (Север)
        - 90 = only right (Восток)
        - 180 = only down (Юг)
        - 270 = only left (Запад)
        
        Turn logic:
        - From Восток (right): right turn → 180°, left turn → 0°
        - From Запад (left): right turn → 0°, left turn → 180°
        - From Север (up): right turn → 90°, left turn → 270°
        - From Юг (down): right turn → 270°, left turn → 90°
        """
        path = [(start_x, start_y)]
        grid_size = 35
        scene_rect = self.scene.sceneRect()
        
        deltas = {
            "Север": (0, -grid_size),
            "Юг": (0, grid_size),
            "Запад": (-grid_size, 0),
            "Восток": (grid_size, 0)
        }
        
        # Map rotation to allowed direction
        rotation_to_direction = {
            0: "Север",
            "0": "Север",
            90: "Восток",
            "90": "Восток",
            180: "Юг",
            "180": "Юг",
            270: "Запад",
            "270": "Запад"
        }
        
        # Turn mappings: {current_direction: {turn_type: required_rotation}}
        turn_mappings = {
            "Восток": {"right": 180, "left": 0},      # Moving right: right turn → 180°, left turn → 0°
            "Запад": {"right": 0, "left": 180},       # Moving left: right turn → 0°, left turn → 180°
            "Север": {"right": 90, "left": 270},      # Moving up: right turn → 90°, left turn → 270°
            "Юг": {"right": 270, "left": 90}          # Moving down: right turn → 270°, left turn → 90°
        }
        
        current_x, current_y = start_x, start_y
        current_dir = start_direction
        max_steps = 100  # Safety limit to prevent infinite loops
        steps = 0
        
        while steps < max_steps:
            steps += 1
            
            # Get the road at current position to check its rotation
            road_rotation = self.get_road_rotation_at(current_x, current_y)
            
            # If on a road, the car must follow that road's direction
            if road_rotation is not None:
                allowed_dir = rotation_to_direction.get(road_rotation)
                if allowed_dir:
                    current_dir = allowed_dir
            
            dx, dy = deltas[current_dir]
            next_x = current_x + dx
            next_y = current_y + dy
            
            # Check if next cell is within bounds
            if not (0 <= next_x < scene_rect.width() and 0 <= next_y < scene_rect.height()):
                # Reached edge of map
                break
            
            # Check if next cell is a road
            if not self.has_road_at(next_x, next_y):
                # Check for possible turns
                next_road_rotation = self.get_road_rotation_at(next_x, next_y)
                
                if next_road_rotation is not None:
                    # Try right turn
                    right_turn_rotation = turn_mappings[current_dir]["right"]
                    if next_road_rotation == right_turn_rotation:
                        current_dir = rotation_to_direction.get(right_turn_rotation)
                        path.append((next_x, next_y))
                        current_x, current_y = next_x, next_y
                        continue
                    
                    # Try left turn
                    left_turn_rotation = turn_mappings[current_dir]["left"]
                    if next_road_rotation == left_turn_rotation:
                        current_dir = rotation_to_direction.get(left_turn_rotation)
                        path.append((next_x, next_y))
                        current_x, current_y = next_x, next_y
                        continue
                
                # Empty cell found (edge of road or boundary)
                break
            
            # Add to path and continue
            path.append((next_x, next_y))
            current_x, current_y = next_x, next_y
        
        # Path must have at least 2 points (start and at least one more)
        if len(path) > 1:
            return path
        else:
            return None
            
    def get_road_rotation_at(self, x, y):
        """
        Gets the rotation of the road at position (x, y).
        Returns the rotation value (0, 90, 180, 270) or None if no road.
        """
        items = self.scene.items(x + 10, y + 10, 15, 15, Qt.IntersectsItemShape, Qt.DescendingOrder)
        for item in items:
            if isinstance(item, SceneObject) and item.obj_type.startswith("R"):
                rotation = item.props.get("Rotation", 0)
                # Convert string to int if needed
                try:
                    rotation = int(rotation)
                except (ValueError, TypeError):
                    rotation = 0
                return rotation
        return None

    def has_road_at(self, x, y):
        # Проверяем наличие дороги в центре указанной клетки (x, y)
        # +10, +10 — смещение к центру клетки 35x35
        items = self.scene.items(x + 10, y + 10, 15, 15, Qt.IntersectsItemShape, Qt.DescendingOrder)
        for item in items:
            if isinstance(item, SceneObject) and item.obj_type.startswith("R"):
                return True
        return False

    def is_cell_free_of_cars(self, x, y):
        # Проверяет, нет ли машины в данной клетке
        items = self.scene.items(x + 10, y + 10, 15, 15, Qt.IntersectsItemShape, Qt.DescendingOrder) # Берем центр клетки
        for item in items:
            if isinstance(item, SceneObject) and item.obj_type == "авто":
                return False
        return True

    def check_transport_mode(self):
        if not self.transport_mode:
            return

        lights = self.get_all_traffic_lights()
        for light in lights:
            current_state = light.props.get("State", "red")
            new_state = "green" if self.is_vehicle_near_light(light) else "red"
            if current_state != new_state:
                light.props["State"] = new_state
                light_id = light.props.get("Id_light")
                if light_id:
                    self.cursor.execute("UPDATE Traffic_light SET Count_color_switches = Count_color_switches + 1 WHERE Id_light = ?", (light_id,))
            light.update_visuals()

    def is_vehicle_near_light(self, light):
        for item in self.scene.items():
            if isinstance(item, SceneObject) and item.obj_type == "авто":
                dx = abs(item.x() - light.x())
                dy = abs(item.y() - light.y())
                if dx <= 35 and dy <= 35:  # Neighboring cell
                    return True
        return False

    def start_drawing_path(self, item):
        self.drawing_path = True
        self.selected_car = item
        if "Path" not in item.props:
            item.props["Path"] = []
            item.props["PathLines"] = []
            item.props["PathIndex"] = 0
            item.props["PathColor"] = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        item.props["Path"].append((item.x(), item.y()))

    def start_car_movement(self):
        self.car_movement_timer.start(500)  # 0.5 seconds

    def move_cars(self):
        if not self.car_movement_timer.isActive():
            return

        grid_size = 35
        cars_to_remove = []
        
        # ... (Deltas, rot_to_dir, opposites - Оставляем как есть) ...
        deltas = {
            "Север": (0, -grid_size),
            "Юг": (0, grid_size),
            "Запад": (-grid_size, 0),
            "Восток": (grid_size, 0)
        }
        rot_to_dir = {
            0: "Север", 90: "Восток", 180: "Юг", 270: "Запад"
        }
        opposites = {"Север": "Юг", "Юг": "Север", "Запад": "Восток", "Восток": "Запад"}
        
        cars = [item for item in self.scene.items() if isinstance(item, SceneObject) and item.obj_type == "авто"]

        for car in cars:
            if car.opacity() != 1: continue

            # 1. Car ID и Spawn Tick (Cars_stats) <<< НОВАЯ ЛОГИКА
            if "Car_id" not in car.props:
                # Получаем текущий ID
                current_car_id = self.car_id_counter

                # Присваиваем ID машине
                car.props["Car_id"] = current_car_id

                # Увеличиваем счетчик для следующей машины
                self.car_id_counter += 1

                # Запись Car_spawn_ticks при первом движении (Используем INSERT OR REPLACE для избежания дубликатов)
                # Car_exit_ticks устанавливается в NULL (просто передаем None, который SQlite преобразует в NULL)
                self.cursor.execute(
                    "INSERT OR REPLACE INTO Cars_stats (Car_id, Car_spawn_ticks, Car_exit_ticks) VALUES (?, ?, ?)",
                    (current_car_id, self.tick_counter, None) # Передаем None для Car_exit_ticks
                )
                self.conn.commit()
            
            # --- Если есть нарисованный путь (тест-шаблон), используем его ---
            if "Path" in car.props and len(car.props["Path"]) > 1:
                # В случае движения по Path (шаблон), статистика проезда учитывается в move_car_along_path.
                self.move_car_along_path(car)
                continue

            # --- ЛОГИКА "УМНОГО" ДВИЖЕНИЯ (Look Ahead) ---
            curr_x, curr_y = car.x(), car.y()
            curr_dir = car.props.get("Direction", "Север")
            
            # ... (2. Формируем список возможных направлений) ...
            potential_dirs = ["Север", "Юг", "Запад", "Восток"]
            if curr_dir in opposites:
                potential_dirs.remove(opposites[curr_dir])

            valid_moves = []

            # ... (3. Проверяем каждого соседа) ...
            for p_dir in potential_dirs:
                dx, dy = deltas[p_dir]
                check_x = curr_x + dx
                check_y = curr_y + dy
                
                # Ищем дорогу в проверяемой клетке
                items_there = self.scene.items(check_x + 10, check_y + 10, 10, 10, Qt.IntersectsItemShape, Qt.DescendingOrder)
                road_item = None
                for it in items_there:
                    if isinstance(it, SceneObject) and it.obj_type.startswith("R"):
                        road_item = it
                        break
                
                if not road_item:
                    continue

                # АНАЛИЗ ДОРОГИ ВПЕРЕДИ
                can_enter = False
                
                if road_item.obj_type == "Rcrossroads":
                    can_enter = True
                elif road_item.obj_type == "Rvertical":
                    road_rot = int(road_item.props.get("Rotation", 0))
                    allowed_road_dir = rot_to_dir.get(road_rot, "Север")
                    
                    if allowed_road_dir == p_dir:
                        can_enter = True
                
                if can_enter:
                    valid_moves.append(p_dir)

            # 4. Выбор направления из доступных
            next_dir = curr_dir 
            
            if not valid_moves:
                cars_to_remove.append(car) # Помечаем на удаление (Тупик)
                continue 
            
            # Приоритет: Ехать прямо
            if curr_dir in valid_moves:
                weighted_choices = valid_moves + [curr_dir] * 8 
                next_dir = random.choice(weighted_choices)
            else:
                next_dir = random.choice(valid_moves)

            # 5. Расчет целевых координат
            dx, dy = deltas[next_dir]
            target_x = curr_x + dx
            target_y = curr_y + dy

            # 6. Проверки препятствий (как и раньше)
            scene_rect = self.scene.sceneRect()
            if not scene_rect.contains(target_x + 10, target_y + 10):
                cars_to_remove.append(car) # Помечаем на удаление (Выезд за город)
                continue
                
            if not self.is_cell_free_of_cars(target_x, target_y):
                continue
            
            if self.is_red_light(target_x, target_y, next_dir):
                continue
                
            if self.is_pedestrian_on_crossing(target_x, target_y):
                continue
            
            if self.is_road_blocked(target_x, target_y):
                continue

            # 7. Движение и Учет Проезда
            
            # *** Учет проезда через перекресток (Traffic_light) - Car_count_full_run ***
            # Если целевая ячейка - перекресток (Rcrossroads), учитываем проезд.
            # Находим перекресток
            target_items = self.scene.items(target_x + 10, target_y + 10, 10, 10, Qt.IntersectsItemShape, Qt.DescendingOrder)
            is_crossroad = any(isinstance(it, SceneObject) and it.obj_type == "Rcrossroads" for it in target_items)
            
            if is_crossroad:
                # Находим ближайший светофор, чтобы привязать статистику
                closest_light = None
                min_dist_sq = float('inf')
                
                # Ищем светофоры только рядом с перекрестком
                for light in self.get_all_traffic_lights():
                    dist_sq = (light.x() - target_x)**2 + (light.y() - target_y)**2
                    # Привязываем к светофору, находящемуся в непосредственной близости от перекрестка
                    if dist_sq < min_dist_sq and dist_sq < (GRID_SIZE * 2)**2: 
                        min_dist_sq = dist_sq
                        closest_light = light

                if closest_light:
                    light_id = closest_light.props.get("Id_light", 0)
                    # Обновление Car_count_full_run
                    self.cursor.execute("""
                        UPDATE Traffic_light SET Car_count_full_run = Car_count_full_run + 1
                        WHERE Id_light = ?
                    """, (light_id,))
                    # Коммит не нужен в цикле, сделаем один раз после всех удалений
                    # self.conn.commit() 
            # ------------------------------------------------------------------------

            # 8. Физическое перемещение
            car.setPos(target_x, target_y)
            car.props["Direction"] = next_dir
            car.update_visuals()

        # Удаление машин и фиксация Car_exit_ticks
        for car in cars_to_remove:
            car_id = car.props.get("Car_id")
            if car_id is not None:
                # 2. Car Exit Tick (Cars_stats) <<< НОВАЯ ЛОГИКА
                self.cursor.execute(
                    "UPDATE Cars_stats SET Car_exit_ticks = ? WHERE Car_id = ?",
                    (self.tick_counter, car_id)
                )
            
            # Удаление из сцены
            self.scene.removeItem(car)
            
        # Коммит всех изменений в БД после цикла
        if cars_to_remove:
            self.conn.commit()

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ ПРОВЕРКИ ПРАВИЛ ---
    def is_traffic_light_red(self, car):
        # Проверяем небольшой квадрат перед машиной.
        # Размер области поиска должен быть примерно равен GRID_SIZE
        search_distance = GRID_SIZE * 1.5 
        
        # Получаем текущие координаты и вращение машины
        x, y = car.x(), car.y()
        rotation = car.props.get("Rotation", 0)

        # Вычисляем область поиска немного впереди машины (упрощенно)
        # Вращение машины (rotation) должно соответствовать направлению движения
        
        # Переводим угол в радианы для sin/cos
        angle_rad = (rotation - 90) * (3.14159 / 180) 
        
        # Смещаем центр поиска немного вперед по направлению движения
        search_x = x + search_distance * math.cos(angle_rad)
        search_y = y + search_distance * math.sin(angle_rad)

        # Ищем объекты в небольшой области вокруг точки (search_x, search_y)
        items = self.scene.items(search_x, search_y, GRID_SIZE, GRID_SIZE, Qt.IntersectsItemShape, Qt.DescendingOrder)
        
        for item in items:
            if isinstance(item, SceneObject) and item.obj_type == "светофор":
                light_state = item.props.get("State", "red")
                if light_state in ["red"]:
                    # Дополнительная проверка: убедиться, что светофор "смотрит" на машину
                    light_rotation = item.props.get("Rotation", 0)
                    # Если разница углов (с поправкой на 180 градусов, т.к. машина едет НА светофор)
                    # находится в допустимом диапазоне, считаем сигнал релевантным.
                    if abs((rotation - light_rotation + 180) % 360 - 180) < 45: 
                         return True # Светофор красный (или желтый) и релевантный
        return False
    def move_car_along_path(self, item):
        # Ваш существующий код движения по пути (copy-paste логики из вашего move_cars)
        path = item.props["Path"]
        path_index = item.props.get("PathIndex", 0)
        if path_index < len(path) - 1:
            next_index = path_index + 1
            next_x, next_y = path[next_index]
            current_x, current_y = item.x(), item.y()
            dx = next_x - current_x
            dy = next_y - current_y
            move_x = 0
            move_y = 0
            direction = item.props.get("Direction", "Север")

            if dx > 0:
                move_x = 35; direction = "Восток"
            elif dx < 0:
                move_x = -35; direction = "Запад"
            elif dy > 0:
                move_y = 35; direction = "Юг"
            elif dy < 0:
                move_y = -35; direction = "Север"

            # Check for red light at the position we're about to move to
            new_x = current_x + move_x
            new_y = current_y + move_y
            if self.is_red_light(new_x, new_y, direction):
                #print(f"[PATH] Car at ({current_x}, {current_y}) stopped at red light at ({new_x}, {new_y}), direction={direction}")
                return  # Do not move if red light

            item.props["Direction"] = direction
            item.setPos(new_x, new_y)
            item.update_visuals()

            if item.x() == next_x and item.y() == next_y:
                item.props["PathIndex"] = next_index

    def move_pedestrians(self):
        # Animation removed for pedestrians
        pass

    def is_valid_pedestrian_move(self, x, y):
        # Check if on road or crossing
        items = self.scene.items(x + 5, y + 5, 10, 10, Qt.IntersectsItemShape, Qt.DescendingOrder)
        has_road = any(isinstance(it, SceneObject) and it.obj_type.startswith("R") for it in items)
        if not has_road:
            return False
        # Check no car
        has_car = any(isinstance(it, SceneObject) and it.obj_type == "авто" for it in items)
        if has_car:
            return False
        # Check bounds
        scene_rect = self.scene.sceneRect()
        if not scene_rect.contains(x + 10, y + 10):
            return False
        return True

    def is_red_light(self, x, y, direction):
        # Ищем светофор в точке x,y
        # Use larger detection area (35x35) to properly detect traffic lights
        items = self.scene.items(x + 5, y + 5, 30, 30, Qt.IntersectsItemShape, Qt.DescendingOrder)
        for item in items:
            if isinstance(item, SceneObject) and item.obj_type == "светофор":
                # Default to "red" if State is not set (initial state)
                state = item.props.get("State", "red")
                if state == "red" or state == "yellow":
                    return True
        return False

    def is_pedestrian_on_crossing(self, x, y):
        # 1. Проверяем, являемся ли мы пешеходным переходом
        items_here = self.scene.items(x + 10, y + 10, 10, 10, Qt.IntersectsItemShape, Qt.DescendingOrder)
        is_zebra = False
        for item in items_here:
            if isinstance(item, SceneObject) and item.obj_type == "пешеходный переход":
                is_zebra = True
                break

        if not is_zebra:
            return False

        # 2. Если зебра, ищем пешехода РЯДОМ (на самой зебре или у края)
        # Расширяем зону поиска немного
        nearby_items = self.scene.items(x - 5, y - 5, 45, 45, Qt.IntersectsItemShape, Qt.DescendingOrder)
        for item in nearby_items:
            if isinstance(item, SceneObject) and item.obj_type == "пешеход":
                return True
        return False

    def is_road_blocked(self, x, y):
        items = self.scene.items(x + 10, y + 10, 10, 10, Qt.IntersectsItemShape, Qt.DescendingOrder)
        for item in items:
            if isinstance(item, SceneObject) and item.obj_type == "движение запрещено":
                prop_type = item.props.get("Type", "Stop")
                if prop_type in ["Stop", "Block"]: # Stop запрещает въезд
                    return True
        return False

    def show_random_car(self):
        if self.invisible_cars:
            car = random.choice(self.invisible_cars)
            car.setOpacity(1)
            if "PathLines" in car.props:
                for line in car.props["PathLines"]:
                    line.setVisible(True)
            self.invisible_cars.remove(car)
        else:
            self.car_appear_timer.stop()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Q:
            if self.drawing_path:
                self.drawing_path = False
                self.selected_car = None
                print("Path drawing stopped and saved.")
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def run_tests(self):
        print("Starting database tests...")
        self.activate_test_template()
        # Wait 10 seconds for template test to populate, then check DB
        QTimer.singleShot(10000, self.check_db_after_template)
        # Then activate random test
        QTimer.singleShot(15000, self.activate_test_random)
        # Wait another 10 seconds, then check DB
        QTimer.singleShot(25000, self.check_db_after_random)
        # Finish tests
        QTimer.singleShot(30000, self.finish_tests)

    def check_db_after_template(self):
        print("Checking DB after test-template...")
        self.cursor.execute("SELECT * FROM Traffic_light")
        lights = self.cursor.fetchall()
        print("Traffic_light table contents:")
        for row in lights:
            print(row)
        self.cursor.execute("SELECT * FROM Cars_stats")
        cars = self.cursor.fetchall()
        print("Cars_stats table contents:")
        for row in cars:
            print()

    def check_db_after_random(self):
        print("Checking DB after test-random...")
        self.cursor.execute("SELECT * FROM Traffic_light")
        lights = self.cursor.fetchall()
        print("Traffic_light table contents:")
        for row in lights:
            print(row)
        self.cursor.execute("SELECT * FROM Cars_stats")
        cars = self.cursor.fetchall()
        print("Cars_stats table contents:")
        for row in cars:
            print()

    def finish_tests(self):
        print("Database tests finished.")
        self.conn.close()
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run tests without GUI
        editor = RoadEditor()
        editor.run_tests()
        sys.exit(app.exec_())
    else:
        window = RoadEditor()
        window.show()
        sys.exit(app.exec_())
