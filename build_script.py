#!/usr/bin/env python3
"""
QMI Parser를 Windows exe 파일로 빌드하는 스크립트
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_dependencies():
    """필요한 의존성 확인"""
    print("의존성 확인 중...")
    
    required_packages = ['pyinstaller', 'pywin32', 'tkinterdnd2']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package} 설치됨")
        except ImportError:
            missing_packages.append(package)
            print(f"✗ {package} 누락")
    
    if missing_packages:
        print(f"\n누락된 패키지 설치 중: {', '.join(missing_packages)}")
        for package in missing_packages:
            subprocess.run([sys.executable, '-m', 'pip', 'install', package], check=True)
        print("의존성 설치 완료!")
    
    return True


def create_version_info():
    """버전 정보 파일 생성"""
    version_content = """# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
# filevers and prodvers should be always a tuple with four items: (1, 2, 3, 4)
# Set not needed items to zero 0.
filevers=(1,0,0,0),
prodvers=(1,0,0,0),
# Contains a bitmask that specifies the valid bits 'flags'r
mask=0x3f,
# Contains a bitmask that specifies the Boolean attributes of the file.
flags=0x0,
# The operating system for which this file was designed.
# 0x4 - NT and there is no need to change it.
OS=0x4,
# The general type of file.
# 0x1 - the file is an application.
fileType=0x1,
# The function of the file.
# 0x0 - the function is not defined for this fileType
subtype=0x0,
# Creation date and time stamp.
date=(0, 0)
),
  kids=[
StringFileInfo(
  [
  StringTable(
    u'040904B0',
    [StringStruct(u'CompanyName', u'QMI Parser Team'),
    StringStruct(u'FileDescription', u'QMI Log Parser Application'),
    StringStruct(u'FileVersion', u'1.0.0.0'),
    StringStruct(u'InternalName', u'QMI-Parser'),
    StringStruct(u'LegalCopyright', u'Copyright © 2024'),
    StringStruct(u'OriginalFilename', u'QMI-Parser.exe'),
    StringStruct(u'ProductName', u'QMI Parser'),
    StringStruct(u'ProductVersion', u'1.0.0.0')])
  ]), 
VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)"""
    
    with open('version_info.txt', 'w', encoding='utf-8') as f:
        f.write(version_content)
    
    print("버전 정보 파일 생성 완료")


def build_exe():
    """exe 파일 빌드"""
    print("\nPyInstaller로 exe 파일 빌드 시작...")
    
    # 이전 빌드 결과 삭제
    if os.path.exists('dist'):
        shutil.rmtree('dist')
        print("이전 dist 폴더 삭제")
    
    if os.path.exists('build'):
        shutil.rmtree('build')
        print("이전 build 폴더 삭제")
    
    # PyInstaller 실행
    cmd = [
        'pyinstaller',
        '--onefile',                    # 단일 exe 파일
        '--windowed',                   # 콘솔 창 숨김
        '--name=QMI-Parser',            # exe 파일 이름
        '--distpath=dist',              # 출력 디렉토리
        '--workpath=build',             # 임시 디렉토리
        '--specpath=.',                 # spec 파일 위치
        '--clean',                      # 캐시 정리
        '--noconfirm',                  # 덮어쓰기 확인 없이 진행
        
        # 필요한 모듈들 명시적으로 포함
        '--hidden-import=tkinter',
        '--hidden-import=tkinter.ttk',
        '--hidden-import=tkinter.filedialog',
        '--hidden-import=tkinter.messagebox',
        '--hidden-import=tkinter.font',
        '--hidden-import=win32com.client',
        '--hidden-import=tkinterdnd2',
        '--hidden-import=pywintypes',
        '--hidden-import=pythoncom',
        
        # 추가 옵션
        '--add-data=constants.py;.',
        '--add-data=qmi_processor.py;.',
        '--add-data=qmi_gui.py;.',
        
        'main.py'
    ]
    
    # 버전 정보 파일이 있으면 추가
    if os.path.exists('version_info.txt'):
        cmd.extend(['--version-file=version_info.txt'])
    
    # 아이콘 파일이 있으면 추가
    if os.path.exists('icon.ico'):
        cmd.extend(['--icon=icon.ico'])
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✓ exe 파일 빌드 성공!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ 빌드 실패: {e}")
        print(f"오류 출력: {e.stderr}")
        return False


def create_portable_package():
    """포터블 패키지 생성"""
    print("\n포터블 패키지 생성 중...")
    
    # 패키지 폴더 생성
    package_dir = Path('QMI-Parser-Portable')
    if package_dir.exists():
        shutil.rmtree(package_dir)
    
    package_dir.mkdir()
    
    # exe 파일 복사
    exe_path = Path('dist/QMI-Parser.exe')
    if exe_path.exists():
        shutil.copy2(exe_path, package_dir / 'QMI-Parser.exe')
        print(f"✓ exe 파일 복사: {package_dir / 'QMI-Parser.exe'}")
    else:
        print("✗ exe 파일을 찾을 수 없습니다")
        return False
    
    # README 파일 생성
    readme_content = """# QMI Parser

## 사용법

1. QMI-Parser.exe를 실행합니다.
2. 파일 처리:
   - 상단의 파일 선택 영역에서 QMI 로그 파일을 선택하거나 드래그 앤 드롭
   - "파일 처리" 버튼 클릭
   - 처리 결과가 파일로 저장되고 우측 출력창에 표시됩니다

3. Raw Data 처리:
   - 좌측 "Raw Data 입력" 영역에 직접 로그 데이터 입력
   - "텍스트 처리" 버튼 클릭
   - 처리 결과가 우측 출력창에 바로 표시됩니다

## 요구사항

- Windows 7/8/10/11 (64-bit)
- QCAT 소프트웨어가 설치되어 있어야 합니다

## 문제 해결

- QCAT 관련 오류가 발생하면 QCAT이 올바르게 설치되어 있는지 확인하세요
- 파일 권한 오류가 발생하면 관리자 권한으로 실행해보세요

## 버전

- 버전: 1.0.0
- 빌드 날짜: 2024년
"""
    
    with open(package_dir / 'README.txt', 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    print(f"✓ 포터블 패키지 생성 완료: {package_dir}")
    return True


def main():
    """메인 빌드 프로세스"""
    print("=== QMI Parser Windows exe 빌드 ===\n")
    
    # 현재 디렉토리 확인
    required_files = ['main.py', 'constants.py', 'qmi_processor.py', 'qmi_gui.py']
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print(f"✗ 필요한 파일이 누락되었습니다: {', '.join(missing_files)}")
        return False
    
    try:
        # 1. 의존성 확인
        if not check_dependencies():
            return False
        
        # 2. 버전 정보 파일 생성
        create_version_info()
        
        # 3. exe 파일 빌드
        if not build_exe():
            return False
        
        # 4. 포터블 패키지 생성
        if not create_portable_package():
            return False
        
        print("\n=== 빌드 완료! ===")
        print("생성된 파일:")
        print(f"  - dist/QMI-Parser.exe")
        print(f"  - QMI-Parser-Portable/QMI-Parser.exe")
        print(f"  - QMI-Parser-Portable/README.txt")
        
        return True
        
    except Exception as e:
        print(f"✗ 빌드 중 오류 발생: {e}")
        return False
    
    finally:
        # 임시 파일 정리
        temp_files = ['version_info.txt', 'QMI-Parser.spec']
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
