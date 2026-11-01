import os
import logging
from functools import partial
import re
import requests
import json
from PyQt6 import QtCore, QtGui, QtWidgets
from as64core import route_loader, config, livesplit
from as64core.resource_utils import base_path, resource_path, absolute_path, rel_to_abs, abs_to_rel
from . import constants
from .widgets import PictureButton, StateButton, StarCountDisplay, SplitListWidget
from .dialogs import AboutDialog, CaptureEditor, SettingsDialog, RouteEditor, ResetGeneratorDialog, OutputDialog

class App(QtWidgets.QMainWindow):
    start = QtCore.pyqtSignal()
    stop = QtCore.pyqtSignal()
    closed = QtCore.pyqtSignal()
    _update_available = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        self.autostarter_active = False
        super().__init__(parent=parent)

        # Window Properties
        self.title = constants.TITLE
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.width = 365
        self.height = 259
        self.setWindowIcon(QtGui.QIcon(base_path(constants.ICON_PATH)))

        # Dragging
        self._drag = False
        self._drag_position = None

        # Pixmaps
        self.start_pixmap = QtGui.QPixmap(base_path(constants.START_PATH))
        self.stop_pixmap = QtGui.QPixmap(base_path(constants.STOP_PATH))
        self.init_pixmap = QtGui.QPixmap(base_path(constants.INIT_PATH))

        # Widgets
        self.central_widget = QtWidgets.QWidget(self)
        self.star_count = StarCountDisplay(parent=self.central_widget)
        self.star_btn = PictureButton(QtGui.QPixmap(base_path(constants.STAR_PATH)),
                                      pixmap_pressed=QtGui.QPixmap(base_path(constants.STAR_HOVER_PATH)),
                                      pixmap_hover=QtGui.QPixmap(base_path(constants.STAR_HOVER_PATH)),
                                      parent=self.central_widget)
        self.start_btn_initial_x = 206
        self.start_btn_initial_y = 180
        self.start_btn = StateButton(self.start_pixmap, self.start_pixmap, parent=self.central_widget)
        self.split_list = SplitListWidget(self.central_widget)

        # SRL-mode badge: hidden unless SRL Mode is on. SRL Mode silently stops
        # the splitter from resetting/starting the timer, so make it visible.
        self.srl_indicator = QtWidgets.QLabel("SRL MODE", self.central_widget)
        self.srl_indicator.setStyleSheet(
            "QLabel { background-color: rgba(200, 40, 40, 220); color: white;"
            " font-weight: bold; font-size: 10px; padding: 2px 5px;"
            " border-radius: 3px; }")
        self.srl_indicator.setToolTip(
            "SRL (race) Mode is on: the splitter will not reset or start your "
            "timer automatically. Toggle it in the right-click menu.")
        self.srl_indicator.hide()

        # Font
        self.button_font = QtGui.QFont("Tw Cen MT", 14)
        self.start_count_font = QtGui.QFont("Tw Cen MT", 20)

        # Route
        self.route = None

        # Dialogs
        self.dialogs = {
            "about_dialog": AboutDialog(self),
            "capture_editor": CaptureEditor(self),
            "settings_dialog": SettingsDialog(self),
            "route_editor": RouteEditor(self),
            "reset_dialog": ResetGeneratorDialog(self),
            "output_dialog": OutputDialog(self)
        }

        self._routes = {}
        self._load_route_dir()

        self.initialize()
        self.show()
        
        # Run the update check off the main thread so a slow or blocked network
        # never delays startup; the popup (if any) is marshalled back to the GUI
        # thread via the _update_available signal.
        self._update_available.connect(self.display_update_message)
        if config.get("general", "update_check"):
            import threading
            threading.Thread(target=self.update_check, daemon=True).start()
        
        # Handle splash screen closure
        try:
            import pyi_splash # type: ignore
            pyi_splash.close()
        except (ImportError, ModuleNotFoundError):
            pass
        
        QtCore.QTimer.singleShot(100, self.autostart)
        

    def set_always_on_top(self, on_top):
        if on_top:
            self.setWindowFlags(QtCore.Qt.WindowType.MSWindowsFixedSizeDialogHint | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(QtCore.Qt.WindowType.MSWindowsFixedSizeDialogHint)

        self.show()

    def initialize(self):
        # Configure window
        self.setWindowTitle(self.title)

        if config.get("general", "on_top"):
            self.setWindowFlags(QtCore.Qt.WindowType.MSWindowsFixedSizeDialogHint | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        else:
        #     self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
            self.setWindowFlags(QtCore.Qt.WindowType.MSWindowsFixedSizeDialogHint)

        self.setFixedSize(self.width, self.height)

        # Restore the last window position (opt-in). Only applied if it still
        # lands on a currently-connected screen, so a saved position from an
        # unplugged monitor can't drop the window off-screen.
        self._restore_window_position()

        # Configure Central Widget
        self.central_widget.setObjectName("central_widget")

        self.central_widget.setStyleSheet(r"QWidget#central_widget{background-image: url(" +
                                          resource_path(constants.BACKGROUND_PATH) +
                                          "); background-attachment: fixed;}")
        self.setCentralWidget(self.central_widget)

        # Configure Other Widgets
        self.star_btn.move(242, 35)

        self.star_count.setFixedWidth(150)
        self.star_count.move(197, 115)
        self.star_count.setFont(self.start_count_font)
        self.star_count.star_count = "-"
        self.star_count.split_star = "-"

        self.start_btn.move(self.start_btn_initial_x, self.start_btn_initial_y)
        # self.start_btn.setFont(self.button_font)
        # self.start_btn.setStyleSheet("font-weight: bold; color: black; font-size: 32px;")
        self.start_btn.add_state("start", self.start_pixmap, "")
        self.start_btn.add_state("stop", self.stop_pixmap, "")
        self.start_btn.add_state("init", self.init_pixmap, "")
        self.start_btn.set_state("start")
        
        # Add hover effects
        self.start_btn.enterEvent = lambda e: self._on_start_btn_hover(True)
        self.start_btn.leaveEvent = lambda e: self._on_start_btn_hover(False)

        self.split_list.setFont(self.button_font)
        self.split_list.setFixedSize(183, self.height)
        self.split_list.move(0, 0)

        self._update_srl_indicator()

        self.open_route()

        # Connections
        self.start_btn.clicked.connect(self.start_clicked)
        self.star_btn.clicked.connect(self._reset)
        self.dialogs["route_editor"].route_updated.connect(self._on_route_update)
        self.dialogs["settings_dialog"].applied.connect(self.settings_updated)
        self.dialogs["capture_editor"].applied.connect(self._reset)
 
    def _update_srl_indicator(self):
        """Show/hide the SRL-mode badge based on config, pinned top-right."""
        if config.get("general", "srl_mode"):
            self.srl_indicator.adjustSize()
            self.srl_indicator.move(self.width - self.srl_indicator.width() - 8, 8)
            self.srl_indicator.show()
            self.srl_indicator.raise_()
        else:
            self.srl_indicator.hide()

    def settings_updated(self):
        self.set_always_on_top(config.get("general", "on_top"))
        self._reset()

    def update_display(self, split_index, current_star, split_star):
        if split_index > len(self.split_list.splits) - 1:
            index = len(self.split_list.splits) - 1
        else:
            index = split_index

        self.split_list.set_selected_index(index)
        self.star_count.star_count = current_star
        self.star_count.split_star = split_star

    def autostart(self):
        if config.get("general", "auto_start") and self.start_btn.get_state() == "start":
            self.autostarter_active = True
            self.start_btn.set_state("init")
            
            # While autostarter is active, try every 2000ms to start the timer
            self.counter = 0
            def try_start():
                if self.autostarter_active:
                    self.start.emit()
                    QtCore.QTimer.singleShot(2000, try_start)
            try_start()
            # Quit the autostarter after trying for 5 minutes
            def quit_autostarter():
                if self.autostarter_active:
                    self.autostarter_active = False
                    self.start_btn.set_state("start")
                    self.stop.emit()
                    self.display_error_message("Failed to auto start timer.", "AutoStart Error")
            QtCore.QTimer.singleShot(300000, quit_autostarter)

    def start_clicked(self):
        if self.start_btn.get_state() == "stop" or self.start_btn.get_state() == "init":
            self.autostarter_active = False
            self.start_btn.set_state("start")
            self.split_list.set_selected_index(0)
            if self.route:
                self.star_count.star_count = self.route.initial_star
                self.star_count.split_star = self.route.splits[0].star_count
            self.stop.emit()
        elif self.start_btn.get_state() == "start":
            # A run cannot start without a route loaded -- warn instead of
            # entering the init state and crashing in the start thread.
            if not self.route:
                self.display_error_message(
                    "Load or create a route before starting.\n\n"
                    "Right-click -> Open Route, or Edit Route to make one.",
                    "No Route Loaded")
                return
            self.start_btn.set_state("init")
            self.start.emit()

    def set_started(self, started):
        if started:
            self.start_btn.set_state("stop")
            self.autostarter_active = False
        elif self.autostarter_active:
            pass
        else:
            self.start_btn.set_state("start")
            # TODO: Set split list index to 0?

        self.start_btn.repaint()

    def open_route(self):
        self._reset()

        if config.get("route", "path") == "":
            return

        #try:
        route = route_loader.load(config.get("route", "path"))
        # except KeyError:
        #     self.display_error_message("Key Error", "Route Error")
        #     return False

        if not route:
            self.display_error_message("Could not load route", "Route Error")
            self._load_route_dir()
            config.set_key("route", "path", "")
            config.save_config()
            return False

        error = route_loader.validate_route(route)

        if error:
            self.display_error_message(error, "Route Error")
            return False

        self.route = route

        self.split_list.clear()
        self.star_count.star_count = route.initial_star
        self.star_count.split_star = route.splits[0].star_count

        for split in route.splits:
            split_icon_path = split.icon_path

            if split_icon_path:
                split_icon_path = rel_to_abs(split_icon_path)
                icon = QtGui.QPixmap(split_icon_path)
            else:
                icon = None

            self.split_list.add_split(split.title, icon)

        self.split_list.repaint()

        return True

    def open_route_browser(self):
        """ Show native file dialog to select a .route file for use. """
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Route", absolute_path("routes"),
                                                             "AS64 Route Files (*.as64)")

        if file_path:
            self._save_open_route(file_path)

    def contextMenuEvent(self, event):
        context_menu = QtWidgets.QMenu(self)
        route_menu = QtWidgets.QMenu("Open Route")
        route_actions = {}
        category_menus = {}

        # SRL MODE Action
        srl_action = QtGui.QAction("SRL Mode", self, checkable=True)
        context_menu.addAction(srl_action)
        srl_action.setChecked(config.get("general", "srl_mode"))
        context_menu.addSeparator()

        for category in sorted(self._routes, key=lambda text:[int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]):
            if len(self._routes[category]) == 1 or category == "":
                for route in self._routes[category]:
                    route_menu.addAction(route[0])
                    route_actions[route[0]] = partial(self._save_open_route, route[1])
            else:
                category_menus[category] = QtWidgets.QMenu(str(category))
                route_menu.addMenu(category_menus[category])

                for route in self._routes[category]:
                    category_menus[category].addAction(route[0])
                    route_actions[route[0]] = partial(self._save_open_route, route[1])

        route_menu.addSeparator()
        file_action = route_menu.addAction("From File")

        # Actions
        edit_route = context_menu.addAction("Edit Route")
        context_menu.addMenu(route_menu)
        context_menu.addSeparator()
        cords_action = context_menu.addAction("Edit Coordinates")
        context_menu.addSeparator()
        advanced_action = context_menu.addAction("Settings")
        context_menu.addSeparator()
        reset_gen_action = context_menu.addAction("Generate Reset Templates")
        context_menu.addSeparator()
        output_action = context_menu.addAction("Show Output")
        context_menu.addSeparator()
        popout_action = context_menu.addAction("Pop Out LiveSplit View")
        context_menu.addSeparator()
        autostart_action = QtGui.QAction("Autostart", self, checkable=True)
        context_menu.addAction(autostart_action)
        autostart_action.setChecked(config.get("general", "auto_start"))
        context_menu.addSeparator()
        about_action = context_menu.addAction("About")
        context_menu.addSeparator()
        exit_action = context_menu.addAction("Exit")

        action = context_menu.exec(self.mapToGlobal(event.pos()))

        # Connections
        if action == srl_action:
            checked = srl_action.isChecked()
            config.set_key("general", "srl_mode", checked)
            config.save_config()
            self._update_srl_indicator()
        elif action == edit_route:
            self.dialogs["route_editor"].show()
        elif action == file_action:
            self.open_route_browser()
        elif action == cords_action:
            self.dialogs["capture_editor"].show()
            try:
                self.dialogs["output_dialog"].close()
            except AttributeError:
                pass
        elif action == advanced_action:
            self.dialogs["settings_dialog"].show()
        elif action == reset_gen_action:
            self.dialogs["reset_dialog"].show()
        elif action == output_action:
            self.dialogs["output_dialog"].show()
        elif action == popout_action:
            self._pop_out_livesplit()
        elif action == autostart_action:
            checked = autostart_action.isChecked()
            config.set_key("general", "auto_start", checked)
            config.save_config()
            self.autostart()
        elif action == about_action:
            self.dialogs["about_dialog"].show()
        elif action == exit_action:
            self.close()
        else:
            try:
                route_actions[action.text()]()
            except (KeyError, AttributeError):
                pass

    def mousePressEvent(self, event):
        if event.buttons() == QtCore.Qt.MouseButton.LeftButton:
            self._drag = True
            self._drag_position = event.globalPosition().toPoint() - self.pos()
            event.accept()

        self.dialogs["about_dialog"].close()

    def mouseReleaseEvent(self, event):
        if event.buttons() == QtCore.Qt.MouseButton.LeftButton:
            self._drag = False
            event.accept()

    def mouseMoveEvent(self, event):
        try:
            if event.buttons() == QtCore.Qt.MouseButton.LeftButton:
                try:
                    self.move(event.globalPosition().toPoint() - self._drag_position)
                except TypeError:
                    pass
                event.accept()
        except AttributeError:
            pass

    def display_error_message(self, message, title="Error"):
        """
        Display a warning dialog with given title and message
        :param title: Window title
        :param message: Warning/error message
        :return:
        """
        if self.autostarter_active:
            return
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.exec()

    def display_update_message(self, version):
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Update Available")
        msg.setText(f"A new version of AutoSplit 64+ is available!\n\nCurrent Version: {constants.VERSION}\nLatest Version: {version}")
        
        # Create custom icon label
        icon_label = QtWidgets.QLabel()
        pixmap = QtGui.QPixmap(base_path(constants.STAR_HOVER_PATH))
        icon_label.setPixmap(pixmap)
        layout = msg.layout()
        layout.addWidget(icon_label, 0, 0, 1, 1, QtCore.Qt.AlignmentFlag.AlignCenter)
        msg.addButton("Ignore", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        download_btn = msg.addButton("Download", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        
        def on_button_clicked(button):
            if button == download_btn:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(f"https://github.com/{constants.GITHUB_REPO}/releases/latest"))

        msg.buttonClicked.connect(on_button_clicked)
        msg.exec()

    def parse_version(self, version_str):
        version = version_str.lstrip('v')
        return [int(x) for x in version.split('.')]

    def update_check(self):
        # Runs on a background thread (see __init__). Must not touch Qt widgets
        # directly; emit _update_available to show any popup on the GUI thread.
        try:
            response = requests.get(
                f"https://api.github.com/repos/{constants.GITHUB_REPO}/releases/latest",
                timeout=5,
            )
            response.raise_for_status()
            data = json.loads(response.text)
            latest_version = data["tag_name"]

            if self.parse_version(latest_version) > self.parse_version(constants.VERSION):
                self._update_available.emit(latest_version)
        except Exception as e:
            logging.error(f"Update check failed: {str(e)}")
            return None

    def _load_route_dir(self):
        self._routes = {}

        # Resolve the bundled routes directory against the app root so this
        # works regardless of the current working directory (AppImage/.desktop
        # launch). Paths stored in self._routes stay *relative* so they survive
        # the AppImage mounting at a different /tmp path on each launch.
        routes_dir = absolute_path("routes")
        if not os.path.isdir(routes_dir):
            return

        for file in os.listdir(routes_dir):
            if file.endswith(".as64"):
                rel_path = "routes/" + file
                route = route_loader.load(rel_path)

                if route:
                    category = route.category
                    self._routes.setdefault(category, []).append([route.title, rel_path])

    def _on_route_update(self):
        self._load_route_dir()
        self.open_route()

    def _save_open_route(self, file_path):
        # Store routes that live inside the app tree as relative paths; an
        # AppImage mounts at a different /tmp path each launch, so an absolute
        # path into the bundle would be stale next time. Paths outside the app
        # tree (a user's own file) are left absolute.
        file_path = abs_to_rel(file_path)
        prev_route = config.get("route", "path")
        config.set_key("route", "path", file_path)
        config.save_config()
        success = self.open_route()

        if success:
            return
        else:
            config.set_key("route", "path", prev_route)
            config.save_config()
            self.open_route()

    def _reset(self):
        if self.start_btn.get_state() == "stop":
            self._stop()
            self.start_btn.set_state("init")
            self.start.emit()
        else:
            self._stop()

    def _stop(self):
        self.stop.emit()
        self.set_started(False)

    def close(self):
        import time
        try:
            self.dialogs["output_dialog"].close()
            time.sleep(0.1)
        except AttributeError:
            pass

        self.stop.emit()
        super().close()
        
    def closeEvent(self, event):
        self._save_window_position()
        self.close()
        event.accept()

    def _save_window_position(self):
        if not config.get("general", "remember_window_position"):
            return
        try:
            pos = self.pos()
            config.set_key("general", "window_position", [pos.x(), pos.y()])
            config.save_config()
        except Exception:
            pass

    def _restore_window_position(self):
        if not config.get("general", "remember_window_position"):
            return
        try:
            saved = config.get("general", "window_position")
            if not saved or len(saved) != 2:
                return
            point = QtCore.QPoint(int(saved[0]), int(saved[1]))
            # Only restore if the saved position is on a screen that exists now.
            frame = QtCore.QRect(point, self.size())
            for screen in QtWidgets.QApplication.screens():
                if screen.availableGeometry().intersects(frame):
                    self.move(point)
                    return
        except Exception:
            pass

    def _pop_out_livesplit(self):
        """Open a windowed LiveSplit projector in OBS at the saved geometry."""
        sock = livesplit.connect()
        if sock is False:
            err = livesplit.connection_error() or "Could not connect to the timer."
            QtWidgets.QMessageBox.warning(self, "Pop Out LiveSplit View", err)
            return
        try:
            livesplit.open_projector(sock, self._projector_geometry_b64())
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Pop Out LiveSplit View", str(e))
        finally:
            livesplit.disconnect(sock)

    def _projector_geometry_b64(self):
        """Build the Qt base64 geometry OBS wants from the configured rect."""
        try:
            rect = config.get("connection", "obs_projector_geometry")
            if not rect or len(rect) != 4:
                return None
            holder = QtWidgets.QWidget()
            holder.setGeometry(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
            return bytes(holder.saveGeometry().toBase64()).decode("ascii")
        except Exception:
            return None

    def _on_start_btn_hover(self, hovering):
        if hovering:
            scale = 1.1
        else:
            scale = 1.0
        
        # Resize button
        new_width = int(self.start_pixmap.width() * scale)
        new_height = int(self.start_pixmap.height() * scale)
        self.start_btn.setFixedSize(new_width, new_height)
        
        # Move button relative to its initial position
        new_x = self.start_btn_initial_x - (new_width - self.start_pixmap.width()) // 2
        new_y = self.start_btn_initial_y - (new_height - self.start_pixmap.height()) // 2
        self.start_btn.move(new_x, new_y)
