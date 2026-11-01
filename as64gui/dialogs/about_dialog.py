from PyQt6 import QtCore, QtGui, QtWidgets

from ..constants import (
    VERSION,
    AUTHOR,
    ABOUT_PATH,
    TITLE,
    GITHUB_REPO,
)
from as64core import resource_utils


class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.width = 420
        self.height = 320
        self.title = "About AutoSplit64+"

        self.background = QtWidgets.QLabel(parent=self)
        
        self.title_lb = QtWidgets.QLabel(TITLE, parent=self)
        self.ver_title_lb = QtWidgets.QLabel("Version:", parent=self)
        self.ver_lb = QtWidgets.QLabel(VERSION, parent=self)
        self.author_title_lb = QtWidgets.QLabel("Authors:", parent=self)
        self.author_lb = QtWidgets.QLabel(AUTHOR, parent=self)
        self.github_btn = QtWidgets.QPushButton("Open GitHub", parent=self)

        self.initialize_window()

    def initialize_window(self):
        self.setFixedSize(self.width, self.height)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint | 
            QtCore.Qt.WindowType.WindowStaysOnTopHint | 
            QtCore.Qt.WindowType.Dialog
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(self.title)

        # Configure Widgets
        self.background.setPixmap(QtGui.QPixmap(resource_utils.resource_path(ABOUT_PATH)))
        
        title_font = QtGui.QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        
        label_font = QtGui.QFont()
        label_font.setPointSize(10)
        
        self.title_lb.setFont(title_font)
        self.ver_title_lb.setFont(label_font)
        self.ver_lb.setFont(label_font)
        self.author_title_lb.setFont(label_font)
        self.author_lb.setFont(label_font)
        self.github_btn.setFont(title_font)

        self.background.move(0, 10)
        # Text block sits in the dark panel on the right; keep it high enough
        # that a three-line Authors list (upstream + Linux port) stays inside it.
        self.title_lb.move(275, 72)
        self.ver_title_lb.move(275, 104)
        self.ver_lb.move(275, 124)
        self.author_title_lb.move(275, 152)
        self.author_lb.move(275, 172)
        self.github_btn.move(272, 272)

        self.github_btn.clicked.connect(
            lambda: self._open_url(f"https://github.com/{GITHUB_REPO}")
        )

    def _open_url(self, url):
        # QDesktopServices.openUrl shells out to xdg-open, which often isn't
        # found from inside an AppImage; fall back to Python's webbrowser so the
        # link actually opens.
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

    def mousePressEvent(self, e):
        self.close()
