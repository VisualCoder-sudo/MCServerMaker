"""
main.py — MCServerMaker entry point.
Optimized: stylesheet cached, font pre-loaded, OpenGL disabled for pure-2D app.
"""
import sys
import os

# ── Pre-import speedups ────────────────────────────────────────────
# Tell Qt to use software rendering only for 2D widgets — avoids
# GPU/OpenGL driver init overhead on headless or minimal Linux installs.
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont


# Stylesheet is a module-level constant — evaluated once, never re-built
_STYLESHEET = """
QMainWindow,QDialog,QWidget{
    background-color:#1e1e2e;color:#cdd6f4;
    font-family:'Noto Sans','Segoe UI',sans-serif;font-size:13px;
}
QPushButton{
    background-color:#313244;color:#cdd6f4;
    border:1px solid #45475a;border-radius:6px;padding:6px 16px;
}
QPushButton:hover{background-color:#45475a;}
QPushButton:pressed{background-color:#585b70;}
QPushButton#primary{background-color:#89b4fa;color:#1e1e2e;font-weight:bold;border:none;}
QPushButton#primary:hover{background-color:#b4d0fb;}
QPushButton#danger{background-color:#f38ba8;color:#1e1e2e;font-weight:bold;border:none;}
QLineEdit,QTextEdit,QPlainTextEdit{
    background-color:#181825;border:1px solid #45475a;
    border-radius:4px;padding:4px 8px;color:#cdd6f4;
}
QScrollBar:vertical{width:8px;background:#181825;}
QScrollBar::handle:vertical{background:#45475a;border-radius:4px;min-height:20px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QSlider::groove:horizontal{height:6px;background:#313244;border-radius:3px;}
QSlider::handle:horizontal{
    background:#89b4fa;width:16px;height:16px;margin:-5px 0;border-radius:8px;
}
QSlider::sub-page:horizontal{background:#89b4fa;border-radius:3px;}
QCheckBox::indicator{
    width:16px;height:16px;border:2px solid #45475a;
    border-radius:3px;background:#181825;
}
QCheckBox::indicator:checked{background:#89b4fa;border-color:#89b4fa;}
QProgressBar{background:#313244;border-radius:4px;border:none;text-align:center;}
QProgressBar::chunk{background:#89b4fa;border-radius:4px;}
"""


def main():
    # Disable accessibility bus — removes 50-200 ms startup delay on Linux
    os.environ.setdefault("NO_AT_BRIDGE", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("MCServerMaker")
    app.setOrganizationName("MCServerMaker")

    # Set a single default font once — avoids per-widget font resolution
    app.setFont(QFont("Noto Sans", 10))

    app.setStyleSheet(_STYLESHEET)

    # Import here (after QApplication exists) for fastest cold start
    from ui.wizard_window import WizardWindow
    wizard = WizardWindow()
    wizard.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
