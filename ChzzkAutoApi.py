import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json
import webbrowser
from urllib.parse import urlparse, parse_qs
import threading
import time
import os
import pyperclip
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


class ChzzkAuthApp:
    def __init__(self, root):
        self.root = root
        self.root.title("네이버 치지직 API 인증")
        self.root.geometry("600x800")  # 좀 더 콤팩트한 UI 사이즈
        self.root.resizable(False, False)

        self.access_token = None
        self.refresh_token = None

        # 설정 파일 경로
        self.config_file = "chzzk_config.json"

        # 기본 URL은 숨겨진 상태로 유지
        self.base_url_var = tk.StringVar(value="https://openapi.chzzk.naver.com/")

        # 공유되는 클라이언트 ID
        self.client_id_var = tk.StringVar(value="")

        # 네이버 로그인 정보
        self.naver_id_var = tk.StringVar(value="")
        self.naver_pw_var = tk.StringVar(value="")

        # 2차 인증 설정
        self.use_manual_2fa_var = tk.BooleanVar(value=False)

        # 기타 설정 변수들
        self.redirect_uri_var = tk.StringVar(value="https%3A%2F%2Flocalhost%3A8080")
        self.url_state_var = tk.StringVar(value="zxclDasdfA25")
        self.client_secret_var = tk.StringVar(
            value="qKjtG6nhe9wAoJkSu08_v4a2Xf1E-32IsbS5BMoiwSA"
        )

        # 저장된 설정 로드
        self.load_config()

        self.create_widgets()

        # 변경 감지를 위한 트레이스 설정
        self.setup_traces()

    def create_widgets(self):
        # 굵게 표시할 라벨의 폰트 설정
        bold_font = ("Helvetica", 9, "bold")

        # Create main frame with smaller padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(
            main_frame, text="네이버 치지직 API 인증", font=("Helvetica", 14, "bold")
        )
        title_label.pack(pady=(0, 10))

        # 네이버 로그인 정보 프레임 - 패딩 축소
        login_frame = ttk.LabelFrame(
            main_frame, text="네이버 자동 로그인 설정", padding="5"
        )
        login_frame.pack(fill=tk.X, padx=3, pady=3)

        # 네이버 ID
        ttk.Label(login_frame, text="네이버 아이디:").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        ttk.Entry(login_frame, textvariable=self.naver_id_var, width=50).grid(
            row=0, column=1, padx=3, pady=2
        )

        # 네이버 비밀번호
        ttk.Label(login_frame, text="네이버 비밀번호:").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        pw_entry = ttk.Entry(
            login_frame, textvariable=self.naver_pw_var, width=50, show="*"
        )
        pw_entry.grid(row=1, column=1, padx=3, pady=2)

        # 2차 인증 체크박스 추가
        ttk.Checkbutton(
            login_frame,
            text="2차 인증 수동 처리 필요",
            variable=self.use_manual_2fa_var,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)

        # URL Construction frame - 패딩 축소
        url_frame = ttk.LabelFrame(
            main_frame, text="인증 URL 생성 및 코드 받기", padding="5"
        )
        url_frame.pack(fill=tk.X, padx=3, pady=3)

        # Client ID for URL - 공유 변수 사용, 굵게 표시
        ttk.Label(url_frame, text="클라이언트 ID:", font=bold_font).grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        client_id_entry = ttk.Entry(
            url_frame, textvariable=self.client_id_var, width=50
        )
        client_id_entry.grid(row=0, column=1, padx=3, pady=2)

        # Redirect URI, 굵게 표시
        ttk.Label(url_frame, text="리다이렉트 URI:", font=bold_font).grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        redirect_uri_entry = ttk.Entry(
            url_frame, textvariable=self.redirect_uri_var, width=50
        )
        redirect_uri_entry.grid(row=1, column=1, padx=3, pady=2)

        # State for URL, 굵게 표시 및 이름 변경
        ttk.Label(url_frame, text="state:", font=bold_font).grid(
            row=2, column=0, sticky=tk.W, pady=2
        )
        state_entry = ttk.Entry(url_frame, textvariable=self.url_state_var, width=50)
        state_entry.grid(row=2, column=1, padx=3, pady=2)

        # Generated URL
        ttk.Label(url_frame, text="생성된 URL:").grid(
            row=3, column=0, sticky=tk.W, pady=2
        )
        self.generated_url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.generated_url_var, width=50)
        url_entry.grid(row=3, column=1, padx=3, pady=2)

        # 초기 URL 생성
        self.update_url()

        # 코드받기 버튼 (WebDriver 자동화)
        buttons_frame = ttk.Frame(url_frame)
        buttons_frame.grid(row=4, column=0, columnspan=2, pady=5)

        self.get_code_button = ttk.Button(
            buttons_frame, text="코드받기", command=self.get_authorization_code
        )
        self.get_code_button.pack(side=tk.LEFT, padx=3)

        # 응답 URL 숨김 (내부적으로만 사용)
        self.response_url_var = tk.StringVar()

        # 쿼리 파라미터 추출 결과 표시 프레임
        params_frame = ttk.LabelFrame(url_frame, text="URL 쿼리 파라미터", padding="5")
        params_frame.grid(row=5, column=0, columnspan=2, pady=5, sticky=tk.W + tk.E)

        # CODE 파라미터
        ttk.Label(params_frame, text="CODE:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.extracted_code_var = tk.StringVar()
        ttk.Entry(params_frame, textvariable=self.extracted_code_var, width=50).grid(
            row=0, column=1, padx=3, pady=2
        )

        # state 파라미터
        ttk.Label(params_frame, text="state:").grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        self.extracted_state_var = tk.StringVar()
        ttk.Entry(params_frame, textvariable=self.extracted_state_var, width=50).grid(
            row=1, column=1, padx=3, pady=2
        )

        # Input fields - 패딩 축소
        input_frame = ttk.LabelFrame(main_frame, text="API 연결 매개변수", padding="5")
        input_frame.pack(fill=tk.X, padx=3, pady=3)

        # Client ID - 공유 변수 사용
        ttk.Label(input_frame, text="클라이언트 ID:").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        ttk.Entry(input_frame, textvariable=self.client_id_var, width=50).grid(
            row=0, column=1, padx=3, pady=2
        )

        # Client Secret, 굵게 표시
        ttk.Label(input_frame, text="클라이언트 시크릿:", font=bold_font).grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        ttk.Entry(input_frame, textvariable=self.client_secret_var, width=50).grid(
            row=1, column=1, padx=3, pady=2
        )

        # Authorization Code
        ttk.Label(input_frame, text="인증 코드:").grid(
            row=2, column=0, sticky=tk.W, pady=2
        )
        self.auth_code_var = tk.StringVar(value="")
        ttk.Entry(input_frame, textvariable=self.auth_code_var, width=50).grid(
            row=2, column=1, padx=3, pady=2
        )

        # State, 이름 변경
        ttk.Label(input_frame, text="state:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.state_var = tk.StringVar(value="")
        ttk.Entry(input_frame, textvariable=self.state_var, width=50).grid(
            row=3, column=1, padx=3, pady=2
        )

        # 버튼 제거 - 자동으로 토큰을 요청하도록 변경
        self.get_token_button = None  # 참조는 유지하되 실제 버튼은 없앰

        # Results frame - 패딩 축소
        results_frame = ttk.LabelFrame(main_frame, text="결과", padding="5")
        results_frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # Status
        ttk.Label(results_frame, text="상태:").grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        self.status_var = tk.StringVar(value="준비")
        status_label = ttk.Label(results_frame, textvariable=self.status_var)
        status_label.grid(row=0, column=1, sticky=tk.W, pady=2)

        # Access Token
        ttk.Label(results_frame, text="액세스 토큰:").grid(
            row=1, column=0, sticky=tk.NW, pady=2
        )
        self.access_token_text = tk.Text(
            results_frame, height=2, width=45, wrap=tk.WORD
        )
        self.access_token_text.grid(row=1, column=1, pady=2, padx=3)

        # Refresh Token
        ttk.Label(results_frame, text="리프레시 토큰:").grid(
            row=2, column=0, sticky=tk.NW, pady=2
        )
        self.refresh_token_text = tk.Text(
            results_frame, height=2, width=45, wrap=tk.WORD
        )
        self.refresh_token_text.grid(row=2, column=1, pady=2, padx=3)

        # 제작자 정보
        creator_label = ttk.Label(
            main_frame, text="제작자: FinN", font=("Helvetica", 8)
        )
        creator_label.pack(side=tk.BOTTOM, anchor=tk.SE, padx=5, pady=5)

    def setup_traces(self):
        """설정 값 변경 감지 및 저장을 위한 트레이스 설정"""
        # URL 관련 설정
        self.client_id_var.trace_add("write", self.save_config_callback)
        self.client_id_var.trace_add("write", self.update_url)
        self.redirect_uri_var.trace_add("write", self.save_config_callback)
        self.redirect_uri_var.trace_add("write", self.update_url)
        self.url_state_var.trace_add("write", self.save_config_callback)
        self.url_state_var.trace_add("write", self.update_url)

        # API 연결 매개변수
        self.client_secret_var.trace_add("write", self.save_config_callback)

        # 네이버 로그인 정보 - 자동 저장 추가
        self.naver_id_var.trace_add("write", self.save_config_callback)
        self.naver_pw_var.trace_add("write", self.save_config_callback)

        # 2차 인증 설정 저장
        self.use_manual_2fa_var.trace_add("write", self.save_config_callback)

    def save_config_callback(self, *args):
        """콜백 함수: 트레이스에서 호출 시 설정 저장"""
        self.save_config()

    def save_config(self):
        """설정을 JSON 파일로 저장"""
        config = {
            "client_id": self.client_id_var.get(),
            "redirect_uri": self.redirect_uri_var.get(),
            "state": self.url_state_var.get(),
            "client_secret": self.client_secret_var.get(),
            "naver_id": self.naver_id_var.get(),
            "naver_pw": self.naver_pw_var.get(),
            "use_manual_2fa": self.use_manual_2fa_var.get(),
        }

        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"설정 저장 오류: {str(e)}")
            messagebox.showerror("오류", f"설정 저장 중 오류 발생: {str(e)}")

    def load_config(self):
        """저장된 설정 파일에서 설정 로드"""
        if not os.path.exists(self.config_file):
            return

        try:
            if not os.path.exists(self.config_file):
                print("설정 파일이 없습니다. 기본 설정을 사용합니다.")
                return

            with open(self.config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            # 설정 값 적용
            if "client_id" in config:
                self.client_id_var.set(config["client_id"])
            if "redirect_uri" in config:
                self.redirect_uri_var.set(config["redirect_uri"])
            if "state" in config:
                self.url_state_var.set(config["state"])
            if "client_secret" in config:
                self.client_secret_var.set(config["client_secret"])
            if "naver_id" in config:
                self.naver_id_var.set(config["naver_id"])
            if "naver_pw" in config:
                self.naver_pw_var.set(config["naver_pw"])
            if "use_manual_2fa" in config:
                self.use_manual_2fa_var.set(config["use_manual_2fa"])

        except Exception as e:
            print(f"설정 로드 오류: {str(e)}")
            messagebox.showerror("오류", f"설정 로드 중 오류 발생: {str(e)}")

    def update_url(self, *args):
        """실시간으로 URL 업데이트"""
        client_id = self.client_id_var.get()
        redirect_uri = self.redirect_uri_var.get()
        state = self.url_state_var.get()

        url = f"https://chzzk.naver.com/account-interlock?clientId={client_id}&redirectUri={redirect_uri}&state={state}"
        self.generated_url_var.set(url)

    def get_authorization_code(self):
        """WebDriver를 사용하여 자동으로 인증 코드 받기"""
        # 버튼 비활성화
        self.get_code_button.config(state=tk.DISABLED)
        self.status_var.set("브라우저 자동화 중...")
        self.root.update()

        # 쓰레드로 실행하여 UI가 멈추지 않도록 함
        threading.Thread(target=self._run_webdriver, daemon=True).start()

    def _run_webdriver(self):
        """백그라운드에서 Selenium WebDriver 실행"""
        driver = None
        try:
            # Chrome 옵션 설정
            chrome_options = Options()
            # 필요에 따라 추가 옵션 설정 (headless 모드 등)
            # chrome_options.add_argument("--headless")

            # WebDriver 초기화
            self.root.after(0, lambda: self.status_var.set("웹드라이버 초기화 중..."))
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=chrome_options
            )

            # 타임아웃 설정
            driver.set_page_load_timeout(60)

            # 상태값을 API 연결 매개변수에 설정
            self.root.after(0, lambda: self.state_var.set(self.url_state_var.get()))

            # 네이버 로그인 처리
            naver_id = self.naver_id_var.get()
            naver_pw = self.naver_pw_var.get()
            use_manual_2fa = self.use_manual_2fa_var.get()

            if naver_id and naver_pw:
                self.root.after(
                    0, lambda: self.status_var.set("네이버 로그인 페이지 로딩 중...")
                )

                # 네이버 로그인 페이지 접속
                login_url = "https://nid.naver.com/nidlogin.login"
                driver.get(login_url)

                # 페이지 로딩 대기
                time.sleep(2)

                # ID 필드 찾기
                id_field = driver.find_element(By.ID, "id")
                id_field.click()

                # pyperclip을 사용하여 ID 입력
                self.root.after(0, lambda: self.status_var.set("아이디 입력 중..."))
                pyperclip.copy(naver_id)

                # 클립보드 내용 붙여넣기 (Ctrl+V)
                ActionChains(driver).key_down(Keys.CONTROL).send_keys("v").key_up(
                    Keys.CONTROL
                ).perform()
                time.sleep(0.5)

                # 비밀번호 필드 찾기
                pw_field = driver.find_element(By.ID, "pw")
                pw_field.click()

                # pyperclip을 사용하여 비밀번호 입력
                self.root.after(0, lambda: self.status_var.set("비밀번호 입력 중..."))
                pyperclip.copy(naver_pw)

                # 클립보드 내용 붙여넣기 (Ctrl+V)
                ActionChains(driver).key_down(Keys.CONTROL).send_keys("v").key_up(
                    Keys.CONTROL
                ).perform()
                time.sleep(0.5)

                # 로그인 버튼 클릭
                self.root.after(0, lambda: self.status_var.set("로그인 중..."))
                login_button = driver.find_element(By.CLASS_NAME, "btn_login")
                login_button.click()

                # 로그인 처리 대기
                time.sleep(3)

                # 수동 2차 인증 처리
                if use_manual_2fa or (
                    "otp" in driver.current_url
                    or "2ndauth" in driver.current_url
                    or "2-step" in driver.current_url
                ):
                    self.root.after(
                        0,
                        lambda: self.status_var.set(
                            "2차 인증 필요: 브라우저에서 인증 진행 중..."
                        ),
                    )

                    # 수동 2FA 체크박스가 선택되어 있다면 추가 안내 메시지 표시
                    if use_manual_2fa:
                        self.root.after(
                            0,
                            lambda: messagebox.showinfo(
                                "2차 인증 안내",
                                "2차 인증을 위해 네이버 로그인 페이지에서 인증을 완료해주세요.\n\n"
                                "• 브라우저 창에서 로그인을 완료하신 후\n"
                                "• 필요한 경우 OTP/SMS/앱 인증을 진행해주세요.\n\n"
                                "인증이 완료되면 '확인' 버튼을 클릭하세요.",
                            ),
                        )
                    else:
                        # 자동 감지된 2FA의 경우 다른 메시지 표시
                        self.root.after(
                            0,
                            lambda: messagebox.showinfo(
                                "2차 인증 필요",
                                "네이버 2차 인증이 필요합니다. 브라우저에서 인증을 완료해주세요.\n\n"
                                "• SMS/이메일로 받은 인증 코드를 입력하거나\n"
                                "• 네이버 앱에서 알림을 확인하여 승인해주세요.\n\n"
                                "인증이 완료되면 '확인' 버튼을 클릭하세요.",
                            ),
                        )

                    # 네이버 로그인 확인 대기
                    # 사용자가 수동으로 확인한 시점부터 진행
                    # 로그인이 필요한 페이지가 아닌지 확인 (네이버 로그인 URL이 아닌 경우)
                    wait_start = time.time()
                    max_wait_time = 300  # 5분 대기 시간

                    while "nid.naver.com" in driver.current_url:
                        # 상태 업데이트
                        elapsed = int(time.time() - wait_start)
                        if elapsed % 10 == 0:  # 10초마다 상태 메시지 업데이트
                            self.root.after(
                                0,
                                lambda t=elapsed: self.status_var.set(
                                    f"2차 인증 대기 중... ({t}초 경과)"
                                ),
                            )

                        time.sleep(1)

                        # 대기 시간 초과 체크
                        if time.time() - wait_start > max_wait_time:
                            # 타임아웃 되었지만 계속 대기
                            user_response = messagebox.askretrycancel(
                                "대기 시간 초과",
                                "2차 인증 대기 시간이 초과되었습니다. 계속 대기하시겠습니까?",
                            )
                            if user_response:
                                # 대기 시간 재설정
                                wait_start = time.time()
                            else:
                                raise TimeoutException(
                                    "2차 인증 시간 초과 (사용자 취소)"
                                )

                    self.root.after(
                        0, lambda: self.status_var.set("2차 인증 완료, 진행 중...")
                    )

            # 인증 URL 열기
            auth_url = self.generated_url_var.get()
            self.root.after(0, lambda: self.status_var.set("인증 페이지 로딩 중..."))
            driver.get(auth_url)

            # 네이버 동의 화면이 나타날 경우 동의 버튼 클릭
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.ID, "agree_btn"))
                ).click()
                self.root.after(0, lambda: self.status_var.set("인증 동의 처리 중..."))
            except:
                # 동의 버튼이 없으면 넘어감
                pass

            # 사용자에게 안내 메시지 표시
            if not (naver_id and naver_pw):
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "안내",
                        "브라우저에서 로그인 및 인증을 완료해주세요. 완료 후 리다이렉트된 페이지를 기다려주세요.",
                    ),
                )

            # 리다이렉트 URL 감지
            self.root.after(0, lambda: self.status_var.set("리다이렉트 감지 중..."))

            # 10분(600초) 타임아웃 설정
            max_wait_time = 600
            start_time = time.time()

            # localhost 또는 리다이렉트 URI의 일부를 포함하는 URL로 리다이렉트될 때까지 대기
            redirect_host = urlparse(
                self.redirect_uri_var.get().replace("%3A", ":").replace("%2F", "/")
            ).netloc

            while True:
                current_url = driver.current_url

                # 리다이렉트 감지 - URL에 'code=' 또는 리다이렉트 호스트 포함 확인
                if "code=" in current_url or redirect_host in current_url:
                    # 응답 URL 설정 및 파싱
                    self.root.after(
                        0, lambda u=current_url: self.response_url_var.set(u)
                    )
                    self.root.after(0, lambda: self.parse_response_url())
                    break

                # 타임아웃 체크
                if time.time() - start_time > max_wait_time:
                    raise TimeoutException("인증 프로세스 타임아웃")

                # CPU 사용량 줄이기 위한 잠시 대기
                time.sleep(0.5)

            # 결과 확인 후 브라우저 종료
            self.root.after(
                0, lambda: self.status_var.set("인증 완료, 브라우저 종료 중...")
            )

        except Exception as e:
            error_msg = f"브라우저 자동화 중 오류: {str(e)}"
            self.root.after(0, lambda: self.status_var.set(error_msg))
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("오류", msg))
        finally:
            # 드라이버 종료
            if driver:
                driver.quit()
            # 처리 완료 후 코드받기 버튼 다시 활성화
            self.root.after(0, lambda: self.get_code_button.config(state=tk.NORMAL))

    def parse_response_url(self):
        """응답 URL에서 코드와 상태값 파싱"""
        response_url = self.response_url_var.get()

        if not response_url:
            messagebox.showerror("오류", "응답 URL을 입력해주세요.")
            return

        try:
            parsed_url = urlparse(response_url)
            query_params = parse_qs(parsed_url.query)

            code = ""
            state = ""

            if "code" in query_params:
                code = query_params["code"][0]
                self.auth_code_var.set(code)
                self.extracted_code_var.set(code)

            if "state" in query_params:
                state = query_params["state"][0]
                self.state_var.set(state)
                self.extracted_state_var.set(state)

            self.status_var.set("코드 추출 완료")

            # 쿼리 파라미터가 없거나 필요한 파라미터가 없는 경우
            if not code or not state:
                messagebox.showwarning(
                    "주의",
                    "URL에서 필요한 모든 파라미터를 찾을 수 없습니다. 올바른 응답 URL을 입력했는지 확인하세요.",
                )
            else:
                # 성공 메시지 없이 바로 액세스 토큰 요청 - 지연 시간 줄임
                self.root.after(50, self.get_access_token)

        except Exception as e:
            self.status_var.set(f"URL 파싱 오류: {str(e)}")
            messagebox.showerror("오류", f"URL 파싱 중 오류 발생: {str(e)}")

    def get_access_token(self):
        # 버튼 없이 진행
        self.status_var.set("액세스 토큰 요청 중...")
        self.root.update()

        try:
            # Get values from input fields
            base_url = self.base_url_var.get()
            client_id = self.client_id_var.get()
            client_secret = self.client_secret_var.get()
            auth_code = self.auth_code_var.get()
            state = self.state_var.get()

            # Make sure base_url ends with a slash
            if not base_url.endswith("/"):
                base_url += "/"

            # Prepare API request
            url = f"{base_url}auth/v1/token"

            response = requests.post(
                url=url,
                json={
                    "grantType": "authorization_code",
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "code": auth_code,
                    "state": state,
                },
            )

            # Update status with response code
            status_txt = f"응답 상태: {response.status_code}"
            self.status_var.set(status_txt)

            # Process response
            if response.status_code == 200:
                data = json.loads(response.text)

                # Update token fields
                self.access_token = data["content"]["accessToken"]
                self.refresh_token = data["content"]["refreshToken"]

                self.access_token_text.delete(1.0, tk.END)
                self.access_token_text.insert(tk.END, self.access_token)

                self.refresh_token_text.delete(1.0, tk.END)
                self.refresh_token_text.insert(tk.END, self.refresh_token)

                messagebox.showinfo("성공", "액세스 토큰을 성공적으로 가져왔습니다!")
            else:
                error_msg = f"오류: {response.status_code}\n{response.text}"
                self.access_token_text.delete(1.0, tk.END)
                self.refresh_token_text.delete(1.0, tk.END)
                messagebox.showerror("오류", error_msg)

        except Exception as e:
            self.status_var.set(f"오류: {str(e)}")
            messagebox.showerror("예외", str(e))

        # 버튼이 없으므로 재활성화 필요 없음
        pass


def main():
    root = tk.Tk()
    app = ChzzkAuthApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
