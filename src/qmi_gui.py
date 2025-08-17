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

# QMI.py의 상수들 (실제 QMI.py에서 가져온 값들)
LOG_PACKET_DEFAULT = "24 00 8F 13 00 00 9A 9E CD 7B C2 00"
QCAT_MODEL_NUMBER = 165
MAX_BUFFER_BYTES_PER_LINE = 32
MAX_OUTPUT_BUF_SIZE = ((MAX_BUFFER_BYTES_PER_LINE * 3) + 2)


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
            qcat_header_pattern = r'\d{4}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\[.{2,8}\]\s+0x....\s+QMI Link 1 TX PDU'
            replacement = f"""--------------------------------------------------\n{log_timestamp}"""
            new_text, count = re.subn(qcat_header_pattern, replacement, parsed_text, count=1)
            if count > 0:
                parsed_text = new_text
            else:
                # 패턴이 일치하지 않으면 기존 방식으로 대체
                replacement_fallback = f"""--------------------------------------------------\n{log_timestamp} builded. Parsed by QCAT"""
                parsed_text = re.sub(
                    r' (\d{2}):(\d{2}):(\d{2}\.\d{1,9})\s+.\[.{2,8}\]\s+(0x....)  QMI Link 1 TX PDU',
                    replacement_fallback,
                    parsed_text
                )
        else:
            # 타임스탬프가 없으면 기존 방식으로 동작
            parsed_text = re.sub(
                r' ([0-9]{2}):([0-9]{2}):([0-9]{2}\.[0-9]{1,9})\s+\[.{2,8}\]\s+(0x....)  QMI Link 1 TX PDU',
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
        self.root.title("QMI Parser")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)

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

        # UI 설정
        self.setup_ui()
        self.setup_drag_drop()

    def setup_styles(self):
        """UI 스타일 설정"""
        style = ttk.Style()

        # 테마 설정
        try:
            style.theme_use('clam')  # 더 현대적인 테마
        except:
            pass

        # 커스텀 스타일 정의
        style.configure('Title.TLabel', font=('맑은 고딕', 12, 'bold'), foreground='#2c3e50')
        style.configure('Subtitle.TLabel', font=('맑은 고딕', 10), foreground='#34495e')
        style.configure('Success.TLabel', font=('맑은 고딕', 9), foreground='#27ae60')
        style.configure('Error.TLabel', font=('맑은 고딕', 9), foreground='#e74c3c')
        style.configure('Warning.TLabel', font=('맑은 고딕', 9), foreground='#f39c12')

        # 프로그레스 바 스타일
        style.configure('Custom.Horizontal.TProgressbar',
                       troughcolor='#ecf0f1',
                       background='#3498db',
                       borderwidth=1,
                       lightcolor='#3498db',
                       darkcolor='#2980b9')

        # 버튼 스타일
        style.configure('Action.TButton', font=('맑은 고딕', 9, 'bold'))
        style.configure('Danger.TButton', font=('맑은 고딕', 9))

    def setup_ui(self):
        # 메인 컨테이너
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 헤더
        self.setup_header(main_container)

        # 메인 콘텐츠 영역
        content_paned = ttk.PanedWindow(main_container, orient=tk.HORIZONTAL)
        content_paned.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # 좌측 패널 (파일 처리와 텍스트 입력)
        left_panel = ttk.Frame(content_paned)
        content_paned.add(left_panel, weight=2)

        # 우측 패널 (출력)
        right_panel = ttk.Frame(content_paned)
        content_paned.add(right_panel, weight=3)

        # 좌측 패널 구성
        self.setup_left_panel(left_panel)

        # 우측 패널 구성
        self.setup_right_panel(right_panel)

        # 하단 상태바
        self.setup_status_bar(main_container)

    def setup_header(self, parent):
        """헤더 영역 설정"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_label = ttk.Label(header_frame, text="QMI Parser", style='Title.TLabel')
        title_label.pack(side=tk.LEFT)

        # subtitle_label = ttk.Label(header_frame, text="QCAT 기반 QMI 로그 분석 도구", style='Subtitle.TLabel')
        # subtitle_label.pack(side=tk.LEFT, padx=(10, 0))

        # 버전 정보
        version_label = ttk.Label(header_frame, text="v1.0", style='Subtitle.TLabel')
        version_label.pack(side=tk.RIGHT)

    def setup_left_panel(self, parent):
        """좌측 패널 설정 - 파일 처리와 텍스트 입력"""

        # 파일 처리 섹션
        file_section = ttk.LabelFrame(parent, text="📁 파일 처리", padding=15)
        file_section.pack(fill=tk.X, pady=(0, 10))

        # 드래그 앤 드롭 영역 (relief를 'solid'로 변경)
        self.drop_frame = tk.Frame(file_section, bg='#ecf0f1', relief='solid', bd=2)
        self.drop_frame.pack(fill=tk.X, pady=(0, 10), ipady=20)

        self.drop_label = tk.Label(self.drop_frame,
                                   text="📂 QMI 로그 파일을 여기에 드래그하거나\n아래 버튼을 클릭하세요",
                                   font=('맑은 고딕', 11),
                                   fg='#7f8c8d',
                                   bg='#ecf0f1')
        self.drop_label.pack(expand=True)

        # 파일 선택 버튼과 경로 표시
        file_controls = ttk.Frame(file_section)
        file_controls.pack(fill=tk.X, pady=(0, 10))

        self.browse_button = ttk.Button(file_controls, text="📁 파일 선택",
                                        command=self.browse_file, style='Action.TButton')
        self.browse_button.pack(side=tk.LEFT)

        self.file_path_var = tk.StringVar()
        self.file_label = ttk.Label(file_controls, textvariable=self.file_path_var,
                                    foreground='#2980b9', font=('맑은 고딕', 9))
        self.file_label.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        # 파일 처리 버튼
        button_frame = ttk.Frame(file_section)
        button_frame.pack(fill=tk.X)

        self.process_file_button = ttk.Button(button_frame, text="⚡ 파일 파싱 시작",
                                              command=self.start_file_processing,
                                              state='disabled', style='Action.TButton')
        self.process_file_button.pack(side=tk.LEFT)

        self.cancel_button = ttk.Button(button_frame, text="❌ 취소",
                                        command=self.cancel_processing_action,
                                        state='disabled', style='Danger.TButton')
        self.cancel_button.pack(side=tk.LEFT, padx=(10, 0))

        # 텍스트 입력 섹션
        text_section = ttk.LabelFrame(parent, text="📝 텍스트 로그 직접 입력", padding=15)
        text_section.pack(fill=tk.BOTH, expand=True)

        # 텍스트 입력 안내
        ttk.Label(text_section, text="QMI 로그 텍스트를 직접 입력하세요:",
                  style='Subtitle.TLabel').pack(anchor=tk.W, pady=(0, 5))

        # 텍스트 입력창
        text_input_frame = ttk.Frame(text_section)
        text_input_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.raw_input = tk.Text(text_input_frame, height=8, wrap=tk.WORD,
                                 font=('Consolas', 9), bg='#fafafa')
        text_scrollbar = ttk.Scrollbar(text_input_frame, orient="vertical",
                                       command=self.raw_input.yview)
        self.raw_input.configure(yscrollcommand=text_scrollbar.set)

        self.raw_input.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        text_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        text_input_frame.grid_columnconfigure(0, weight=1)
        text_input_frame.grid_rowconfigure(0, weight=1)

        # 텍스트 처리 버튼
        text_button_frame = ttk.Frame(text_section)
        text_button_frame.pack(fill=tk.X)

        self.process_text_button = ttk.Button(text_button_frame, text="⚡ 텍스트 파싱 시작",
                                              command=self.process_raw_data,
                                              style='Action.TButton')
        self.process_text_button.pack(side=tk.LEFT)

        # 샘플 데이터 삽입 버튼
        ttk.Button(text_button_frame, text="📋 샘플 데이터",
                   command=self.insert_sample_data,
                   style='Info.TButton').pack(side=tk.LEFT, padx=(10, 0))

        # 입력 클리어 버튼
        ttk.Button(text_button_frame, text="🗑️ 입력 지우기",
                   command=self.clear_raw_input,
                   style='Secondary.TButton').pack(side=tk.RIGHT)

    def setup_right_panel(self, parent):
        """우측 패널 설정 - 출력 결과"""

        # 출력 섹션
        output_section = ttk.LabelFrame(parent, text="📊 출력 결과", padding=15)
        output_section.pack(fill=tk.BOTH, expand=True)

        # 노트북 (탭) 위젯
        self.output_notebook = ttk.Notebook(output_section)
        self.output_notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 1. 통합 결과 탭 (원본 로그 + 파싱 결과)
        combined_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(combined_frame, text="📄 통합 결과")

        combined_text_frame = ttk.Frame(combined_frame)
        combined_text_frame.pack(fill=tk.BOTH, expand=True)

        self.combined_text = tk.Text(combined_text_frame, wrap=tk.WORD,
                                     font=('Consolas', 9), bg='#fafafa')
        combined_scrollbar = ttk.Scrollbar(combined_text_frame, orient="vertical",
                                           command=self.combined_text.yview)
        self.combined_text.configure(yscrollcommand=combined_scrollbar.set)

        self.combined_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        combined_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        combined_text_frame.grid_columnconfigure(0, weight=1)
        combined_text_frame.grid_rowconfigure(0, weight=1)

        # 2. 파싱 결과만 탭
        parsed_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(parsed_frame, text="🔍 파싱 결과만")

        parsed_text_frame = ttk.Frame(parsed_frame)
        parsed_text_frame.pack(fill=tk.BOTH, expand=True)

        self.parsed_only_text = tk.Text(parsed_text_frame, wrap=tk.WORD,
                                        font=('Consolas', 9), bg='#fafafa')
        parsed_scrollbar = ttk.Scrollbar(parsed_text_frame, orient="vertical",
                                         command=self.parsed_only_text.yview)
        self.parsed_only_text.configure(yscrollcommand=parsed_scrollbar.set)

        self.parsed_only_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        parsed_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        parsed_text_frame.grid_columnconfigure(0, weight=1)
        parsed_text_frame.grid_rowconfigure(0, weight=1)

        # 3. 처리 로그 탭
        log_frame = ttk.Frame(self.output_notebook)
        self.output_notebook.add(log_frame, text="📋 처리 로그")

        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_text_frame, wrap=tk.WORD,
                                font=('Consolas', 9), bg='#f8f9fa')
        log_scrollbar = ttk.Scrollbar(log_text_frame, orient="vertical",
                                      command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        log_text_frame.grid_columnconfigure(0, weight=1)
        log_text_frame.grid_rowconfigure(0, weight=1)

        # 출력 버튼들
        output_buttons = ttk.Frame(output_section)
        output_buttons.pack(fill=tk.X)

        ttk.Button(output_buttons, text="💾 결과 저장",
                   command=self.save_results,
                   style='Success.TButton').pack(side=tk.LEFT)

        ttk.Button(output_buttons, text="🗑️ 출력 지우기",
                   command=self.clear_output,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(output_buttons, text="🔄 전체 초기화",
                   command=self.clear_all,
                   style='Danger.TButton').pack(side=tk.LEFT, padx=(10, 0))

    def setup_status_bar(self, parent):
        """상태바 설정"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        # 구분선
        ttk.Separator(status_frame, orient='horizontal').pack(fill=tk.X, pady=(0, 5))

        status_content = ttk.Frame(status_frame)
        status_content.pack(fill=tk.X)

        # 상태 라벨
        self.status_var = tk.StringVar()
        self.status_var.set("🟢 준비 완료")
        self.status_label = ttk.Label(status_content, textvariable=self.status_var,
                                     style='Success.TLabel', font=('맑은 고딕', 9))
        self.status_label.pack(side=tk.LEFT)

        # 프로그레스 바
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(status_content,
                                          variable=self.progress_var,
                                          maximum=100,
                                          style='Custom.Horizontal.TProgressbar')
        self.progress_bar.pack(side=tk.RIGHT, padx=(10, 0), fill=tk.X, expand=True)

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
07-31 15:27:15.795 radio 10981 11042 D RILD    : RIL-RAWDATA: 35 FF """
        self.raw_input.delete(1.0, tk.END)
        self.raw_input.insert(1.0, sample_data)
        self.log("✅ 샘플 QMI 로그 데이터가 입력되었습니다.")

    def setup_drag_drop(self):
        """드래그 앤 드롭 설정"""
        # 드래그 앤 드롭 이벤트 바인딩
        self.drop_frame.bind('<Button-1>', self.on_drop_click)
        self.drop_label.bind('<Button-1>', self.on_drop_click)

        # Windows에서 파일 드롭 지원
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_file_drop)
        except:
            # tkinterdnd2가 없는 경우 기본 기능만 사용
            pass

    def on_drop_click(self, event):
        """드롭 영역 클릭 시 파일 브라우저 열기"""
        self.browse_file()

    def on_file_drop(self, event):
        """파일 드롭 이벤트 처리"""
        if self.is_processing:
            messagebox.showwarning("경고", "현재 처리 중입니다. 완료 후 다시 시도해주세요.")
            return

        files = event.data.split()
        if files:
            file_path = files[0].strip('{}')
            self.set_file_path(file_path)

    def browse_file(self):
        """파일 브라우저 열기"""
        if self.is_processing:
            messagebox.showwarning("경고", "현재 처리 중입니다. 완료 후 다시 시도해주세요.")
            return

        file_path = filedialog.askopenfilename(
            title="QMI 로그 파일 선택",
            filetypes=[("텍스트 파일", "*.txt"), ("로그 파일", "*.log"), ("모든 파일", "*.*")]
        )
        if file_path:
            self.set_file_path(file_path)

    def set_file_path(self, file_path):
        """선택된 파일 경로 설정"""
        self.file_path = file_path
        filename = os.path.basename(file_path)
        self.file_path_var.set(filename)
        self.process_file_button.config(state='normal')

        # 드롭 영역 스타일 변경
        self.drop_frame.config(bg='#d5f4e6', relief='solid')
        self.drop_label.config(
            text=f"✅ 파일 선택됨\n{filename}",
            fg='#27ae60',
            bg='#d5f4e6'
        )

        self.update_status("📁 파일이 선택되었습니다 - 파싱 준비 완료", "success")
        self.log(f"📁 파일 선택: {file_path}")

    def clear_raw_input(self):
        """텍스트 입력창 클리어"""
        if self.is_processing:
            messagebox.showwarning("경고", "현재 처리 중입니다. 완료 후 다시 시도해주세요.")
            return

        self.raw_input.delete(1.0, tk.END)
        self.log("🧹 텍스트 입력창이 클리어되었습니다.")

    def clear_output(self):
        """모든 출력 영역 초기화"""
        try:
            # 통합 결과 초기화
            if hasattr(self, 'combined_text'):
                self.combined_text.delete('1.0', tk.END)

            # 파싱 결과만 초기화
            if hasattr(self, 'parsed_only_text'):
                self.parsed_only_text.delete('1.0', tk.END)

            # 로그 초기화
            if hasattr(self, 'log_text'):
                self.log_text.delete('1.0', tk.END)

            self.update_status("출력 영역이 초기화되었습니다.", "info")

        except Exception as e:
            print(f"출력 초기화 중 오류: {e}")

    def clear_all(self):
        """전체 초기화 - 모든 데이터와 UI 상태를 초기화"""
        try:
            # 진행 중인 작업이 있으면 중단
            if self.is_processing:
                self.cancel_processing_action()
                # 잠시 대기하여 작업 완전 중단
                self.root.after(100, self._complete_clear_all)
                return

            self._complete_clear_all()

        except Exception as e:
            print(f"전체 초기화 중 오류 발생: {e}")
            # 강제로라도 기본 초기화 수행
            self._force_clear_all()

    def _complete_clear_all(self):
        """전체 초기화 완료"""
        try:
            # 1. 파일 경로 초기화
            self.file_path = None
            self.file_path_var.set("")

            # 2. 모든 출력 영역 초기화
            self.clear_output()

            # 3. 텍스트 입력 초기화
            self.clear_raw_input()

            # 4. UI 상태 초기화
            self.unlock_ui()

            # 5. 버튼 상태 초기화
            self.process_file_button.config(state='disabled')
            self.process_text_button.config(state='normal')
            self.cancel_button.config(state='disabled')

            # 6. 드래그 앤 드롭 영역 초기화
            if hasattr(self, 'drop_frame') and hasattr(self, 'drop_label'):
                self.drop_frame.config(bg='#ecf0f1')
                self.drop_label.config(fg='#7f8c8d', bg='#ecf0f1')

            # 7. 프로그레스바 초기화
            if hasattr(self, 'progress_var'):
                self.progress_var.set(0)

            # 8. 첫 번째 탭으로 이동
            if hasattr(self, 'output_notebook'):
                self.output_notebook.select(0)

            # 9. 상태 메시지 초기화
            self.update_status("전체 초기화 완료", "success")

            # 10. 로그 메시지
            self.log("🔄 전체 초기화가 완료되었습니다.")

        except Exception as e:
            print(f"완전 초기화 중 오류: {e}")
            self._force_clear_all()

    def _force_clear_all(self):
        """강제 초기화 - 오류 발생 시 최소한의 초기화"""
        try:
            self.file_path = None
            if hasattr(self, 'file_path_var'):
                self.file_path_var.set("")
            if hasattr(self, 'raw_input'):
                self.raw_input.delete('1.0', tk.END)
            if hasattr(self, 'result_text'):
                self.result_text.delete('1.0', tk.END)
            if hasattr(self, 'log_text'):
                self.log_text.delete('1.0', tk.END)

            self.is_processing = False
            self.cancel_processing = False

            print("강제 초기화 완료")

        except Exception as e:
            print(f"강제 초기화 중에도 오류 발생: {e}")

    def update_status(self, message, status_type="info"):
        """상태 업데이트"""
        self.status_var.set(message)

        if status_type == "success":
            self.status_label.config(style='Success.TLabel')
        elif status_type == "error":
            self.status_label.config(style='Error.TLabel')
        elif status_type == "warning":
            self.status_label.config(style='Warning.TLabel')
        else:
            self.status_label.config(style='Subtitle.TLabel')

        self.root.update_idletasks()

    def log(self, message, show_time=True):
        """로그 출력"""
        self.log_text.config(state=tk.NORMAL)

        if show_time:
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_message = f"[{timestamp}] {message}\n"
        else:
            formatted_message = f"{message}\n"

        self.log_text.insert(tk.END, formatted_message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def show_result(self, results):
        """파싱 결과를 각각의 탭에 표시"""
        try:
            if isinstance(results, dict):
                # 통합 결과 탭에 표시
                combined_content = results.get('combined', '')
                if hasattr(self, 'combined_text'):
                    self.combined_text.delete('1.0', tk.END)
                    if combined_content:
                        self.combined_text.insert('1.0', combined_content)
                        self.log(f"📄 통합 결과: {len(combined_content)}자 표시됨")

                # 파싱 결과만 탭에 표시
                parsed_only_content = results.get('parsed_only', '')
                if hasattr(self, 'parsed_only_text'):
                    self.parsed_only_text.delete('1.0', tk.END)
                    if parsed_only_content:
                        self.parsed_only_text.insert('1.0', parsed_only_content)
                        self.log(f"🔍 파싱 결과만: {len(parsed_only_content)}자 표시됨")
                    else:
                        self.parsed_only_text.insert('1.0',
                                                     "파싱된 결과가 없습니다.\n\nQCAT이 처리할 수 있는 QMI 패킷이 입력에 포함되어 있는지 확인해주세요.")
                        self.log("⚠️ 파싱 결과가 비어있음")

                # 통계 정보 로깅
                if 'stats' in results:
                    stats = results['stats']
                    self.log(f"📊 처리 통계 - 라인: {stats.get('lines', 0)}, 패킷: {stats.get('packets', 0)}")

                # 파싱 결과가 있으면 해당 탭으로, 없으면 통합 결과 탭으로
                if parsed_only_content and parsed_only_content.strip():
                    self.output_notebook.select(1)  # 파싱 결과만 탭
                    self.log("🎯 '파싱 결과만' 탭으로 이동")
                else:
                    self.output_notebook.select(0)  # 통합 결과 탭
                    self.log("🎯 '통합 결과' 탭으로 이동")

            else:
                # 이전 버전 호환성 (문자열 결과)
                if hasattr(self, 'combined_text'):
                    self.combined_text.delete('1.0', tk.END)
                    self.combined_text.insert('1.0', str(results))
                if hasattr(self, 'parsed_only_text'):
                    self.parsed_only_text.delete('1.0', tk.END)
                    self.parsed_only_text.insert('1.0', "이전 버전 결과 형식입니다.")
                self.output_notebook.select(0)

        except Exception as e:
            self.log(f"❌ 결과 표시 중 오류: {e}")
            print(f"show_result 오류: {e}")

    def save_results(self):
        """결과를 파일로 저장"""
        try:
            from tkinter import filedialog

            # 현재 선택된 탭 확인
            current_tab = self.output_notebook.index(self.output_notebook.select())

            if current_tab == 0:  # 통합 결과 탭
                content = self.combined_text.get('1.0', tk.END).strip()
                default_name = "qmi_combined_result.txt"
                title = "통합 결과 저장"
            elif current_tab == 1:  # 파싱 결과만 탭
                content = self.parsed_only_text.get('1.0', tk.END).strip()
                default_name = "qmi_parsed_only.txt"
                title = "파싱 결과 저장"
            else:  # 로그 탭
                content = self.log_text.get('1.0', tk.END).strip()
                default_name = "qmi_process_log.txt"
                title = "처리 로그 저장"

            if not content:
                self.update_status("저장할 내용이 없습니다.", "warning")
                return

            file_path = filedialog.asksaveasfilename(
                title=title,
                initialfile=default_name,
                defaultextension=".txt",
                filetypes=[
                    ("텍스트 파일", "*.txt"),
                    ("모든 파일", "*.*")
                ]
            )

            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.update_status(f"결과가 저장되었습니다: {file_path}", "success")
                self.log(f"💾 결과 저장 완료: {file_path}")

        except Exception as e:
            self.update_status(f"저장 중 오류 발생: {e}", "error")
            self.log(f"❌ 저장 오류: {e}")

    def lock_ui(self):
        """처리 중 UI 잠금"""
        self.is_processing = True
        self.browse_button.config(state='disabled')
        self.process_file_button.config(state='disabled')
        self.process_text_button.config(state='disabled')
        self.cancel_button.config(state='normal')

        # 드래그 앤 드롭 비활성화
        self.drop_frame.config(bg='#f8f9fa')
        self.drop_label.config(fg='#adb5bd', bg='#f8f9fa')

    def unlock_ui(self):
        """UI 잠금 해제"""
        self.is_processing = False
        self.cancel_processing = False
        self.browse_button.config(state='normal')
        self.process_text_button.config(state='normal')
        self.cancel_button.config(state='disabled')

        if self.file_path:
            self.process_file_button.config(state='normal')

        # 드래그 앤 드롭 활성화
        if self.file_path:
            self.drop_frame.config(bg='#d5f4e6')
            self.drop_label.config(fg='#27ae60', bg='#d5f4e6')
        else:
            self.drop_frame.config(bg='#ecf0f1')
            self.drop_label.config(fg='#7f8c8d', bg='#ecf0f1')

    def cancel_processing_action(self):
        """처리 취소"""
        self.cancel_processing = True
        self.update_status("⏹️ 처리 취소 요청됨...", "warning")
        self.log("⏹️ 사용자가 처리 취소를 요청했습니다.")

    def start_file_processing(self):
        """파일 처리 시작"""
        if not self.file_path or self.is_processing:
            return

        if not os.path.exists(self.file_path):
            messagebox.showerror("오류", "선택한 파일이 존재하지 않습니다.")
            return

        # UI 잠금
        self.lock_ui()
        self.progress_var.set(0)
        self.update_status("⚡ 파일 처리 중...", "info")

        # 출력 파일 경로 설정
        input_file_path = os.path.abspath(self.file_path)
        input_dir = os.path.dirname(input_file_path)
        input_filename = os.path.basename(input_file_path)
        base_name = os.path.splitext(input_filename)[0]

        combined_path = os.path.join(input_dir, f"QCAT_{base_name}.txt")
        parsed_only_path = os.path.join(input_dir, f"QCAT_{base_name}_parsed_only.txt")

        # 별도 스레드에서 처리
        thread = threading.Thread(target=self.process_file_thread,
                                  args=(input_file_path, combined_path, parsed_only_path))
        thread.daemon = True
        thread.start()

    def process_file_thread(self, input_path, combined_path, parsed_only_path):
        """파일 처리 스레드"""
        try:
            self.log("🚀 QMI 로그 파일 처리를 시작합니다.")

            def progress_callback(message, progress=None):
                if self.cancel_processing:
                    raise Exception("사용자에 의해 처리가 취소되었습니다.")

                self.root.after(0, lambda: self.log(message, show_time=False))

                if progress is not None:
                    self.root.after(0, lambda: self.progress_var.set(progress))
                    if "%" in message:
                        self.root.after(0, lambda: self.update_status(f"⚡ {message}", "info"))

            result = self.processor.process_qmi_log(
                input_path, combined_path, parsed_only_path,
                progress_callback=progress_callback
            )

            if not self.cancel_processing:
                self.root.after(0, lambda: self.log("✅ 파일 처리가 완료되었습니다!"))
                self.root.after(0, lambda: self.update_status("✅ 파일 처리 완료!", "success"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "완료",
                    f"QMI 로그 파싱이 완료되었습니다!\n\n" 
                    f"출력 파일:\n- {os.path.basename(combined_path)}\n" 
                    f"- {os.path.basename(parsed_only_path)}\n\n"
                    f"폴더: {os.path.dirname(combined_path)}"
                ))

        except Exception as e:
            error_msg = f"❌ 파일 처리 중 오류: {str(e)}"
            self.root.after(0, lambda: self.log(error_msg))
            self.root.after(0, lambda: self.update_status("❌ 파일 처리 오류", "error"))
            if not self.cancel_processing:
                self.root.after(0, lambda: messagebox.showerror("오류", str(e)))

        finally:
            self.root.after(0, self.unlock_ui)
            self.root.after(0, lambda: self.progress_var.set(0))

    def process_raw_data(self):
        """텍스트 데이터 처리"""
        raw_data = self.raw_input.get(1.0, tk.END).strip()
        if not raw_data:
            messagebox.showwarning("경고", "처리할 텍스트를 입력해주세요.")
            return

        if self.is_processing:
            messagebox.showwarning("경고", "현재 처리 중입니다. 완료 후 다시 시도해주세요.")
            return

        # UI 잠금
        self.lock_ui()
        self.progress_var.set(0)
        self.update_status("⚡ 텍스트 처리 중...", "info")

        # 별도 스레드에서 처리
        thread = threading.Thread(target=self.process_text_thread, args=(raw_data,))
        thread.daemon = True
        thread.start()

    def process_text_thread(self, raw_data):
        """텍스트 처리 스레드"""
        try:
            self.root.after(0, lambda: self.log("🚀 텍스트 로그 처리를 시작합니다."))

            def progress_callback(message, progress=None):
                if self.cancel_processing:
                    raise Exception("사용자에 의해 처리가 취소되었습니다.")

                self.root.after(0, lambda: self.log(message, show_time=False))

                if progress is not None:
                    self.root.after(0, lambda: self.progress_var.set(progress))
                    if "%" in message:
                        self.root.after(0, lambda: self.update_status(f"⚡ {message}", "info"))

            result = self.processor.process_qmi_text(raw_data, progress_callback=progress_callback)

            if not self.cancel_processing:
                self.root.after(0, lambda: self.show_result(result))
                self.root.after(0, lambda: self.log("✅ 텍스트 처리가 완료되었습니다!"))
                self.root.after(0, lambda: self.update_status("✅ 텍스트 처리 완료!", "success"))

        except Exception as e:
            error_msg = f"❌ 텍스트 처리 중 오류: {str(e)}"
            self.root.after(0, lambda: self.log(error_msg))
            self.root.after(0, lambda: self.update_status("❌ 텍스트 처리 오류", "error"))
            if not self.cancel_processing:
                self.root.after(0, lambda: messagebox.showerror("오류", str(e)))

        finally:
            self.root.after(0, self.unlock_ui)
            self.root.after(0, lambda: self.progress_var.set(0))


if __name__ == '__main__':
    root = tk.Tk()
    app = QMIParserGUI(root)
    root.mainloop()