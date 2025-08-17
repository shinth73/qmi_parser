## 프로젝트 패키지 및 가상환경 관리 
 uv 

## 실행파일 
pyinstaller --onefile --windowed --name=QMI-Parser --hidden-import=tkinter --hidden-import=tkinter.ttk --hidden-import=tkinter.filedialog --hidden-import=tkinter.messagebox --hidden-import=win32com.client --hidden-import=tkinterdnd2 main.py

## 생성 위치
프로젝트 폴더/
├── dist/
│   └── QMI-Parser.exe          # 실행 파일
├── QMI-Parser-Portable/
│   ├── QMI-Parser.exe          # 포터블 버전
│   └── README.txt              # 사용법 안내
├── build/                      # 임시 빌드 파일 (삭제 가능)
└── QMI-Parser.spec            # PyInstaller 설정 파일



## 배포시 주의사항
### ✅ **포함된 것들:**
- Python 런타임 (사용자가 Python을 설치할 필요 없음)
- 모든 필요한 Python 패키지
- tkinter GUI 라이브러리
- win32com 모듈

### ⚠️ **별도 필요한 것들:**
- **QCAT 소프트웨어**: QMI 파싱을 위해 반드시 설치되어 있어야 함
- **Windows 환경**: Windows 7/8/10/11에서 실행 가능

## 파일 크기 최적화 (선택사항)
exe 파일이 너무 크다면 다음 옵션을 추가할 수 있습니다:
``` python
# build.py의 cmd 리스트에 추가
'--exclude-module=matplotlib',
'--exclude-module=numpy',
'--exclude-module=pandas',
'--exclude-module=PIL',
# 사용하지 않는 다른 큰 모듈들 제외
```
