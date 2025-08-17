#!/usr/bin/env python3
"""
QMI 로그 파서 애플리케이션 실행 파일
"""
import sys
import os
import tkinter as tk

# src 폴더를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from qmi_gui import QMIParserGUI


def main():
    """애플리케이션 진입점"""
    # tkinterdnd2 설치 여부 확인 및 import
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk()

        def setup_drag_drop_advanced(gui_instance):
            gui_instance.root.drop_target_register(DND_FILES)
            gui_instance.root.dnd_bind('<<Drop>>', gui_instance.on_file_drop_advanced)

        def on_file_drop_advanced(self, event):
            files = event.data.split()
            if files:
                file_path = files[0].strip('{}')  # 중괄호 제거
                self.set_file_path(file_path)

        # 고급 드래그 앤 드롭 메서드 추가
        QMIParserGUI.on_file_drop_advanced = on_file_drop_advanced
        QMIParserGUI.setup_drag_drop = setup_drag_drop_advanced

    except ImportError:
        # tkinterdnd2가 없으면 기본 tkinter 사용
        root = tk.Tk()

    app = QMIParserGUI(root)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        root.quit()


if __name__ == "__main__":
    main()