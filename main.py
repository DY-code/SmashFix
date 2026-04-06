# main.py
# -------------------------------------------------------------
# Ubuntu 22.04 适配说明：
# 1. Wayland 环境下强制使用 xcb，确保 libVLC 可嵌入 Qt 窗口
# 2. app.exec_() 改为 app.exec() (PySide6 标准)
# -------------------------------------------------------------
import os
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow


def configure_linux_runtime():
    """在 Ubuntu 22.04 上优先使用 X11 后端，兼容 VLC 视频嵌入。"""
    if not sys.platform.startswith("linux"):
        return

    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main():
    configure_linux_runtime()
    app = QApplication(sys.argv)
    try:
        win = MainWindow()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "启动失败",
            "程序启动失败，请确认 Ubuntu 22.04 已安装文档中的系统依赖。\n\n"
            f"错误信息：{exc}",
        )
        sys.exit(1)

    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
