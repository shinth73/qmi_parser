"""
QMI 파서의 GUI 인터페이스
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font
import os
import sys
import threading
from datetime import datetime

# 상대 import 대신 절대 import 사용
try:
    from qmi_processor import QMILogProcessor
except ImportError:
    # src 폴더 내에서 실행되는 경우
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from qmi_processor import QMILogProcessor


class QMIParserGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("QMI 로그 파서")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 600)

        # 변수 초기화
        self.file_path = None
        self.processor = QMILogProcessor()
        self.is_processing = False
        self.last_combined_result = ""
        self.last_parsed_result = ""

        self.setup_ui()
        self.setup_drag_drop()

    def setup_ui(self):
        """UI 구성 요소 초기화"""
        # 메인 프레임
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 그리드 가중치 설정
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=3)  # 입력 영역
        main_frame.columnconfigure(1, weight=4)  # 출력 영역
        main_frame.rowconfigure(1, weight=1)     # 메인 콘텐츠 영역

        # 상단 파일 선택 영역 (크기 축소)
        self.setup_file_selection(main_frame)

        # 좌측 입력 영역
        self.setup_input_area(main_frame)

        # 우측 출력 영역
        self.setup_output_area(main_frame)

        # 하단 상태 표시줄
        self.setup_status_bar(main_frame)

    def setup_file_selection(self, parent):
        """파일 선택 영역 설정 (크기 축소)"""
        file_frame = ttk.LabelFrame(parent, text="파일 처리", padding="5")
        file_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        parent.columnconfigure(0, weight=1)

        # 드래그 앤 드롭 영역 (높이 축소)
        self.drop_label = tk.Label(file_frame,
                                   text="파일을 드래그 앤 드롭하거나 찾기 버튼 클릭",
                                   relief=tk.RAISED,
                                   bd=1,
                                   height=2,
                                   bg="#f0f0f0")
        self.drop_label.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 5))

        # 파일 경로 표시 및 버튼들
        self.file_path_var = tk.StringVar()
        self.file_label = ttk.Entry(file_frame, textvariable=self.file_path_var, state="readonly")
        self.file_label.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        browse_button = ttk.Button(file_frame, text="파일 찾기", command=self.browse_file)
        browse_button.grid(row=1, column=1, sticky=tk.W, padx=(5, 0), pady=(0, 5))

        self.process_button = ttk.Button(file_frame, text="파일 처리", command=self.process_file)
        self.process_button.grid(row=1, column=2, sticky=tk.W, padx=(5, 0), pady=(0, 5))

        file_frame.columnconfigure(0, weight=1)

    def setup_input_area(self, parent):
        """좌측 입력 영역 설정"""
        input_frame = ttk.LabelFrame(parent, text="Raw Data 입력", padding="10")
        input_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(1, weight=1)

        # 입력 버튼들
        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        button_frame.columnconfigure(3, weight=1)

        insert_sample_button = ttk.Button(button_frame, text="샘플 예제", command=self.insert_sample_data)
        insert_sample_button.grid(row=0, column=0, sticky=tk.W)

        clear_input_button = ttk.Button(button_frame, text="입력값 삭제", command=self.clear_raw_input)
        clear_input_button.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))

        process_text_button = ttk.Button(button_frame, text="디코딩", command=self.process_raw_data)
        process_text_button.grid(row=0, column=2, sticky=tk.W, padx=(5, 0))

        # 텍스트 입력 영역
        text_frame = ttk.Frame(input_frame)
        text_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 0))
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.raw_input = tk.Text(text_frame, wrap=tk.WORD, font=('Consolas', 9))
        scrollbar_input = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.raw_input.yview)
        self.raw_input.configure(yscrollcommand=scrollbar_input.set)

        self.raw_input.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar_input.grid(row=0, column=1, sticky=(tk.N, tk.S))

    def setup_output_area(self, parent):
        """우측 출력 영역 설정"""
        output_frame = ttk.LabelFrame(parent, text="처리 결과", padding="10")
        output_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(2, weight=1)

        # 출력 버튼들
        button_frame = ttk.Frame(output_frame)
        button_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        button_frame.columnconfigure(4, weight=1)

        show_combined_button = ttk.Button(button_frame, text="통합 결과",
                                          command=lambda: self.show_output('combined'))
        show_combined_button.grid(row=0, column=0, sticky=tk.W)

        show_parsed_button = ttk.Button(button_frame, text="파싱 결과",
                                        command=lambda: self.show_output('parsed'))
        show_parsed_button.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))

        clear_output_button = ttk.Button(button_frame, text="출력 지우기", command=self.clear_output)
        clear_output_button.grid(row=0, column=2, sticky=tk.W, padx=(5, 0))

        save_button = ttk.Button(button_frame, text="결과 저장", command=self.save_output)
        save_button.grid(row=0, column=3, sticky=tk.W, padx=(5, 0))

        # 로그/출력 탭
        self.output_notebook = ttk.Notebook(output_frame)
        self.output_notebook.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 0))

        # 처리 로그 탭
        log_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(log_frame, text="처리 로그")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, font=('Consolas', 9), bg='#f8f8f8')
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 출력 결과 탭
        output_result_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(output_result_frame, text="출력 결과")
        output_result_frame.columnconfigure(0, weight=1)
        output_result_frame.rowconfigure(0, weight=1)

        self.output_text = tk.Text(output_result_frame, wrap=tk.WORD, font=('Consolas', 9))
        output_scrollbar = ttk.Scrollbar(output_result_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=output_scrollbar.set)

        self.output_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        output_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

    def setup_status_bar(self, parent):
        """하단 상태 표시줄 설정"""
        status_frame = ttk.Frame(parent)
        status_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        status_frame.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="준비")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var,
                                      relief=tk.SUNKEN, anchor=tk.W, padding=(5, 2))
        self.status_label.grid(row=0, column=0, sticky=(tk.W, tk.E))

    def insert_sample_data(self):
        """샘플 데이터 삽입"""
        sample_data = """07-31 15:27:15.795 radio 10981 11030 D RILD    : RIL-RAWDATA: 01 0C 00 00 03 00 00 72 01 43 00 00 00 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 01 CE 00 80 03 00 02 72 01 43 00 C2 00 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 02 04 00 00 00 00 00 13 1D 00 00 54 F0 50 05 27 23 94 44 00 C4 09 7B 00 00 00 00 00 01 7B 00 AC 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: FF 2B FD 0F FE 00 00 14 1E 00 00 03 22 0B 00 00 00 00 13 01 00 00 00 01 7B 00 97 FF 64 FC 26 FD 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 00 46 05 00 00 00 00 15 02 00 00 00 16 02 00 00 00 1E 04 00 07 00 00 00 26 02 00 05 00 27 04 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 C4 09 00 00 28 0D 00 03 22 0B 00 00 13 01 00 00 46 05 00 00 2A 04 00 03 00 00 00 2C 04 00 01 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 00 00 2D 04 00 04 00 00 00 30 2C 00 00 04 22 0B 00 00 00 00 00 00 13 01 00 00 00 00 00 01 7B 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 97 FF 64 FC 26 FD 00 00 46 05 00 00 00 00 00 00 80 0C 00 00 00 00 00 00 32 06 00 34 35 30 30 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 35 FF """

        self.raw_input.delete('1.0', tk.END)
        self.raw_input.insert('1.0', sample_data)
        self.log("샘플 데이터가 입력되었습니다.")

    def setup_drag_drop(self):
        """기본 드래그 앤 드롭 설정"""
        self.drop_label.bind("<Button-1>", self.on_drop_click)
        self.drop_label.bind("<B1-Motion>", self.on_drag)
        self.drop_label.bind("<ButtonRelease-1>", self.on_drop)

    def on_drop_click(self, event):
        """드래그 시작"""
        pass

    def on_drag(self, event):
        """드래그 중"""
        pass

    def on_drop(self, event):
        """드롭 완료"""
        pass

    def on_file_drop(self, event):
        """파일 드롭 이벤트 처리"""
        pass

    def browse_file(self):
        """파일 선택 대화상자"""
        file_path = filedialog.askopenfilename(
            title="QMI 로그 파일 선택",
            filetypes=[
                ("텍스트 파일", "*.txt"),
                ("로그 파일", "*.log"),
                ("모든 파일", "*.*")
            ]
        )
        if file_path:
            self.set_file_path(file_path)

    def set_file_path(self, file_path):
        """선택된 파일 경로 설정"""
        self.file_path = file_path
        self.file_path_var.set(file_path)
        self.drop_label.config(text=f"선택된 파일: {os.path.basename(file_path)}", bg="#e8f5e8")
        self.log(f"파일 선택됨: {os.path.basename(file_path)}")

    def clear_raw_input(self):
        """원시 입력 데이터 지우기"""
        self.raw_input.delete('1.0', tk.END)
        self.log("입력 데이터가 지워졌습니다.")

    def clear_output(self):
        """출력 텍스트와 캐시된 결과를 모두 지움"""
        # 텍스트 위젯 내용 지우기
        self.output_text.delete("1.0", tk.END)

        # 캐시된 결과도 모두 지우기
        self.last_combined_result = ""
        self.last_parsed_result = ""

        # 로그에도 기록
        self.log("출력 내용을 지웠습니다.")

    def clear_all(self):
        """모든 출력 지우기"""
        self.output_text.delete('1.0', tk.END)
        self.log_text.delete('1.0', tk.END)
        self.last_combined_result = ""
        self.last_parsed_result = ""
        self.log("모든 출력이 지워졌습니다.")

    def log(self, message):
        """로그 메시지 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"

        # 로그 탭에 메시지 추가
        self.log_text.insert(tk.END, log_message)
        self.log_text.see(tk.END)

        # 상태 표시줄 업데이트
        self.status_var.set(message)

        # UI 업데이트
        self.root.update_idletasks()

    def show_output(self, output_type='combined'):
        """처리 결과를 출력 영역에 표시"""
        try:
            self.output_text.delete("1.0", tk.END)

            if output_type == 'combined':
                if self.last_combined_result:
                    self.output_text.insert("1.0", self.last_combined_result)
                else:
                    self.output_text.insert("1.0", "표시할 통합 결과가 없습니다.")
            elif output_type == 'parsed':
                if self.last_parsed_result:
                    self.output_text.insert("1.0", self.last_parsed_result)
                else:
                    self.output_text.insert("1.0", "표시할 파싱 결과가 없습니다.")

            # 텍스트 시작 부분으로 스크롤
            self.output_text.see("1.0")

            # 노트북 탭을 출력 탭으로 변경
            if hasattr(self, 'output_notebook'):
                self.output_notebook.select(1)  # 출력 탭 선택

        except Exception as e:
            error_msg = f"출력 표시 중 오류 발생: {e}"
            self.log(error_msg)
            messagebox.showerror("오류", error_msg)

    def save_output(self):
        """출력 결과를 파일로 저장"""
        if not self.last_combined_result and not self.last_parsed_result:
            messagebox.showwarning("경고", "저장할 결과가 없습니다. 먼저 파싱을 실행하세요.")
            return

        try:
            # 현재 표시된 텍스트 가져오기
            current_text = self.output_text.get("1.0", tk.END).strip()
            if not current_text:
                messagebox.showwarning("경고", "저장할 내용이 없습니다.")
                return

            # 파일 저장 대화상자
            file_path = filedialog.asksaveasfilename(
                title="결과 저장",
                defaultextension=".txt",
                filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")]
            )

            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(current_text)

                messagebox.showinfo("성공", f"파일이 저장되었습니다:\n{file_path}")
                self.log(f"결과를 파일에 저장했습니다: {file_path}")

        except Exception as e:
            error_msg = f"파일 저장 중 오류 발생: {e}"
            messagebox.showerror("오류", error_msg)
            self.log(error_msg)

    def processing_finished(self, result):
        """처리 완료 후 호출되는 콜백 함수"""
        try:
            self.is_processing = False
            self.process_button.config(state='normal')

            if result and 'combined' in result and 'parsed_only' in result:
                # 결과 저장 (캐시)
                self.last_combined_result = result['combined']
                self.last_parsed_result = result['parsed_only']

                # 통합 결과 표시
                self.show_output('combined')

                # 성공 메시지
                stats = result.get('stats', {})
                lines = stats.get('lines', 0)
                packets = stats.get('packets', 0)

                success_msg = f"Raw Data 처리 완료!\n라인: {lines:,}, 패킷: {packets:,}"
                self.update_status(success_msg)
                self.log(success_msg)

            else:
                error_msg = "처리 결과가 비어있거나 잘못된 형식입니다."
                self.update_status(f"처리 실패: {error_msg}")
                self.log(error_msg)

        except Exception as e:
            error_msg = f"처리 완료 콜백에서 오류 발생: {e}"
            self.update_status(f"오류: {error_msg}")
            self.log(error_msg)

    def update_status(self, message):
        """상태 업데이트 (스레드에서 안전하게 호출 가능)"""
        def update():
            self.status_var.set(message)
            self.root.update_idletasks()

        self.root.after(0, update)

    def process_raw_data(self):
        """Raw Data 텍스트 처리"""
        input_text = self.raw_input.get('1.0', tk.END).strip()
        if not input_text:
            messagebox.showwarning("경고", "처리할 텍스트가 없습니다.")
            return

        if self.is_processing:
            messagebox.showwarning("경고", "이미 처리 중입니다.")
            return

        # 스레드에서 처리
        thread = threading.Thread(target=self.process_raw_data_thread, args=(input_text,))
        thread.daemon = True
        thread.start()

    def process_raw_data_thread(self, input_text):
        """Raw Data 처리 스레드"""
        try:
            self.is_processing = True
            self.root.after(0, lambda: self.update_status("텍스트 처리 중..."))
            self.root.after(0, lambda: self.log("Raw Data 텍스트 처리를 시작합니다..."))

            # 처리 시작
            result = self.processor.process_qmi_text(input_text, progress_callback=self.log)

            # 결과 저장
            self.last_combined_result = result['combined']
            self.last_parsed_result = result['parsed_only']

            # 파싱 결과를 출력창에 바로 표시
            def show_result():
                self.output_text.delete('1.0', tk.END)
                self.output_text.insert('1.0', self.last_parsed_result)
                self.output_notebook.select(1)  # 출력 결과 탭 선택

            self.root.after(0, show_result)

            # 성공 메시지
            stats = result['stats']
            success_msg = (f"Raw Data 처리 완료! "
                           f"라인: {stats['lines']}, 패킷: {stats['packets']}")

            self.root.after(0, lambda: self.log(success_msg))

        except Exception as e:
            error_msg = f"Raw Data 처리 중 오류: {str(e)}"
            self.root.after(0, lambda: self.log(error_msg))
            self.root.after(0, lambda: messagebox.showerror("오류", error_msg))
        finally:
            self.is_processing = False
            self.root.after(0, lambda: self.update_status("준비"))

    def process_file(self):
        """파일 처리"""
        if not self.file_path:
            messagebox.showwarning("경고", "파일을 선택하세요.")
            return

        if not os.path.exists(self.file_path):
            messagebox.showerror("오류", "선택한 파일이 존재하지 않습니다.")
            return

        if self.is_processing:
            messagebox.showwarning("경고", "이미 처리 중입니다.")
            return

        # 출력 파일 경로 생성
        base_path = os.path.splitext(self.file_path)[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        combined_file_path = f"{base_path}_combined_{timestamp}.txt"
        parsed_only_file_path = f"{base_path}_parsed_{timestamp}.txt"

        # 처리 시작 확인
        if not messagebox.askyesno("확인",
                                   f"다음 파일을 처리하시겠습니까?\n\n"
                                   f"입력: {os.path.basename(self.file_path)}\n"
                                   f"출력1: {os.path.basename(combined_file_path)}\n"
                                   f"출력2: {os.path.basename(parsed_only_file_path)}"):
            return

        # 스레드에서 처리 실행
        thread = threading.Thread(
            target=self.process_file_thread,
            args=(self.file_path, combined_file_path, parsed_only_file_path)
        )
        thread.daemon = True
        thread.start()

    def process_file_thread(self, input_path, combined_path, parsed_path):
        """파일 처리 스레드"""
        try:
            self.is_processing = True
            self.root.after(0, lambda: self.update_status("파일 처리 중..."))
            self.root.after(0, lambda: self.log("파일 처리를 시작합니다..."))

            # 파일 처리 실행
            self.processor.process_qmi_log(
                input_path, combined_path, parsed_path,
                progress_callback=self.log
            )

            # 처리 완료 후 결과 파일 읽기
            try:
                with open(combined_path, 'r', encoding='utf-8') as f:
                    self.last_combined_result = f.read()
                with open(parsed_path, 'r', encoding='utf-8') as f:
                    self.last_parsed_result = f.read()

                # 파싱 결과를 출력창에 바로 표시
                def show_result():
                    self.output_text.delete('1.0', tk.END)
                    self.output_text.insert('1.0', self.last_parsed_result)
                    self.output_notebook.select(1)  # 출력 결과 탭 선택

                self.root.after(0, show_result)

            except Exception as e:
                self.root.after(0, lambda: self.log(f"결과 파일 읽기 실패: {e}"))

            # 완료 메시지
            success_msg = (f"파일 처리 완료!\n\n"
                           f"통합 결과: {combined_path}\n"
                           f"파싱 결과: {parsed_path}")

            self.root.after(0, lambda: self.log("파일 처리가 완료되었습니다."))
            self.root.after(0, lambda: messagebox.showinfo("완료", success_msg))

        except Exception as e:
            error_msg = f"파일 처리 중 오류: {str(e)}"
            self.root.after(0, lambda: self.log(error_msg))
            self.root.after(0, lambda: messagebox.showerror("오류", error_msg))
        finally:
            self.is_processing = False
            self.root.after(0, lambda: self.update_status("준비"))

    def processing_finished(self):
        """처리 완료 후 호출"""
        self.is_processing = False
        self.update_status("처리 완료")