# main.py
# -------------------------------------------------------------
# 修改说明：
# 1. 导入改为 PySide6.QtWidgets
# 2. app.exec_() 改为 app.exec() (PySide6 标准)
# -------------------------------------------------------------
import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    # PySide6 中 exec_() 已被弃用，使用 exec()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()