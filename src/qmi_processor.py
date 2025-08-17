
"""
QMI 로그 처리를 담당하는 핵심 클래스 및 함수
"""
import os
import io
import re
import struct
import win32com.client

# constants import 처리
try:
    from constants import LOG_PACKET_DEFAULT, QCAT_MODEL_NUMBER, MAX_OUTPUT_BUF_SIZE
except ImportError:
    # constants.py가 같은 폴더에 없는 경우 직접 정의
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