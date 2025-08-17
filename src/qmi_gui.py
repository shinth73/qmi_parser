import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font
import os
import sys
import threading
from datetime import datetime
import win32com.client
import struct
import re
import io
import json

# QMI.py의 상수들 (실제 QMI.py에서 가져온 값들)
LOG_PACKET_DEFAULT = "24 00 8F 13 00 00 9A 9E CD 7B C2 00"
QCAT_MODEL_NUMBER = 165
MAX_BUFFER_BYTES_PER_LINE = 32
MAX_OUTPUT_BUF_SIZE = ((MAX_BUFFER_BYTES_PER_LINE * 3) + 2)
CONFIG_FILE = "qmi_parser_config.json"


def process_qmi_packet(qcat_app, combined_fh, parsed_only_fh, log_packet, log_timestamp=""):
    """
    원본 QMI.py의 process_qmi_packet 함수와 동일. 타임스탬프 교체 기능 추가.
    """
    byte_strings = [s for s in log_packet.split() if s]
    if not byte_strings:
        return

    try:
        hex_bytes = [int(b, 16) for b in byte_strings]
    except ValueError as e:
        print(f"Error converting hex string to bytes: {e}")
        print(f"Skipping problematic packet: {log_packet}")
        return

    # The first two bytes of the log packet must contain the total length
    # in little-endian format for QCAT to process it correctly.
    total_length = len(hex_bytes)
    hex_bytes[0] = total_length & 0xFF
    hex_bytes[1] = (total_length >> 8) & 0xFF

    # Pack the bytes into a binary format (array of unsigned chars)
    packet = struct.pack(f'{total_length}B', *hex_bytes)

    # Process the packet with QCAT
    qcat_app.Model = QCAT_MODEL_NUMBER
    parsed_object = qcat_app.ProcessPacket(packet)

    if parsed_object is None:
        print(f"QCAT failed to process a packet. Error: {qcat_app.LastError}")
    else:
        parsed_text = parsed_object.Text
        # log_timestamp가 있으면 QCAT 헤더를 타임스탬프로 교체 시도
        if log_timestamp:
            # QCAT header format: 2013 Feb  5 10:20:30.123 [AB] 0x1234  QMI Link 1 TX PDU
            qcat_header_pattern = r'\d{4}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+[[.{2,8}]\s+0x....\s+QMI Link 1 TX PDU'
            replacement = f"""--------------------------------------------------\ntimestamp {log_timestamp}"""
            new_text, count = re.subn(qcat_header_pattern, replacement, parsed_text, count=1)
            if count > 0:
                parsed_text = new_text
            else:
                # 패턴이 일치하지 않으면 기존 방식으로 대체
                replacement_fallback = f"""--------------------------------------------------\ntimestamp {log_timestamp} builded. Parsed by QCAT"""
                parsed_text = re.sub(
                    r' ([0-9]{2}):([0-9]{2}):([0-9]{2}\.[0-9]{1,9})\s+[[.{2,8}]\s+(0x....)  QMI Link 1 TX PDU',
                    replacement_fallback,
                    parsed_text
                )
        else:
            # 타임스탬프가 없으면 기존 방식으로 동작
            parsed_text = re.sub(
                r' ([0-9]{2}):([0-9]{2}):([0-9]{2}\.[0-9]{1,9})\s+[[.{2,8}]\s+(0x....)  QMI Link 1 TX PDU',
                'builded. Parsed by QCAT',
                parsed_text
            )

        if parsed_text and parsed_text.strip():
            for line in parsed_text.splitlines():
                if line.strip():
                    line_with_newline = line + '\n'
                    combined_fh.write(line_with_newline)
                    parsed_only_fh.write(line_with_newline)


