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


def process_qmi_packet(qcat_app, combined_fh, parsed_only_fh, log_packet):
    """
    원본 QMI.py의 process_qmi_packet 함수와 동일
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
        # The regex replaces QCAT's detailed timestamp and header with a simple confirmation.
        parsed_text = re.sub(
            r' ([0-9]{2}):([0-9]{2}):([0-9]{2}\.[0-9]{1,9})\s+\[.{2,8}\]\s+(0x....)  QMI Link 1 TX PDU',
            'builded. Parsed by QCAT',
            parsed_object.Text
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
            line_count = 0
            processed_packets = 0

            lines = input_text.strip().split('\n')
            total_lines = len(lines)

            if progress_callback:
                progress_callback(f"총 {total_lines}라인 처리 시작")

            for txt_line in lines:
                line_count += 1

                # 진행률 업데이트
                if line_count % 100 == 0 and progress_callback:
                    progress = int((line_count / total_lines) * 100)
                    progress_callback(f"처리 중... {progress}% (라인: {line_count}, 패킷: {processed_packets})")

                # 원본 라인을 combined 출력에 기록 (빈 라인이 아닌 경우)
                if txt_line.strip():
                    combined_output.write(txt_line + '\n')

                is_data_line = re.search(r'RIL-RAWDATA..[0-9,A-F]{2} ', txt_line)

                if is_data_line:
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
                                progress_callback(f"경고: 16진수 문자열 디코딩 실패: {txt_line.strip()}")

                elif is_accumulating:
                    process_qmi_packet(self.qcat_app, combined_output, parsed_only_output, log_packet)
                    processed_packets += 1
                    # Reset state
                    log_packet = LOG_PACKET_DEFAULT
                    qmi_packet_accum_length = 0
                    qmi_packet_expected_length = 0
                    is_accumulating = False

                if is_accumulating and (
                        (qmi_packet_expected_length > 0 and qmi_packet_accum_length >= qmi_packet_expected_length) or
                        (qmi_packet_accum_length >= MAX_OUTPUT_BUF_SIZE)
                ):
                    process_qmi_packet(self.qcat_app, combined_output, parsed_only_output, log_packet)
                    processed_packets += 1
                    # Reset state
                    log_packet = LOG_PACKET_DEFAULT
                    qmi_packet_accum_length = 0
                    qmi_packet_expected_length = 0
                    is_accumulating = False

            # 마지막 패킷 처리
            if is_accumulating:
                if progress_callback:
                    progress_callback("텍스트 끝 도달, 마지막 누적 패킷 처리 중...")
                process_qmi_packet(self.qcat_app, combined_output, parsed_only_output, log_packet)
                processed_packets += 1

            if progress_callback:
                progress_callback(f"\n처리 완료: {line_count}라인, {processed_packets}패킷 처리됨")

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
                progress_callback(error_msg)
            raise e

    def process_qmi_log(self, dump_file_path, combined_file_path, parsed_only_file_path, progress_callback=None):
        """
        QMI 로그 파일을 파싱하는 메인 함수 (원본 QMI.py 로직 사용)
        """
        try:
            # QCAT 애플리케이션 시작
            self.qcat_app = win32com.client.Dispatch('QCAT6.Application')
            if progress_callback:
                progress_callback(f"QCAT 버전: {self.qcat_app.AppVersion}")
                progress_callback(f"SILK 버전: {self.qcat_app.SILKVersion}\n")

            with open(dump_file_path, 'r', encoding='utf-8', errors='ignore') as dump_fh, \
                    open(combined_file_path, 'w', encoding='utf-8') as combined_fh, \
                    open(parsed_only_file_path, 'w', encoding='utf-8') as parsed_only_fh:

                log_packet = LOG_PACKET_DEFAULT
                qmi_packet_accum_length = 0
                qmi_packet_expected_length = 0
                is_accumulating = False
                line_count = 0
                processed_packets = 0

                # 파일 크기 계산 (진행률 표시용)
                try:
                    file_size = os.path.getsize(dump_file_path)
                    if progress_callback:
                        progress_callback(f"파일 크기: {file_size:,} bytes")
                except Exception:
                    file_size = 0

                for txt_line in dump_fh:
                    line_count += 1

                    # 진행률 업데이트 (1000라인마다)
                    if line_count % 1000 == 0 and progress_callback:
                        progress_callback(f"처리 중... 라인: {line_count:,}, 패킷: {processed_packets}")

                    # 원본 라인을 combined 파일에 기록 (빈 라인이 아닌 경우)
                    if txt_line.strip():
                        combined_fh.write(txt_line)

                    is_data_line = re.search(r'RIL-RAWDATA..[0-9,A-F]{2} ', txt_line)

                    if is_data_line:
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
                                    progress_callback(f"경고: 16진수 문자열 디코딩 실패: {txt_line.strip()}")

                    elif is_accumulating:
                        process_qmi_packet(self.qcat_app, combined_fh, parsed_only_fh, log_packet)
                        processed_packets += 1
                        # 상태 초기화
                        log_packet = LOG_PACKET_DEFAULT
                        qmi_packet_accum_length = 0
                        qmi_packet_expected_length = 0
                        is_accumulating = False

                    if is_accumulating and (
                            (
                                    qmi_packet_expected_length > 0 and qmi_packet_accum_length >= qmi_packet_expected_length) or
                            (qmi_packet_accum_length >= MAX_OUTPUT_BUF_SIZE)
                    ):
                        process_qmi_packet(self.qcat_app, combined_fh, parsed_only_fh, log_packet)
                        processed_packets += 1
                        # 상태 초기화
                        log_packet = LOG_PACKET_DEFAULT
                        qmi_packet_accum_length = 0
                        qmi_packet_expected_length = 0
                        is_accumulating = False

                # 마지막 패킷 처리
                if is_accumulating:
                    if progress_callback:
                        progress_callback("파일 끝 도달, 마지막 누적 패킷 처리 중...")
                    process_qmi_packet(self.qcat_app, combined_fh, parsed_only_fh, log_packet)
                    processed_packets += 1

                if progress_callback:
                    progress_callback(f"\n처리 완료: {line_count:,}라인, {processed_packets}패킷 처리됨")

        except Exception as e:
            error_msg = f"오류 발생: {e}"
            if "pywintypes.com_error" in str(type(e)):
                error_msg += "\nQCAT이 올바르게 설치되거나 등록되지 않았을 수 있습니다."
            if self.qcat_app:
                error_msg += f"\nQCAT 마지막 오류: {self.qcat_app.LastError}"

            if progress_callback:
                progress_callback(error_msg)
            raise e

        finally:
            # COM 객체 해제 (단일 패킷 처리에서는 해제하지 않음)
            pass


class QMIParserGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("QMI Log Parser")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)

        # 드래그 앤 드롭을 위한 변수
        self.file_path = None
        self.processor = QMILogProcessor()
        self.is_processing = False

        self.setup_ui()
        self.setup_drag_drop()

    def setup_ui(self):
        # 메인 프레임
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 상단 프레임 (파일 선택과 Raw Data 입력)
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        # 파일 선택 영역 (크기 축소)
        file_frame = ttk.LabelFrame(top_frame, text="파일 처리", padding="5")
        file_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))

        # 드래그 앤 드롭 영역 (크기 축소)
        self.drop_label = ttk.Label(file_frame,
                                    text="QMI 로그 파일 드래그\n또는 파일 선택 클릭",
                                    font=('맑은 고딕', 10),
                                    foreground='gray',
                                    background='lightgray',
                                    relief='solid',
                                    borderwidth=1,
                                    anchor='center')
        self.drop_label.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5), ipady=15)

        # 파일 선택 버튼과 경로
        button_path_frame = ttk.Frame(file_frame)
        button_path_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E))

        ttk.Button(button_path_frame, text="파일 선택", command=self.browse_file).pack(side=tk.LEFT)

        self.file_path_var = tk.StringVar()
        self.file_label = ttk.Label(button_path_frame, textvariable=self.file_path_var, foreground='blue')
        self.file_label.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)

        # 파일 처리 버튼
        self.process_button = ttk.Button(file_frame, text="파일 파싱 시작", command=self.start_processing, state='disabled')
        self.process_button.grid(row=2, column=0, pady=(5, 0), sticky=tk.W)

        # Raw Data 입력 영역
        raw_frame = ttk.LabelFrame(top_frame, text="텍스트 로그 직접 입력", padding="5")
        raw_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))

        # Raw Data 입력창
        input_frame = ttk.Frame(raw_frame)
        input_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        ttk.Label(raw_frame, text="QMI 로그 텍스트를 직접 입력하세요:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))

        self.raw_input = tk.Text(input_frame, height=4, wrap=tk.WORD, font=('Consolas', 9))
        raw_scrollbar = ttk.Scrollbar(input_frame, orient="vertical", command=self.raw_input.yview)
        self.raw_input.configure(yscrollcommand=raw_scrollbar.set)

        self.raw_input.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        raw_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        input_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))

        # Raw Data 처리 버튼
        raw_button_frame = ttk.Frame(raw_frame)
        raw_button_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))

        ttk.Button(raw_button_frame, text="텍스트 파싱", command=self.process_raw_data).pack(side=tk.LEFT)
        ttk.Button(raw_button_frame, text="입력 클리어", command=self.clear_raw_input).pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(raw_button_frame, text="샘플 데이터", command=self.insert_sample_data).pack(side=tk.LEFT, padx=(5, 0))

        # 하단 프레임 (상태와 버튼)
        middle_frame = ttk.Frame(main_frame)
        middle_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Button(middle_frame, text="전체 클리어", command=self.clear_all).pack(side=tk.LEFT)

        # 처리 상태 라벨
        self.status_var = tk.StringVar()
        self.status_var.set("대기 중...")
        self.status_label = ttk.Label(middle_frame, textvariable=self.status_var, foreground='blue')
        self.status_label.pack(side=tk.LEFT, padx=(20, 0))

        # 출력 영역 (처리 로그와 공통 사용)
        output_frame = ttk.LabelFrame(main_frame, text="처리 로그 / 파싱 결과", padding="5")
        output_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 텍스트 위젯과 스크롤바
        text_frame = ttk.Frame(output_frame)
        text_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.output_text = tk.Text(text_frame, height=20, wrap=tk.WORD, font=('Consolas', 9))
        output_scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=output_scrollbar.set)

        self.output_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        output_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # Grid weight 설정
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)  # 출력 영역이 확장되도록

        top_frame.columnconfigure(0, weight=1)
        top_frame.columnconfigure(1, weight=2)  # Raw Data 영역을 더 크게
        file_frame.columnconfigure(1, weight=1)
        raw_frame.columnconfigure(0, weight=1)
        raw_frame.rowconfigure(1, weight=1)

        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

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
        self.log("샘플 QMI 로그 데이터가 입력되었습니다.")

    def setup_drag_drop(self):
        # 드래그 앤 드롭 이벤트 바인딩
        self.drop_label.bind('<Button-1>', self.on_drop_click)
        self.drop_label.bind('<B1-Motion>', self.on_drag)
        self.drop_label.bind('<ButtonRelease-1>', self.on_drop)

        # tkinter.dnd를 사용하지 않고 간단한 방법으로 구현
        # Windows에서 파일 드롭 지원
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.on_file_drop)
        except:
            # tkinterdnd2가 없는 경우 파일 선택 버튼만 사용
            pass

    def on_drop_click(self, event):
        self.browse_file()

    def on_drag(self, event):
        pass

    def on_drop(self, event):
        pass

    def on_file_drop(self, event):
        files = event.data.split()
        if files:
            self.set_file_path(files[0])

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="QMI 로그 파일 선택",
            filetypes=[("텍스트 파일", "*.txt"), ("로그 파일", "*.log"), ("모든 파일", "*.*")]
        )
        if file_path:
            self.set_file_path(file_path)

    def set_file_path(self, file_path):
        self.file_path = file_path
        self.file_path_var.set(os.path.basename(file_path))
        self.process_button.config(state='normal')
        self.drop_label.config(text=f"선택됨:\n{os.path.basename(file_path)}",
                               foreground='blue', background='lightblue')
        self.status_var.set("파일 선택됨 - 파싱 준비 완료")
        self.log("파일이 선택되었습니다: " + file_path)

    def clear_raw_input(self):
        self.raw_input.delete(1.0, tk.END)
        self.log("텍스트 입력창이 클리어되었습니다.")

    def clear_all(self):
        self.file_path = None
        self.file_path_var.set("")
        self.process_button.config(state='disabled')
        self.drop_label.config(text="QMI 로그 파일 드래그\n또는 파일 선택 클릭",
                               foreground='gray', background='lightgray')
        self.status_var.set("대기 중...")
        self.output_text.delete(1.0, tk.END)
        self.raw_input.delete(1.0, tk.END)
        self.is_processing = False
        self.log("모든 내용이 클리어되었습니다.")

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.output_text.see(tk.END)
        self.root.update_idletasks()

    def show_output(self, message, is_parsed_result=False):
        if is_parsed_result:
            self.output_text.insert(tk.END, "\n" + "=" * 60 + "\n")
            self.output_text.insert(tk.END, "파싱 결과:\n")
            self.output_text.insert(tk.END, "=" * 60 + "\n")
            self.output_text.insert(tk.END, message + "\n")
            self.output_text.insert(tk.END, "=" * 60 + "\n\n")
        else:
            self.log(message)
        self.output_text.see(tk.END)
        self.root.update_idletasks()

    def update_status(self, message):
        self.status_var.set(message)
        self.root.update_idletasks()

    def process_raw_data(self):
        raw_data = self.raw_input.get(1.0, tk.END).strip()
        if not raw_data:
            messagebox.showwarning("경고", "텍스트 로그를 입력해주세요.")
            return

        self.log(f"텍스트 로그 파싱 시작 (총 {len(raw_data.split())}라인)")
        self.update_status("텍스트 처리 중...")

        # 별도 스레드에서 처리
        thread = threading.Thread(target=self.process_raw_data_thread, args=(raw_data,))
        thread.daemon = True
        thread.start()

    def process_raw_data_thread(self, raw_data):
        try:
            def progress_callback(message):
                self.root.after(0, lambda: self.log(message))
                # 상태 업데이트
                if "처리 중..." in message:
                    status_part = message.split("처리 중...")
                    if len(status_part) > 1:
                        self.root.after(0, lambda: self.update_status("처리 중... " + status_part[1].strip()))

            result = self.processor.process_qmi_text(raw_data, progress_callback=progress_callback)

            # 결과 표시
            combined_result = result['combined']
            parsed_only_result = result['parsed_only']
            stats = result['stats']

            output_message = f"=== 통합 결과 (Combined) ===\n{combined_result}\n"
            output_message += f"=== 파싱 결과만 (Parsed Only) ===\n{parsed_only_result}\n"
            output_message += f"=== 통계 ===\n처리된 라인: {stats['lines']}\n처리된 패킷: {stats['packets']}"

            self.root.after(0, lambda: self.show_output(output_message, is_parsed_result=True))
            self.root.after(0, lambda: self.update_status("텍스트 파싱 완료"))

        except Exception as e:
            error_msg = f"텍스트 파싱 중 오류: {str(e)}"
            self.root.after(0, lambda: self.log(error_msg))
            self.root.after(0, lambda: self.update_status("텍스트 파싱 오류"))

    def start_processing(self):
        if not self.file_path:
            messagebox.showerror("오류", "파일을 선택해주세요.")
            return

        if self.is_processing:
            messagebox.showwarning("경고", "이미 처리 중입니다.")
            return

        # 선택된 파일과 같은 폴더에 출력 파일 생성
        # 절대 경로로 변환하여 확실하게 같은 폴더에 생성되도록 함
        input_file_path = os.path.abspath(self.file_path)
        input_dir = os.path.dirname(input_file_path)
        input_filename = os.path.basename(input_file_path)
        base_name = os.path.splitext(input_filename)[0]

        combined_path = os.path.join(input_dir, f"QCAT_{base_name}.txt")
        parsed_only_path = os.path.join(input_dir, f"QCAT_{base_name}_parsed_only.txt")

        # 디버깅을 위한 로그 추가
        self.log(f"입력 파일 절대 경로: {input_file_path}")
        self.log(f"출력 폴더: {input_dir}")
        self.log(f"생성될 Combined 파일: {combined_path}")
        self.log(f"생성될 Parsed Only 파일: {parsed_only_path}")

        # 출력 폴더에 쓰기 권한이 있는지 확인
        if not os.access(input_dir, os.W_OK):
            messagebox.showerror("오류", f"출력 폴더에 쓰기 권한이 없습니다: {input_dir}")
            return

        # 처리 시작
        self.is_processing = True
        self.process_button.config(state='disabled')
        self.update_status("파일 처리 중...")

        # 별도 스레드에서 처리 실행
        thread = threading.Thread(target=self.process_file,
                                  args=(input_file_path, combined_path, parsed_only_path))
        thread.daemon = True
        thread.start()

    def process_file(self, input_path, combined_path, parsed_only_path):
        try:
            self.log("QMI 로그 파싱을 시작합니다...")
            self.log(f"입력 파일: {input_path}")
            self.log(f"Combined 출력: {combined_path}")
            self.log(f"Parsed Only 출력: {parsed_only_path}")

            def progress_callback(message):
                self.log(message)
                # 상태 업데이트
                if "처리 중..." in message:
                    status_part = message.split("처리 중...")
                    if len(status_part) > 1:
                        self.root.after(0, lambda: self.update_status("처리 중... " + status_part[1].strip()))

            self.processor.process_qmi_log(
                input_path,
                combined_path,
                parsed_only_path,
                progress_callback=progress_callback
            )

            # 파일이 실제로 생성되었는지 확인
            if os.path.exists(combined_path):
                self.log(f"✓ Combined 파일 생성 확인: {combined_path}")
            else:
                self.log(f"✗ Combined 파일 생성 실패: {combined_path}")

            if os.path.exists(parsed_only_path):
                self.log(f"✓ Parsed Only 파일 생성 확인: {parsed_only_path}")
            else:
                self.log(f"✗ Parsed Only 파일 생성 실패: {parsed_only_path}")

            self.log("파싱이 완료되었습니다!")

            # 완료 상태 업데이트
            self.root.after(0, lambda: self.update_status("파일 파싱 완료!"))

            # 완료 메시지 박스 표시
            self.root.after(0, lambda: messagebox.showinfo("완료",
                                                           f"QMI 로그 파싱이 완료되었습니다!\n\n출력 파일:\n- {os.path.basename(combined_path)}\n- {os.path.basename(parsed_only_path)}\n\n폴더: {os.path.dirname(combined_path)}"))

        except Exception as e:
            error_msg = f"파싱 중 오류가 발생했습니다: {str(e)}"
            self.log(error_msg)
            self.root.after(0, lambda: self.update_status("파일 파싱 오류"))
            self.root.after(0, lambda: messagebox.showerror("오류", error_msg))

        finally:
            # UI 상태 복구
            self.root.after(0, self.processing_finished)

    def processing_finished(self):
        self.is_processing = False
        self.process_button.config(state='normal')


def main():
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