class QMILogProcessor:
    """QMI 로그 처리를 위한 클래스"""

    def __init__(self):
        self.qcat_app = None

    def process_qmi_text(self, input_text, progress_callback=None):
        """
        텍스트 입력을 파일과 동일한 방식으로 처리하고 결과를 반환
        """
        try:
            # QCAT 애플리케이션 시작
            if self.qcat_app is None:
                self.qcat_app = win32com.client.Dispatch('QCAT6.Application')
                if progress_callback:
                    progress_callback(f"QCAT 버전: {self.qcat_app.AppVersion}")
                    progress_callback(f"SILK 버전: {self.qcat_app.SILKVersion}\n")

            # 출력을 메모리에 저장
            combined_output = io.StringIO()
            parsed_only_output = io.StringIO()

            # 입력 텍스트를 라인별로 처리 (파일과 동일한 방식)
            log_packet = LOG_PACKET_DEFAULT
            qmi_packet_accum_length = 0
            qmi_packet_expected_length = 0
            is_accumulating = False
            log_timestamp = ""
            line_count = 0
            processed_packets = 0

            lines = input_text.strip().split('\n')
            total_lines = len(lines)

            if progress_callback:
                progress_callback(f"총 {total_lines}라인 처리 시작", 0)

            for txt_line in lines:
                line_count += 1

                # 진행률 업데이트
                if line_count % 10 == 0 and progress_callback:
                    progress = int((line_count / total_lines) * 100)
                    progress_callback(f"처리 중... {progress}% (라인: {line_count}, 패킷: {processed_packets})", progress)

                # 원본 라인을 combined 출력에 기록 (빈 라인이 아닌 경우)
                if txt_line.strip():
                    combined_output.write(txt_line + '\n')

                is_data_line = re.search(r'RIL-RAWDATA..[0-9,A-F]{2} ', txt_line)

                if is_data_line:
                    if not is_accumulating:
                        try:
                            log_timestamp = " ".join(txt_line.split()[:2])
                        except IndexError:
                            log_timestamp = ""
                    is_accumulating = True
                    split_data = txt_line.split(':')
                    if len(split_data) > 1:
                        hex_chunk = split_data[-1].strip()
                        log_packet += f" {hex_chunk}"

                        try:
                            chunk_bytes = bytes.fromhex(hex_chunk)
                            # The first data chunk contains the expected length of the QMI message.
                            if qmi_packet_expected_length == 0 and len(chunk_bytes) > 2:
                                qmi_packet_expected_length = chunk_bytes[1] + (chunk_bytes[2] << 8)

                            qmi_packet_accum_length += (len(chunk_bytes) - 1)

                        except ValueError:
                            if progress_callback:
                                progress_callback(f"경고: 16진수 문자열 디코딩 실패: {txt_line.strip()}", None)

                elif is_accumulating:
                    process_qmi_packet(self.qcat_app, combined_output, parsed_only_output, log_packet, log_timestamp)
                    processed_packets += 1
                    # Reset state
                    log_packet = LOG_PACKET_DEFAULT
                    qmi_packet_accum_length = 0
                    qmi_packet_expected_length = 0
                    is_accumulating = False
                    log_timestamp = ""

                if is_accumulating and (
                        (qmi_packet_expected_length > 0 and qmi_packet_accum_length >= qmi_packet_expected_length) or
                        (qmi_packet_accum_length >= MAX_OUTPUT_BUF_SIZE)
                ):
                    process_qmi_packet(self.qcat_app, combined_output, parsed_only_output, log_packet, log_timestamp)
                    processed_packets += 1
                    # Reset state
                    log_packet = LOG_PACKET_DEFAULT
                    qmi_packet_accum_length = 0
                    qmi_packet_expected_length = 0
                    is_accumulating = False
                    log_timestamp = ""

            # 마지막 패킷 처리
            if is_accumulating:
                if progress_callback:
                    progress_callback("텍스트 끝 도달, 마지막 누적 패킷 처리 중...", None)
                process_qmi_packet(self.qcat_app, combined_output, parsed_only_output, log_packet, log_timestamp)
                processed_packets += 1

            if progress_callback:
                progress_callback(f"\n처리 완료: {line_count}라인, {processed_packets}패킷 처리됨", 100)

            # 결과 반환
            combined_result = combined_output.getvalue()
            parsed_only_result = parsed_only_output.getvalue()

            return {
                'combined': combined_result,
                'parsed_only': parsed_only_result,
                'stats': {
                    'lines': line_count,
                    'packets': processed_packets
                }
            }

        except Exception as e:
            error_msg = f"텍스트 처리 중 오류 발생: {e}"
            if "pywintypes.com_error" in str(type(e)):
                error_msg += "\nQCAT이 올바르게 설치되거나 등록되지 않았을 수 있습니다."
            if self.qcat_app:
                error_msg += f"\nQCAT 마지막 오류: {self.qcat_app.LastError}"

            if progress_callback:
                progress_callback(error_msg, None)
            raise e

    def process_qmi_log(self, dump_file_path, combined_file_path, parsed_only_file_path, progress_callback=None):
        """
        QMI 로그 파일을 파싱하는 메인 함수 (원본 QMI.py 로직 사용)
        """
        try:
            # QCAT 애플리케이션 시작
            self.qcat_app = win32com.client.Dispatch('QCAT6.Application')
            if progress_callback:
                progress_callback(f"QCAT 버전: {self.qcat_app.AppVersion}", 0)
                progress_callback(f"SILK 버전: {self.qcat_app.SILKVersion}\n", 0)

            with open(dump_file_path, 'r', encoding='utf-8', errors='ignore') as dump_fh, \
                    open(combined_file_path, 'w', encoding='utf-8') as combined_fh, \
                    open(parsed_only_file_path, 'w', encoding='utf-8') as parsed_only_fh:

                log_packet = LOG_PACKET_DEFAULT
                qmi_packet_accum_length = 0
                qmi_packet_expected_length = 0
                is_accumulating = False
                log_timestamp = ""
                line_count = 0
                processed_packets = 0

                # 파일 크기 계산 (진행률 표시용)
                try:
                    file_size = os.path.getsize(dump_file_path)
                    if progress_callback:
                        progress_callback(f"파일 크기: {file_size:,} bytes", 0)
                except Exception:
                    file_size = 0

                # 총 라인 수 계산 (진행률 표시 개선)
                total_lines = 0
                if progress_callback:
                    progress_callback("파일 라인 수 계산 중...", 0)
                    with open(dump_file_path, 'r', encoding='utf-8', errors='ignore') as count_fh:
                        total_lines = sum(1 for _ in count_fh)
                    progress_callback(f"총 {total_lines:,} 라인", 0)

                dump_fh.seek(0)  # 파일 포인터를 처음으로 되돌림

                for txt_line in dump_fh:
                    line_count += 1

                    # 진행률 업데이트 (100라인마다)
                    if line_count % 100 == 0 and progress_callback and total_lines > 0:
                        progress = int((line_count / total_lines) * 100)
                        progress_callback(f"처리 중... {progress}% (라인: {line_count:,}, 패킷: {processed_packets})", progress)

                    # 원본 라인을 combined 파일에 기록 (빈 라인이 아닌 경우)
                    if txt_line.strip():
                        combined_fh.write(txt_line)

                    is_data_line = re.search(r'RIL-RAWDATA..[0-9,A-F]{2} ', txt_line)

                    if is_data_line:
                        if not is_accumulating:
                            try:
                                log_timestamp = " ".join(txt_line.split()[:2])
                            except IndexError:
                                log_timestamp = ""
                        is_accumulating = True
                        split_data = txt_line.split(':')
                        if len(split_data) > 1:
                            hex_chunk = split_data[-1].strip()
                            log_packet += f" {hex_chunk}"

                            try:
                                chunk_bytes = bytes.fromhex(hex_chunk)
                                # 첫 번째 데이터 청크에는 QMI 메시지의 예상 길이가 포함됨
                                if qmi_packet_expected_length == 0 and len(chunk_bytes) > 2:
                                    qmi_packet_expected_length = chunk_bytes[1] + (chunk_bytes[2] << 8)

                                qmi_packet_accum_length += (len(chunk_bytes) - 1)

                            except ValueError:
                                if progress_callback:
                                    progress_callback(f"경고: 16진수 문자열 디코딩 실패: {txt_line.strip()}", None)

                    elif is_accumulating:
                        process_qmi_packet(self.qcat_app, combined_fh, parsed_only_fh, log_packet, log_timestamp)
                        processed_packets += 1
                        # 상태 초기화
                        log_packet = LOG_PACKET_DEFAULT
                        qmi_packet_accum_length = 0
                        qmi_packet_expected_length = 0
                        is_accumulating = False
                        log_timestamp = ""

                    if is_accumulating and (
                            (
                                    qmi_packet_expected_length > 0 and qmi_packet_accum_length >= qmi_packet_expected_length) or
                            (qmi_packet_accum_length >= MAX_OUTPUT_BUF_SIZE)
                    ):
                        process_qmi_packet(self.qcat_app, combined_fh, parsed_only_fh, log_packet, log_timestamp)
                        processed_packets += 1
                        # 상태 초기화
                        log_packet = LOG_PACKET_DEFAULT
                        qmi_packet_accum_length = 0
                        qmi_packet_expected_length = 0
                        is_accumulating = False
                        log_timestamp = ""

                # 마지막 패킷 처리
                if is_accumulating:
                    if progress_callback:
                        progress_callback("파일 끝 도달, 마지막 누적 패킷 처리 중...", None)
                    process_qmi_packet(self.qcat_app, combined_fh, parsed_only_fh, log_packet, log_timestamp)
                    processed_packets += 1

                if progress_callback:
                    progress_callback(f"\n처리 완료: {line_count:,}라인, {processed_packets}패킷 처리됨", 100)

        except Exception as e:
            error_msg = f"오류 발생: {e}"
            if "pywintypes.com_error" in str(type(e)):
                error_msg += "\nQCAT이 올바르게 설치되거나 등록되지 않았을 수 있습니다."
            if self.qcat_app:
                error_msg += f"\nQCAT 마지막 오류: {self.qcat_app.LastError}"

            if progress_callback:
                progress_callback(error_msg, None)
            raise e

        finally:
            # COM 객체 해제 (단일 패킷 처리에서는 해제하지 않음)
            pass


class QMIParserGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("QMI Log Parser")
        self.root.geometry("1280x800")
        self.root.minsize(1000, 700)

        # --- 색상 및 폰트 정의 ---
        self.colors = {
            "bg": "#282c34",
            "bg_light": "#3e4451",
            "bg_dark": "#21252b",
            "fg": "#abb2bf",
            "primary": "#61afef",
            "secondary": "#98c379",
            "danger": "#e06c75",
            "warning": "#e5c07b",
            "info": "#56b6c2",
            "highlight": "#e5c07b",
        }
        self.fonts = {
            "title": ("맑은 고딕", 16, "bold"),
            "header": ("맑은 고딕", 11, "bold"),
            "body": ("맑은 고딕", 10),
            "button": ("맑은 고딕", 10, "bold"),
            "monospace": ("Consolas", 10),
        }
        
        self.root.configure(bg=self.colors["bg"])

        # 아이콘 설정 시도
        try:
            self.root.iconbitmap(default='icon.ico')
        except:
            pass

        # 스타일 설정
        self.setup_styles()

        # 변수 초기화
        self.file_path = None
        self.processor = QMILogProcessor()
        self.is_processing = False
        self.cancel_processing = False
        self.original_texts = {}
        self.regex_var = tk.BooleanVar()

        # 설정 불러오기 및 종료 시 저장 바인딩
        self.load_config()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # UI 설정
        self.setup_ui()
        self.setup_drag_drop()

    def setup_styles(self):
        """UI 스타일 설정"""
        style = ttk.Style()
        style.theme_use('clam')

        # --- 기본 스타일 ---
        style.configure('.', 
                        background=self.colors["bg"], 
                        foreground=self.colors["fg"],
                        font=self.fonts["body"],
                        bordercolor=self.colors["bg_light"],
                        lightcolor=self.colors["bg_light"],
                        darkcolor=self.colors["bg_dark"])
        style.configure('TFrame', background=self.colors["bg"])
        style.configure('TCheckbutton', background=self.colors["bg"], foreground=self.colors["fg"])
        style.map('TCheckbutton', 
                  background=[('active', self.colors["bg"])],
                  indicatorcolor=[('selected', self.colors["primary"]), ('pressed', self.colors["primary"])])

        
        # --- 제목 ---
        style.configure('Title.TLabel', 
                        font=self.fonts["title"], 
                        foreground=self.colors["primary"],
                        background=self.colors["bg"])
        style.configure('Subtitle.TLabel', 
                        font=self.fonts["body"], 
                        foreground=self.colors["fg"],
                        background=self.colors["bg"])

        # --- 버튼 ---
        style.configure('TButton', 
                        font=self.fonts["button"],
                        padding=(10, 5),
                        borderwidth=0,
                        relief="flat")
        style.map('TButton',
                  background=[('active', self.colors["bg_light"]), ('!disabled', self.colors["bg_dark"])],
                  foreground=[('!disabled', self.colors["primary"])] )

        style.configure('Primary.TButton', foreground=self.colors["secondary"])
        style.map('Primary.TButton', foreground=[('!disabled', self.colors["secondary"])])
        
        style.configure('Danger.TButton', foreground=self.colors["danger"])
        style.map('Danger.TButton', foreground=[('!disabled', self.colors["danger"])])

        # --- 레이블 프레임 ---
        style.configure('TLabelframe', 
                        font=self.fonts["header"],
                        padding=(15, 10),
                        background=self.colors["bg"],
                        foreground=self.colors["fg"],
                        relief="solid",
                        borderwidth=1)
        style.configure('TLabelframe.Label', 
                        font=self.fonts["header"],
                        foreground=self.colors["primary"],
                        background=self.colors["bg"])

        # --- 노트북 (탭) ---
        style.configure('TNotebook', 
                        background=self.colors["bg"],
                        borderwidth=0)
        style.configure('TNotebook.Tab', 
                        font=self.fonts["button"],
                        padding=(10, 5),
                        background=self.colors["bg_dark"],
                        foreground=self.colors["fg"],
                        borderwidth=0)
        style.map('TNotebook.Tab',
                  background=[('selected', self.colors["primary"]), ('active', self.colors["bg_light"])],
                  foreground=[('selected', self.colors["bg_dark"]), ('active', self.colors["primary"])])

        # --- 프로그레스 바 ---
        style.configure('Custom.Horizontal.TProgressbar',
                       troughcolor=self.colors["bg_dark"],
                       background=self.colors["primary"],
                       borderwidth=0)
        
        # --- 상태 라벨 ---
        style.configure('Status.TLabel', font=self.fonts["body"], background=self.colors["bg"])
        style.configure('Success.Status.TLabel', foreground=self.colors["secondary"])
        style.configure('Error.Status.TLabel', foreground=self.colors["danger"])
        style.configure('Warning.Status.TLabel', foreground=self.colors["warning"])

    def setup_ui(self):
        """UI 설정"""
        # 메인 컨테이너
        main_container = ttk.Frame(self.root, padding=(20, 10))
        main_container.pack(fill=tk.BOTH, expand=True)

        # 메인 콘텐츠 영역
        content_paned = ttk.PanedWindow(main_container, orient=tk.HORIZONTAL)
        content_paned.pack(fill=tk.BOTH, expand=True, pady=10)

        # 좌측 패널 (파일 처리와 텍스트 입력)
        left_panel = ttk.Frame(content_paned, padding=5)
        content_paned.add(left_panel, weight=1)

        # 우측 패널 (출력)
        right_panel = ttk.Frame(content_paned, padding=5)
        content_paned.add(right_panel, weight=3)

        # 좌측 패널 구성
        self.setup_left_panel(left_panel)

        # 우측 패널 구성
        self.setup_right_panel(right_panel)

        # 하단 상태바
        self.setup_status_bar(main_container)

    def setup_left_panel(self, parent):
        """좌측 패널 설정 - 파일 처리와 텍스트 입력"""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # 파일 처리 섹션
        file_section = ttk.LabelFrame(parent, text="File Processing")
        file_section.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        file_section.grid_columnconfigure(1, weight=1)

        # 드래그 앤 드롭 영역
        self.drop_frame = tk.Frame(file_section, bg=self.colors["bg_dark"], relief='solid', bd=1)
        self.drop_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=5, ipady=10)

        self.drop_label = tk.Label(self.drop_frame,
                                   text="Drag & Drop QMI Log File Here\nor Click to Browse",
                                   font=self.fonts["body"],
                                   fg=self.colors["fg"],
                                   bg=self.colors["bg_dark"])
        self.drop_label.pack(expand=True, padx=10, pady=10)

        # 파일 선택 버튼과 경로 표시
        self.browse_button = ttk.Button(file_section, text="Browse File",
                                        command=self.browse_file)
        self.browse_button.grid(row=1, column=0, pady=(0, 5), padx=(0, 10))

        self.file_path_var = tk.StringVar()
        self.file_label = ttk.Label(file_section, textvariable=self.file_path_var,
                                    foreground=self.colors["info"], font=self.fonts["body"])
        self.file_label.grid(row=1, column=1, sticky="ew", pady=(0, 5))

        # 파일 처리 버튼
        button_frame = ttk.Frame(file_section)
        button_frame.grid(row=2, column=0, columnspan=2, sticky="w")

        self.process_file_button = ttk.Button(button_frame, text="Parse File",
                                              command=self.start_file_processing,
                                              state='disabled', style='Primary.TButton')
        self.process_file_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(button_frame, text="Cancel",
                                        command=self.cancel_processing_action,
                                        state='disabled', style='Danger.TButton')
        self.cancel_button.pack(side=tk.LEFT, padx=10)

        # 텍스트 입력 섹션
        text_section = ttk.LabelFrame(parent, text="Raw Text Input")
        text_section.grid(row=1, column=0, sticky="nsew")
        text_section.grid_rowconfigure(0, weight=1)
        text_section.grid_columnconfigure(0, weight=1)

        # 텍스트 입력창
        self.raw_input = tk.Text(text_section, height=8, wrap=tk.WORD,
                                 font=self.fonts["monospace"],
                                 bg=self.colors["bg_dark"],
                                 fg=self.colors["fg"],
                                 relief="flat",
                                 insertbackground=self.colors["primary"],
                                 selectbackground=self.colors["bg_light"],
                                 selectforeground=self.colors["fg"])
        text_scrollbar = ttk.Scrollbar(text_section, orient="vertical",
                                       command=self.raw_input.yview)
        self.raw_input.configure(yscrollcommand=text_scrollbar.set)
        self.raw_input.grid(row=0, column=0, sticky="nsew", pady=5)
        text_scrollbar.grid(row=0, column=1, sticky="ns")

        # 텍스트 처리 버튼
        text_button_frame = ttk.Frame(text_section)
        text_button_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.process_text_button = ttk.Button(text_button_frame, text="Parse Text",
                                              command=self.process_raw_data,
                                              style='Primary.TButton')
        self.process_text_button.pack(side=tk.LEFT)
        
        ttk.Button(text_button_frame, text="Sample Data",
                   command=self.insert_sample_data).pack(side=tk.LEFT, padx=10)

        ttk.Button(text_button_frame, text="Clear Input",
                   command=self.clear_raw_input).pack(side=tk.RIGHT)

    def setup_right_panel(self, parent):
        """우측 패널 설정 - 출력 결과"""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        output_section = ttk.LabelFrame(parent, text="Output")
        output_section.grid(row=0, column=0, sticky="nsew")
        output_section.grid_columnconfigure(0, weight=1)
        output_section.grid_rowconfigure(0, weight=1)

        # 노트북 (탭) 위젯
        self.output_notebook = ttk.Notebook(output_section)
        self.output_notebook.pack(fill=tk.BOTH, expand=True, pady=5)

        # 탭 생성
        self.combined_text = self.create_output_tab("Combined")
        self.parsed_only_text = self.create_output_tab("Parsed Only")
        self.log_text = self.create_output_tab("Log")

        # 출력 버튼들
        output_buttons = ttk.Frame(output_section)
        output_buttons.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(output_buttons, text="Save Results",
                   command=self.save_results,
                   style='Primary.TButton').pack(side=tk.LEFT)

        ttk.Button(output_buttons, text="Clear Output",
                   command=self.clear_output).pack(side=tk.LEFT, padx=10)

        ttk.Button(output_buttons, text="Reset All",
                   command=self.clear_all,
                   style='Danger.TButton').pack(side=tk.RIGHT)

    def create_output_tab(self, title):
        """Helper to create a text widget tab with search and copy"""
        tab_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(tab_frame, text=title)
        
        tab_frame.grid_rowconfigure(1, weight=1)
        tab_frame.grid_columnconfigure(0, weight=1)

        # --- 상단 컨트롤 프레임 ---
        control_frame = ttk.Frame(tab_frame)
        control_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(5, 10))
        control_frame.grid_columnconfigure(0, weight=1)

        # 검색 기능
        search_entry = ttk.Entry(control_frame, font=self.fonts["body"])
        search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        regex_check = ttk.Checkbutton(control_frame, text="Regex", variable=self.regex_var)
        regex_check.grid(row=0, column=1, padx=(0, 10))

        search_button = ttk.Button(control_frame, text="🔍 Search", 
                                   command=lambda: self.perform_search(text_widget, search_entry, self.regex_var))
        search_button.grid(row=0, column=2, padx=(0, 5))

        clear_button = ttk.Button(control_frame, text="Clear", 
                                  command=lambda: self.clear_search(text_widget, search_entry))
        clear_button.grid(row=0, column=3, padx=(0, 10))

        copy_button = ttk.Button(control_frame, text="📋 Copy All", 
                                 command=lambda: self.copy_to_clipboard(text_widget))
        copy_button.grid(row=0, column=4)
        
        # 검색창 Key/Return 이벤트 바인딩
        search_entry.bind("<KeyRelease>", lambda event: self.on_search_key_release(event, text_widget, search_entry))
        search_entry.bind("<Return>", lambda event: self.perform_search(text_widget, search_entry, self.regex_var))

        # --- 텍스트 위젯 ---
        text_widget = tk.Text(tab_frame, wrap=tk.WORD,
                              font=self.fonts["monospace"],
                              bg=self.colors["bg_dark"],
                              fg=self.colors["fg"],
                              relief="flat",
                              insertbackground=self.colors["primary"],
                              selectbackground=self.colors["bg_light"],
                              selectforeground=self.colors["fg"])
        
        text_widget.tag_configure("highlight", foreground=self.colors["highlight"])
        text_widget.tag_configure("separator", foreground=self.colors["primary"])
        text_widget.tag_configure("timestamp_highlight", foreground=self.colors["danger"])

        scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        text_widget.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        
        return text_widget

    def on_search_key_release(self, event, text_widget, search_entry):
        """Handle key release in search entry to auto-clear search."""
        if not search_entry.get():
            self.clear_search(text_widget, search_entry)

    def perform_search(self, text_widget, search_entry, regex_var):
        query = search_entry.get()
        use_regex = regex_var.get()

        if not query:
            self.clear_search(text_widget, search_entry)
            return

        original_content = self.original_texts.get(text_widget, "")
        if not original_content:
            self.update_status("No content to search.", "warning")
            return

        matching_lines = []
        try:
            if use_regex:
                pattern = re.compile(query, re.IGNORECASE)
                for line in original_content.splitlines():
                    if pattern.search(line):
                        matching_lines.append(line)
            else:
                for line in original_content.splitlines():
                    if query.lower() in line.lower():
                        matching_lines.append(line)
        except re.error as e:
            self.update_status(f"Regex Error: {e}", "error")
            return

        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        if matching_lines:
            text_widget.insert("1.0", "\n".join(matching_lines))
            self.update_status(f"Found {len(matching_lines)} matching lines.", "success")
        else:
            text_widget.insert("1.0", f"No lines matching: '{query}'")
            self.update_status("No matches found.", "info")
        
        self.highlight_text(text_widget, {"highlight": [query]})
        text_widget.config(state=tk.DISABLED)

    def clear_search(self, text_widget, search_entry):
        search_entry.delete(0, tk.END)
        original_content = self.original_texts.get(text_widget, "")
        text_widget.config(state=tk.NORMAL)
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", original_content)
        self.highlight_text(text_widget, {
            "timestamp_highlight": ["timestamp"],
            "highlight": ["QmiType", "IFType", "QmiLength", "QmiCtlFlags"],
            "separator": ["--------------------------------------------------"]
        })
        text_widget.config(state=tk.DISABLED)
        self.update_status("Search cleared.", "info")

    def highlight_text(self, text_widget, tag_keyword_map):
        for tag, keywords in tag_keyword_map.items():
            text_widget.tag_remove(tag, "1.0", tk.END)
            for keyword in keywords:
                start_pos = "1.0"
                while True:
                    start_pos = text_widget.search(keyword, start_pos, stopindex=tk.END, nocase=True)
                    if not start_pos:
                        break
                    line_start = f"{start_pos.split('.')[0]}.0"
                    line_end = f"{start_pos.split('.')[0]}.end"
                    text_widget.tag_add(tag, line_start, line_end)
                    start_pos = line_end

    def copy_to_clipboard(self, text_widget):
        """Copy the content of a text widget to the clipboard."""
        content = text_widget.get("1.0", tk.END).strip()
        if not content:
            self.update_status("Nothing to copy.", "warning")
            return
        
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.update_status("📋 Content copied to clipboard.", "success")
        self.log("📋 Content copied to clipboard.")

    def setup_status_bar(self, parent):
        """상태바 설정"""
        status_frame = ttk.Frame(parent, padding=(0, 2))
        status_frame.pack(fill=tk.X)
        status_frame.grid_columnconfigure(0, weight=1)

        # 상태 라벨
        self.status_var = tk.StringVar()
        self.status_var.set("🟢 Ready")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, style='Status.TLabel')
        self.status_label.grid(row=0, column=0, sticky="w")

        # 프로그레스 바
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(status_frame,
                                          variable=self.progress_var,
                                          maximum=100,
                                          style='Custom.Horizontal.TProgressbar')
        self.progress_bar.grid(row=0, column=1, sticky="ew", padx=20)

    def insert_sample_data(self):
        """샘플 QMI 로그 데이터를 입력창에 삽입"""
        sample_data = """07-31 15:27:15.795 radio 10981 11030 D RILD    : RIL-RAWDATA: 01 0C 00 00 03 00 00 72 01 43 00 00 00 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 01 CE 00 80 03 00 02 72 01 43 00 C2 00 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 02 04 00 00 00 00 00 13 1D 00 00 54 F0 50 05 27 23 94 44 00 C4 09 7B 00 00 00 00 00 01 7B 00 AC 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: FF 2B FD 0F FE 00 00 14 1E 00 00 03 22 0B 00 00 00 00 13 01 00 00 00 01 7B 00 97 FF 64 FC 26 FD 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 00 46 05 00 00 00 00 15 02 00 00 00 16 02 00 00 00 1E 04 00 07 00 00 00 26 02 00 05 00 27 04 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 C4 09 00 00 28 0D 00 03 22 0B 00 00 13 01 00 00 46 05 00 00 2A 04 00 03 00 00 00 2C 04 00 01 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 00 00 2D 04 00 04 00 00 00 30 2C 00 00 04 22 0B 00 00 00 00 00 00 13 01 00 00 00 00 00 01 7B 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 00 97 FF 64 FC 26 FD 00 00 46 05 00 00 00 00 00 00 80 0C 00 00 00 00 00 00 32 06 00 34 35 30 30 
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 35 FF"""
        self.raw_input.delete(1.0, tk.END)
        self.raw_input.insert(1.0, sample_data)
        self.log("✅ Sample QMI log data inserted.")

    def setup_drag_drop(self):
        """드래그 앤 드롭 설정"""
        self.drop_frame.bind('<Button-1>', self.on_drop_click)
        self.drop_label.bind('<Button-1>', self.on_drop_click)
        try:
            from tkinterdnd2 import DND_FILES
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_file_drop)
        except ImportError:
            self.log("⚠️ tkinterdnd2 not found. Drag & drop is disabled.", show_time=False)

    def on_drop_click(self, event):
        self.browse_file()

    def on_file_drop(self, event):
        if self.is_processing:
            messagebox.showwarning("Warning", "Processing is ongoing. Please wait.")
            return
        # In tkinterdnd2, event.data is a string of file paths
        file_path = self.root.tk.splitlist(event.data)[0]
        self.set_file_path(file_path)

    def browse_file(self):
        if self.is_processing:
            messagebox.showwarning("Warning", "Processing is ongoing. Please wait.")
            return
        file_path = filedialog.askopenfilename(
            title="Select QMI Log File",
            filetypes=[("Log files", "*.txt *.log"), ("All files", "*.*")]
        )
        if file_path:
            self.set_file_path(file_path)

    def set_file_path(self, file_path):
        self.file_path = file_path
        filename = os.path.basename(file_path)
        self.file_path_var.set(filename)
        self.process_file_button.config(state='normal')
        self.drop_label.config(text=f"✅ File Selected:\n{filename}", fg=self.colors["secondary"])
        self.update_status(f"📁 File selected, ready to parse.", "success")
        self.log(f"📁 File selected: {file_path}")

    def clear_raw_input(self):
        if self.is_processing: return
        self.raw_input.delete(1.0, tk.END)
        self.log("🧹 Raw input cleared.")

    def clear_output(self):
        for text_widget in self.original_texts:
            text_widget.config(state=tk.NORMAL)
            text_widget.delete('1.0', tk.END)
            text_widget.config(state=tk.DISABLED)
        self.original_texts.clear()
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.update_status("🧹 Output cleared.", "info")

    def clear_all(self):
        if self.is_processing:
            self.cancel_processing_action()
            self.root.after(100, self._complete_clear_all)
            return
        self._complete_clear_all()

    def _complete_clear_all(self):
        self.file_path = None
        self.file_path_var.set("")
        self.clear_output()
        self.clear_raw_input()
        self.unlock_ui()
        self.process_file_button.config(state='disabled')
        self.drop_label.config(text="Drag & Drop QMI Log File Here\nor Click to Browse", fg=self.colors["fg"])
        self.progress_var.set(0)
        self.output_notebook.select(0)
        self.update_status("🔄 Reset complete.", "success")
        self.log("🔄 Application has been reset.")

    def update_status(self, message, status_type="info"):
        self.status_var.set(message)
        style_map = {
            "success": "Success.Status.TLabel",
            "error": "Error.Status.TLabel",
            "warning": "Warning.Status.TLabel",
            "info": "Status.TLabel"
        }
        self.status_label.config(style=style_map.get(status_type, "Status.TLabel"))
        self.root.update_idletasks()

    def log(self, message, show_time=True):
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n" if show_time else f"{message}\n"
        self.log_text.insert(tk.END, formatted_message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def show_result(self, results):
        try:
            if isinstance(results, dict):
                # Clear previous results and original text cache
                self.clear_output()

                tag_map = {
                    "timestamp_highlight": ["timestamp"],
                    "highlight": ["QmiType", "IFType", "QmiLength", "QmiCtlFlags"],
                    "separator": ["--------------------------------------------------"]
                }

                combined_content = results.get('combined', '')
                self.combined_text.config(state=tk.NORMAL)
                if combined_content:
                    self.combined_text.insert('1.0', combined_content)
                    self.original_texts[self.combined_text] = combined_content
                    self.log(f"📄 Combined result: {len(combined_content)} chars.")
                    self.highlight_text(self.combined_text, tag_map)
                self.combined_text.config(state=tk.DISABLED)

                parsed_only_content = results.get('parsed_only', '')
                self.parsed_only_text.config(state=tk.NORMAL)
                if parsed_only_content:
                    self.parsed_only_text.insert('1.0', parsed_only_content)
                    self.original_texts[self.parsed_only_text] = parsed_only_content
                    self.log(f"🔍 Parsed result: {len(parsed_only_content)} chars.")
                    self.highlight_text(self.parsed_only_text, tag_map)
                else:
                    self.parsed_only_text.insert('1.0', "No QMI packets found to parse.\n\nCheck if the input contains valid QMI log entries.")
                self.parsed_only_text.config(state=tk.DISABLED)

                if 'stats' in results:
                    stats = results['stats']
                    self.log(f"📊 Stats - Lines: {stats.get('lines', 0)}, Packets: {stats.get('packets', 0)}")

                if parsed_only_content and parsed_only_content.strip():
                    self.output_notebook.select(1)
                    self.log("🎯 Switched to 'Parsed Only' tab.")
                else:
                    self.output_notebook.select(0)
                    self.log("🎯 Switched to 'Combined' tab.")
            else: # Fallback for old string format
                self.show_result({'combined': str(results), 'parsed_only': "Result is in a legacy format.", 'stats': {}})

        except Exception as e:
            self.log(f"❌ Error displaying results: {e}")
            print(f"show_result error: {e}")

    def save_results(self):
        try:
            current_tab_index = self.output_notebook.index(self.output_notebook.select())
            text_widgets = [self.combined_text, self.parsed_only_text, self.log_text]
            default_names = ["qmi_combined.txt", "qmi_parsed.txt", "qmi_log.txt"]
            titles = ["Save Combined Result", "Save Parsed Result", "Save Log"]

            content = text_widgets[current_tab_index].get('1.0', tk.END).strip()
            if not content:
                self.update_status("Nothing to save.", "warning")
                return

            file_path = filedialog.asksaveasfilename(
                title=titles[current_tab_index],
                initialfile=default_names[current_tab_index],
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
            )
            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.update_status(f"💾 Result saved to {file_path}", "success")
                self.log(f"💾 Saved: {file_path}")
        except Exception as e:
            self.update_status(f"❌ Save error: {e}", "error")
            self.log(f"❌ Save error: {e}")

    def lock_ui(self):
        self.is_processing = True
        self.browse_button.config(state='disabled')
        self.process_file_button.config(state='disabled')
        self.process_text_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.drop_label.config(text="Processing...", fg=self.colors["warning"])

    def unlock_ui(self):
        self.is_processing = False
        self.cancel_processing = False
        self.browse_button.config(state='normal')
        self.process_text_button.config(state='normal')
        self.cancel_button.config(state='disabled')
        if self.file_path:
            self.process_file_button.config(state='normal')
            self.set_file_path(self.file_path) # Restore file selected state
        else:
            self.drop_label.config(text="Drag & Drop QMI Log File Here\nor Click to Browse", fg=self.colors["fg"])

    def cancel_processing_action(self):
        self.cancel_processing = True
        self.update_status("⏹️ Cancelling...", "warning")
        self.log("⏹️ User requested to cancel processing.")

    def start_file_processing(self):
        if not self.file_path or self.is_processing: return
        if not os.path.exists(self.file_path):
            messagebox.showerror("Error", "The selected file does not exist.")
            return
        self.lock_ui()
        self.progress_var.set(0)
        self.update_status("⚡ Parsing file...", "info")
        input_dir = os.path.dirname(self.file_path)
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        combined_path = os.path.join(input_dir, f"QCAT_{base_name}.txt")
        parsed_only_path = os.path.join(input_dir, f"QCAT_{base_name}_parsed_only.txt")
        thread = threading.Thread(target=self.process_file_thread,
                                  args=(self.file_path, combined_path, parsed_only_path))
        thread.daemon = True
        thread.start()

    def process_file_thread(self, input_path, combined_path, parsed_only_path):
        try:
            self.log("🚀 Starting file processing thread.")
            def progress_callback(message, progress=None):
                if self.cancel_processing: raise Exception("Processing cancelled by user.")
                self.root.after(0, self.log, message, False)
                if progress is not None:
                    self.root.after(0, self.progress_var.set, progress)
                    if "%" in message:
                        self.root.after(0, self.update_status, f"⚡ {message}", "info")
            
            self.processor.process_qmi_log(input_path, combined_path, parsed_only_path, progress_callback)

            if not self.cancel_processing:
                self.root.after(0, self.log, "✅ File processing complete!")
                self.root.after(0, self.update_status, "✅ File parsing complete!", "success")
                self.root.after(0, messagebox.showinfo, "Complete", f"QMI log parsing is complete!\n\nOutput files saved in:\n{os.path.dirname(combined_path)}")
        except Exception as e:
            error_msg = f"❌ File processing error: {e}"
            self.root.after(0, self.log, error_msg)
            self.root.after(0, self.update_status, "❌ File processing error.", "error")
            if not self.cancel_processing:
                self.root.after(0, messagebox.showerror, "Error", str(e))
        finally:
            self.root.after(0, self.unlock_ui)
            self.root.after(0, self.progress_var.set, 0)

    def process_raw_data(self):
        raw_data = self.raw_input.get(1.0, tk.END).strip()
        if not raw_data:
            messagebox.showwarning("Warning", "Input text is empty.")
            return
        if self.is_processing: return
        self.lock_ui()
        self.progress_var.set(0)
        self.update_status("⚡ Parsing text...", "info")
        thread = threading.Thread(target=self.process_text_thread, args=(raw_data,))
        thread.daemon = True
        thread.start()

    def process_text_thread(self, raw_data):
        try:
            self.log("🚀 Starting text processing thread.")
            def progress_callback(message, progress=None):
                if self.cancel_processing: raise Exception("Processing cancelled by user.")
                self.root.after(0, self.log, message, False)
                if progress is not None:
                    self.root.after(0, self.progress_var.set, progress)
                    if "%" in message:
                        self.root.after(0, self.update_status, f"⚡ {message}", "info")
            
            result = self.processor.process_qmi_text(raw_data, progress_callback)

            if not self.cancel_processing:
                self.root.after(0, self.show_result, result)
                self.root.after(0, self.log, "✅ Text processing complete!")
                self.root.after(0, self.update_status, "✅ Text parsing complete!", "success")
        except Exception as e:
            error_msg = f"❌ Text processing error: {e}"
            self.root.after(0, self.log, error_msg)
            self.root.after(0, self.update_status, "❌ Text processing error.", "error")
            if not self.cancel_processing:
                self.root.after(0, messagebox.showerror, "Error", str(e))
        finally:
            self.root.after(0, self.unlock_ui)
            self.root.after(0, self.progress_var.set, 0)

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.regex_var.set(config.get("use_regex", True))
            else:
                self.regex_var.set(True)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading config: {e}")
            self.regex_var.set(True)

    def save_config(self):
        try:
            config = {"use_regex": self.regex_var.get()}
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=4)
        except IOError as e:
            print(f"Error saving config: {e}")

    def on_closing(self):
        self.save_config()
        self.root.destroy()

if __name__ == '__main__':
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except ImportError:
        root = tk.Tk()
        
    app = QMIParserGUI(root)
    root.mainloop()