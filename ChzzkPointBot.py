import sys
import json
import random
import time
import threading
import socketio
import requests
import tkinter as tk
import os
import tempfile
from pathlib import Path
from tkinter import ttk, scrolledtext, messagebox, simpledialog
from datetime import datetime, timedelta
from flask import (
    Flask,
    jsonify,
    render_template,
    send_from_directory,
    request,
    Response,
)
import webbrowser


class ChzzkPointsBot:
    def __init__(self, root):
        self.root = root
        self.root.title("치지직 포인트 봇 (제작 : FinN)")
        self.root.geometry("1024x800")
        self.root.resizable(True, True)

        self.setup_data_directory()

        self.channel_id = ""
        self.api_key = ""
        self.client_id = ""
        self.client_secret = ""
        self.access_token = ""
        self.session_key = ""
        self.min_points = 50
        self.max_points = 200
        self.jackpot_points = 500
        self.jackpot_chance = 5
        self.cooldown_minutes = 10
        self.point_multiplier = 1.0
        self.show_point_messages = True
        self.show_betting_messages = True

        # 설정 관련 UI 변수 미리 초기화
        self.show_point_messages_var = tk.BooleanVar(value=self.show_point_messages)
        self.settings_show_point_messages_var = tk.BooleanVar(
            value=self.show_point_messages
        )
        self.show_betting_messages_var = tk.BooleanVar(value=self.show_betting_messages)
        self.settings_show_betting_messages_var = tk.BooleanVar(
            value=self.show_betting_messages
        )

        self.user_points = {}
        self.user_last_reward = {}

        self.shop_items = {}
        self.user_inventory = {}

        # 아이템 사용 이력 초기화
        self.item_use_history = []

        self.betting_event = None
        self.is_betting_active = False
        self.betting_options = []
        self.user_bets = {}
        self.betting_end_time = None
        self.betting_timer = None
        self.betting_results_file = os.path.join(
            self.data_dir, "chzzk_betting_history.json"
        )
        self.betting_history = []

        self.sio = None
        self.is_connected = False
        self.is_running = False

        # Flask 서버 설정
        self.flask_app = Flask(
            __name__,
            template_folder=os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "templates"
            ),
            static_folder=os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "static"
            ),
        )
        self.setup_flask_routes()
        self.flask_thread = None
        self.flask_port = 5000
        self.overlay_url = f"http://localhost:{self.flask_port}/overlay"

        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TButton", font=("Helvetica", 10))
        style.configure("TLabel", font=("Helvetica", 10))
        style.configure("TFrame", background="#f0f0f0")

        self.create_ui()

        self.load_settings()

        self.load_shop_items()
        self.refresh_shop_items()  # 상점 아이템 UI 자동 갱신

        self.load_user_inventory()

        self.load_betting_history()

        self.log(
            "프로그램이 시작되었습니다. 치지직 채널에 연결하려면 '연결' 버튼을 클릭하세요."
        )

        # Flask 서버 시작
        self.start_flask_server()

    def setup_flask_routes(self):
        @self.flask_app.route("/")
        def home():
            self.log("대시보드 홈 페이지 요청 받음")
            return render_template("index.html")

        @self.flask_app.route("/overlay")
        def overlay():
            self.log("오버레이 페이지 요청 받음")
            return render_template("overlay.html")

        @self.flask_app.route("/api/betting/current")
        def current_betting():
            self.log("현재 배팅 정보 API 요청 받음")
            if not self.is_betting_active:
                self.log("현재 진행 중인 배팅 없음")
                return jsonify(
                    {"active": False, "message": "현재 진행 중인 배팅이 없습니다."}
                )

            time_left = 0
            if self.betting_end_time:
                time_left = max(
                    0, (self.betting_end_time - datetime.now()).total_seconds()
                )

            options_data = []
            total_points = sum(bet["amount"] for bet in self.user_bets.values())

            for idx, option in enumerate(self.betting_event["options"]):
                option_bets = sum(
                    bet["amount"]
                    for bet in self.user_bets.values()
                    if bet["option"] == idx
                )
                participants = len(
                    [bet for bet in self.user_bets.values() if bet["option"] == idx]
                )

                # 배당률 계산
                odds = 0
                if option_bets > 0 and total_points > 0:
                    odds = round(total_points / option_bets, 2)

                options_data.append(
                    {
                        "idx": idx + 1,
                        "name": option,
                        "bets": option_bets,
                        "participants": participants,
                        "odds": odds,
                    }
                )

            response_data = {
                "active": True,
                "topic": self.betting_event["topic"],
                "time_left": int(time_left),
                "total_points": total_points,
                "options": options_data,
            }

            self.log(
                f"배팅 정보 API 응답: {response_data['topic']} (옵션 {len(options_data)}개)"
            )
            return jsonify(response_data)

        @self.flask_app.route("/api/betting/history")
        def betting_history():
            self.log("배팅 이력 API 요청 받음")
            recent_history = (
                self.betting_history[-10:] if len(self.betting_history) > 0 else []
            )
            return jsonify(recent_history)

        # 아이템 사용 API 추가
        @self.flask_app.route("/api/item/used")
        def item_used():
            self.log("아이템 사용 정보 API 요청 받음")
            # 현재 활성화된 아이템 사용 정보만 반환
            current_time = datetime.now().timestamp()
            active_items = []

            if hasattr(self, "item_use_history"):
                active_items = [
                    item
                    for item in self.item_use_history
                    if item["expires_at"] > current_time
                ]

            return jsonify(active_items)

        @self.flask_app.route("/static/<path:path>")
        def serve_static(path):
            return send_from_directory("static", path)

    def start_flask_server(self):
        def run_flask():
            try:
                self.log("Flask 서버 시작 중...")
                self.flask_app.run(
                    host="127.0.0.1",
                    port=self.flask_port,
                    debug=False,
                    use_reloader=False,
                )
            except Exception as e:
                self.log(f"Flask 서버 시작 오류: {str(e)}")

        try:
            self.flask_thread = threading.Thread(target=run_flask)
            self.flask_thread.daemon = True
            self.flask_thread.start()
            self.log(f"OBS 오버레이 서버가 시작되었습니다. URL: {self.overlay_url}")

            # 서버 작동 상태 확인 메시지 추가
            self.log("오버레이 서버 이용 방법:")
            self.log(f"1. OBS 브라우저 소스에 URL 추가: {self.overlay_url}")
            self.log("2. 너비: 1280, 높이: 720 권장")
            self.log("3. 배팅이 활성화될 때만 오버레이가 표시됩니다.")

        except Exception as e:
            self.log(f"Flask 서버 스레드 시작 오류: {str(e)}")
            messagebox.showerror(
                "서버 오류", f"오버레이 서버를 시작할 수 없습니다: {str(e)}"
            )

    def setup_data_directory(self):
        self.data_dir = os.path.join(Path.home(), ".chzzk_points_bot")

        try:
            if not os.path.exists(self.data_dir):
                os.makedirs(self.data_dir)

            test_file = os.path.join(self.data_dir, "write_test.tmp")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)

            print(f"데이터 디렉터리 설정 완료: {self.data_dir}")
        except Exception as e:
            print(f"데이터 디렉터리 생성 실패: {str(e)}")
            self.data_dir = tempfile.gettempdir()
            print(f"임시 디렉터리로 대체: {self.data_dir}")

        self.settings_file = os.path.join(self.data_dir, "chzzk_bot_settings.json")
        self.user_data_file = os.path.join(self.data_dir, "chzzk_user_data.json")
        self.shop_items_file = os.path.join(self.data_dir, "chzzk_shop_items.json")
        self.user_inventory_file = os.path.join(
            self.data_dir, "chzzk_user_inventory.json"
        )

        # 템플릿 및 스태틱 디렉토리 생성
        self.templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "templates"
        )
        self.static_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "static"
        )

        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)

        if not os.path.exists(self.static_dir):
            os.makedirs(self.static_dir)

        # 템플릿 파일 생성
        self.create_template_files()

    def create_template_files(self):
        # index.html 파일 생성
        index_html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>치지직 포인트 봇 대시보드</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <div class="dashboard">
        <h1>치지직 포인트 봇 대시보드</h1>
        <div class="info-box">
            <h2>OBS 오버레이 사용 방법</h2>
            <p>1. OBS Studio를 실행하세요.</p>
            <p>2. '소스' 섹션에서 '+' 버튼을 클릭하고 '브라우저'를 선택하세요.</p>
            <p>3. 새 소스 이름을 입력하고 '확인'을 클릭하세요.</p>
            <p>4. URL에 아래 주소를 입력하세요:</p>
            <div class="url-box">
                <input type="text" id="overlay-url" value="http://localhost:5000/overlay" readonly>
                <button onclick="copyUrl()">복사</button>
            </div>
            <p>5. 너비 1280, 높이 720으로 설정하고 '확인'을 클릭하세요.</p>
            <p>6. 오버레이는 배팅이 활성화될 때만 표시됩니다.</p>
        </div>
        
        <div class="actions">
            <button onclick="window.open('/overlay', '_blank')">오버레이 미리보기</button>
            <button onclick="checkBettingStatus()">배팅 상태 확인</button>
        </div>
        
        <div id="status" class="status"></div>
    </div>
    
    <script>
        function copyUrl() {
            const urlInput = document.getElementById('overlay-url');
            urlInput.select();
            document.execCommand('copy');
            alert('오버레이 URL이 클립보드에 복사되었습니다.');
        }
        
        function checkBettingStatus() {
            fetch('/api/betting/current')
                .then(response => response.json())
                .then(data => {
                    const statusDiv = document.getElementById('status');
                    if (data.active) {
                        statusDiv.innerHTML = `
                            <h3>현재 진행 중인 배팅</h3>
                            <p>주제: ${data.topic}</p>
                            <p>남은 시간: ${Math.floor(data.time_left / 60)}분 ${Math.floor(data.time_left % 60)}초</p>
                            <p>총 배팅 포인트: ${data.total_points}</p>
                            <h4>배팅 옵션:</h4>
                            <ul>
                                ${data.options.map(opt => `
                                    <li>${opt.name} - ${opt.bets} 포인트 (${opt.participants}명 참여, 배당률: ${opt.odds}배)</li>
                                `).join('')}
                            </ul>
                        `;
                    } else {
                        statusDiv.innerHTML = `<p>${data.message}</p>`;
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    document.getElementById('status').innerHTML = '<p>데이터를 불러오는 중 오류가 발생했습니다.</p>';
                });
        }
        
        // 페이지 로드 시 자동으로 상태 확인
        window.onload = checkBettingStatus;
    </script>
</body>
</html>
"""

        # overlay.html 파일 생성 - 아이템 효과 부분 추가
        overlay_html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>치지직 포인트 봇 오버레이</title>
    <link rel="stylesheet" href="/static/overlay.css">
    <script>
        // 디버깅용 로그 함수
        function logDebug(message) {
            console.log("[디버그] " + message);
        }
        
        // 페이지 로드 시 실행
        window.onload = function() {
            logDebug("오버레이 페이지 로드됨");
            updateBettingOverlay();
            updateItemUsedOverlay();
            // 1초마다 업데이트
            setInterval(updateBettingOverlay, 1000);
            setInterval(updateItemUsedOverlay, 1000);
        };
    </script>
</head>
<body>
    <div id="betting-overlay" class="hidden">
        <div class="betting-container">
            <div class="betting-header">
                <div class="betting-title">
                    <h2 id="betting-topic">배팅 주제</h2>
                </div>
                <div class="timer">
                    남은 시간: <span id="time-left">00:00</span>
                </div>
            </div>
            
            <div id="options-container" class="options-container">
                <!-- 배팅 옵션들이 여기에 동적으로 추가됩니다 -->
            </div>
            
            <div class="betting-footer">
                <div class="total-points">
                    총 배팅: <span id="total-points">0</span> 포인트
                </div>
                <div class="betting-instructions">
                    채팅에 !번호 포인트로 배팅 (예: !1 500)
                </div>
            </div>
        </div>
    </div>

    <!-- 아이템 사용 알림 오버레이 -->
    <div id="item-used-overlay" class="hidden">
        <div class="item-used-container">
            <div class="item-used-header">
                <div class="item-used-icon">🎮</div>
                <div class="item-used-title">아이템 사용</div>
            </div>
            <div class="item-used-content">
                <div id="item-used-username" class="item-used-username">사용자</div>
                <div id="item-used-message" class="item-used-message">아이템을 사용하였습니다!</div>
            </div>
        </div>
    </div>

    <script>
        // 배팅 오버레이 업데이트 함수
        function updateBettingOverlay() {
            logDebug("배팅 데이터 업데이트 시도 중...");
            fetch('/api/betting/current')
                .then(response => response.json())
                .then(data => {
                    logDebug("배팅 데이터 받음: " + JSON.stringify(data).substring(0, 100) + "...");
                    const overlay = document.getElementById('betting-overlay');
                    
                    if (data.active) {
                        logDebug("활성화된 배팅 감지됨");
                        overlay.classList.remove('hidden');
                        
                        // 주제 업데이트
                        document.getElementById('betting-topic').textContent = data.topic;
                        
                        // 시간 업데이트
                        const minutes = Math.floor(data.time_left / 60);
                        const seconds = Math.floor(data.time_left % 60);
                        document.getElementById('time-left').textContent = 
                            `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
                        
                        // 총 배팅 포인트 업데이트
                        document.getElementById('total-points').textContent = data.total_points.toLocaleString();
                        
                        // 옵션 컨테이너 초기화
                        const optionsContainer = document.getElementById('options-container');
                        optionsContainer.innerHTML = '';
                        
                        // 모든 옵션 추가
                        data.options.forEach(option => {
                            const optionDiv = document.createElement('div');
                            optionDiv.className = 'option';
                            
                            // 옵션 내용
                            const optionHTML = `
                                <div class="option-header">
                                    <div class="option-number">${option.idx}</div>
                                    <div class="option-name">${option.name}</div>
                                </div>
                                <div class="option-stats">
                                    <div class="option-bets">${option.bets.toLocaleString()} 포인트</div>
                                    <div class="option-participants">${option.participants}명 참여</div>
                                    <div class="option-odds">배당률 ${option.odds.toFixed(2)}배</div>
                                </div>
                                <div class="option-bar">
                                    <div class="option-progress" style="width: ${calculateWidth(option.bets, data.total_points)}%"></div>
                                </div>
                            `;
                            
                            optionDiv.innerHTML = optionHTML;
                            optionsContainer.appendChild(optionDiv);
                        });
                    } else {
                        logDebug("활성화된 배팅 없음");
                        overlay.classList.add('hidden');
                    }
                })
                .catch(error => {
                    console.error('배팅 데이터 가져오기 오류:', error);
                    logDebug('배팅 데이터 가져오기 오류: ' + error);
                });
        }
        
        // 아이템 사용 오버레이 업데이트 함수
        function updateItemUsedOverlay() {
            fetch('/api/item/used')
                .then(response => response.json())
                .then(data => {
                    const overlay = document.getElementById('item-used-overlay');
                    
                    if (data.length > 0) {
                        // 가장 최근 아이템 사용 정보 가져오기
                        const latestItem = data[data.length - 1];
                        
                        // 오버레이 정보 업데이트
                        document.getElementById('item-used-username').textContent = latestItem.username;
                        document.getElementById('item-used-message').textContent = 
                            `"${latestItem.item_name}"을(를) 사용하였습니다!`;
                        
                        // 오버레이 표시
                        overlay.classList.remove('hidden');
                        
                        // 5초 후 자동으로 숨김
                        setTimeout(() => {
                            overlay.classList.add('hidden');
                        }, 5000);
                    } else {
                        // 활성화된 아이템 사용 없음
                        overlay.classList.add('hidden');
                    }
                })
                .catch(error => {
                    console.error('아이템 사용 데이터 가져오기 오류:', error);
                });
        }
        
        function calculateWidth(optionBets, totalBets) {
            if (totalBets === 0) return 0;
            return (optionBets / totalBets) * 100;
        }
    </script>
</body>
</html>
"""

        # CSS 파일 생성
        styles_css = """body {
    font-family: 'Noto Sans KR', Arial, sans-serif;
    background-color: #f5f5f5;
    margin: 0;
    padding: 20px;
    color: #333;
}

.dashboard {
    max-width: 800px;
    margin: 0 auto;
    background: white;
    border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    padding: 20px;
}

h1 {
    color: #3498db;
    text-align: center;
    margin-bottom: 30px;
}

h2 {
    color: #2c3e50;
    font-size: 1.5em;
    margin-bottom: 15px;
}

.info-box {
    background-color: #f9f9f9;
    border-left: 4px solid #3498db;
    padding: 15px;
    margin-bottom: 20px;
    border-radius: 0 4px 4px 0;
}

.url-box {
    display: flex;
    margin: 15px 0;
}

.url-box input {
    flex: 1;
    padding: 10px;
    border: 2px solid #ddd;
    border-radius: 4px 0 0 4px;
    font-size: 14px;
}

.url-box button {
    padding: 10px 15px;
    background-color: #3498db;
    color: white;
    border: none;
    border-radius: 0 4px 4px 0;
    cursor: pointer;
    font-weight: bold;
}

.url-box button:hover {
    background-color: #2980b9;
}

.actions {
    display: flex;
    justify-content: center;
    gap: 15px;
    margin: 20px 0;
}

.actions button {
    padding: 12px 20px;
    background-color: #3498db;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
    transition: background-color 0.3s;
}

.actions button:hover {
    background-color: #2980b9;
}

.status {
    margin-top: 20px;
    padding: 15px;
    background-color: #f9f9f9;
    border-radius: 4px;
}

.status h3 {
    margin-top: 0;
    color: #2c3e50;
}

.status ul {
    list-style-type: none;
    padding-left: 0;
}

.status li {
    padding: 8px 0;
    border-bottom: 1px solid #eee;
}

.status li:last-child {
    border-bottom: none;
}
"""

        # 오버레이 CSS 파일 생성
        overlay_css = """body {
    margin: 0;
    padding: 0;
    font-family: 'Noto Sans KR', Arial, sans-serif;
    overflow: hidden;
}

.hidden {
    display: none !important;
}

#betting-overlay {
    width: 100%;
    height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
}

.betting-container {
    width: 90%;
    max-width: 1000px;
    background-color: rgba(0, 0, 0, 0.8);
    border-radius: 10px;
    color: white;
    overflow: hidden;
    box-shadow: 0 0 20px rgba(0, 0, 0, 0.5);
}

.betting-header {
    background-color: rgba(52, 152, 219, 0.9);
    padding: 15px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.betting-title h2 {
    margin: 0;
    font-size: 24px;
    font-weight: 700;
}

.timer {
    font-size: 20px;
    font-weight: 700;
    background-color: rgba(0, 0, 0, 0.3);
    padding: 5px 15px;
    border-radius: 20px;
}

.options-container {
    padding: 20px;
}

.option {
    background-color: rgba(255, 255, 255, 0.1);
    margin-bottom: 15px;
    border-radius: 8px;
    padding: 15px;
    position: relative;
    overflow: hidden;
}

.option-header {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
    position: relative;
    z-index: 1;
}

.option-number {
    background-color: rgba(52, 152, 219, 0.9);
    width: 30px;
    height: 30px;
    border-radius: 50%;
    display: flex;
    justify-content: center;
    align-items: center;
    font-weight: bold;
    margin-right: 15px;
}

.option-name {
    font-size: 18px;
    font-weight: 500;
    flex: 1;
}

.option-stats {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
    position: relative;
    z-index: 1;
}

.option-bets, .option-participants, .option-odds {
    font-size: 14px;
    color: rgba(255, 255, 255, 0.8);
}

.option-odds {
    font-weight: bold;
    color: #f39c12;
}

.option-bar {
    background-color: rgba(255, 255, 255, 0.1);
    height: 8px;
    border-radius: 4px;
    position: relative;
    overflow: hidden;
}

.option-progress {
    position: absolute;
    left: 0;
    top: 0;
    height: 100%;
    background-color: rgba(52, 152, 219, 0.7);
    transition: width 0.5s ease;
}

.betting-footer {
    background-color: rgba(0, 0, 0, 0.3);
    padding: 15px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.total-points {
    font-size: 18px;
    font-weight: 500;
}

.betting-instructions {
    font-size: 16px;
    color: rgba(255, 255, 255, 0.7);
}

/* 아이템 사용 오버레이 */
#item-used-overlay {
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 1000;
    transition: opacity 0.3s ease-in-out;
    animation: slideIn 0.5s ease-out;
}

@keyframes slideIn {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.item-used-container {
    background-color: rgba(0, 0, 0, 0.8);
    border-radius: 10px;
    color: white;
    width: 350px;
    box-shadow: 0 0 20px rgba(0, 0, 0, 0.5);
    overflow: hidden;
    border-left: 4px solid #3cb371; /* 녹색 테두리 */
}

.item-used-header {
    background-color: rgba(60, 179, 113, 0.9); /* 녹색 배경 */
    padding: 10px 15px;
    display: flex;
    align-items: center;
}

.item-used-icon {
    font-size: 24px;
    margin-right: 10px;
}

.item-used-title {
    font-size: 18px;
    font-weight: 700;
}

.item-used-content {
    padding: 15px;
}

.item-used-username {
    font-size: 16px;
    font-weight: 600;
    color: #3cb371; /* 녹색 텍스트 */
    margin-bottom: 5px;
}

.item-used-message {
    font-size: 14px;
    color: rgba(255, 255, 255, 0.9);
}
"""

        # index.html 파일 저장
        index_path = os.path.join(self.templates_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)

        # overlay.html 파일 저장
        overlay_path = os.path.join(self.templates_dir, "overlay.html")
        with open(overlay_path, "w", encoding="utf-8") as f:
            f.write(overlay_html)

        # styles.css 파일 저장
        if not os.path.exists(self.static_dir):
            os.makedirs(self.static_dir)

        styles_path = os.path.join(self.static_dir, "styles.css")
        with open(styles_path, "w", encoding="utf-8") as f:
            f.write(styles_css)

        # overlay.css 파일 저장
        overlay_css_path = os.path.join(self.static_dir, "overlay.css")
        with open(overlay_css_path, "w", encoding="utf-8") as f:
            f.write(overlay_css)

    def create_ui(self):
        main_frame = ttk.Notebook(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        dashboard_tab = ttk.Frame(main_frame)
        settings_tab = ttk.Frame(main_frame)
        logs_tab = ttk.Frame(main_frame)
        users_tab = ttk.Frame(main_frame)
        shop_tab = ttk.Frame(main_frame)
        betting_tab = ttk.Frame(main_frame)
        overlay_tab = ttk.Frame(main_frame)  # 새로운 오버레이 탭 추가

        main_frame.add(dashboard_tab, text="대시보드")
        main_frame.add(settings_tab, text="설정")
        main_frame.add(users_tab, text="유저 포인트")
        main_frame.add(shop_tab, text="상점")
        main_frame.add(betting_tab, text="배팅")
        main_frame.add(overlay_tab, text="OBS 오버레이")  # 오버레이 탭 추가
        main_frame.add(logs_tab, text="로그")

        self.create_dashboard_tab(dashboard_tab)
        self.create_settings_tab(settings_tab)
        self.create_logs_tab(logs_tab)
        self.create_users_tab(users_tab)
        self.create_shop_tab(shop_tab)
        self.create_betting_tab(betting_tab)
        self.create_overlay_tab(overlay_tab)  # 오버레이 탭 UI 생성

        self.status_bar = ttk.Label(
            self.root,
            text=f"데이터 저장 경로: {self.data_dir}",
            relief=tk.SUNKEN,
            anchor=tk.W,
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_overlay_tab(self, parent):
        """OBS 오버레이 설정 탭 생성"""
        overlay_frame = ttk.LabelFrame(parent, text="OBS 오버레이 설정")
        overlay_frame.pack(fill="x", padx=10, pady=10)

        # 오버레이 URL 표시
        ttk.Label(overlay_frame, text="오버레이 URL:").grid(
            row=0, column=0, sticky="w", padx=10, pady=10
        )

        url_frame = ttk.Frame(overlay_frame)
        url_frame.grid(row=0, column=1, sticky="w", padx=10, pady=10)

        url_var = tk.StringVar(value=self.overlay_url)
        url_entry = ttk.Entry(url_frame, textvariable=url_var, width=40)
        url_entry.pack(side="left", padx=5)

        def copy_url():
            self.root.clipboard_clear()
            self.root.clipboard_append(self.overlay_url)
            messagebox.showinfo("URL 복사", "오버레이 URL이 클립보드에 복사되었습니다.")

        ttk.Button(url_frame, text="URL 복사", command=copy_url).pack(side="left")

        # 미리보기 버튼
        def open_preview():
            webbrowser.open(self.overlay_url)

        ttk.Button(overlay_frame, text="오버레이 미리보기", command=open_preview).grid(
            row=1, column=0, columnspan=2, pady=10
        )

        # OBS 연동 가이드
        guide_frame = ttk.LabelFrame(parent, text="OBS Studio 연동 가이드")
        guide_frame.pack(fill="x", padx=10, pady=10)

        guide_text = """
1. OBS Studio를 실행하세요.
2. '소스' 섹션에서 '+' 버튼을 클릭하고 '브라우저'를 선택하세요.
3. 새 소스 이름을 입력하고 '확인'을 클릭하세요.
4. URL에 위 주소를 입력하세요.
5. 너비 1280, 높이 720으로 설정하고 '확인'을 클릭하세요.
6. 필요에 따라 크로마 키 필터를 적용하여 배경을 투명하게 만드세요.
7. 오버레이는 배팅이 활성화될 때만 표시됩니다.
        """

        guide_label = ttk.Label(guide_frame, text=guide_text, justify="left")
        guide_label.pack(padx=10, pady=10, fill="x")

        # 웹 대시보드 버튼
        dash_frame = ttk.LabelFrame(parent, text="웹 대시보드")
        dash_frame.pack(fill="x", padx=10, pady=10)

        def open_dashboard():
            webbrowser.open(f"http://localhost:{self.flask_port}")

        ttk.Button(dash_frame, text="웹 대시보드 열기", command=open_dashboard).pack(
            padx=10, pady=10
        )
        dash_desc = ttk.Label(
            dash_frame,
            text="웹 대시보드에서 배팅 상태를 확인하고 오버레이를 관리할 수 있습니다.",
        )
        dash_desc.pack(padx=10, pady=5)

    def create_dashboard_tab(self, parent):
        status_frame = ttk.LabelFrame(parent, text="봇 상태")
        status_frame.pack(fill="x", padx=10, pady=10)

        self.status_label = ttk.Label(status_frame, text="연결 안됨", foreground="red")
        self.status_label.pack(side="left", padx=10, pady=10)

        self.channel_display = ttk.Label(status_frame, text="")
        self.channel_display.pack(side="left", padx=10, pady=10)

        self.connect_button = ttk.Button(
            status_frame, text="연결", command=self.toggle_connection
        )
        self.connect_button.pack(side="right", padx=10, pady=10)

        stats_frame = ttk.LabelFrame(parent, text="통계")
        stats_frame.pack(fill="x", padx=10, pady=10)

        self.total_users_label = ttk.Label(stats_frame, text="총 유저 수: 0")
        self.total_users_label.pack(anchor="w", padx=10, pady=5)

        self.total_points_label = ttk.Label(stats_frame, text="총 지급 포인트: 0")
        self.total_points_label.pack(anchor="w", padx=10, pady=5)

        self.total_items_label = ttk.Label(stats_frame, text="총 상점 아이템: 0")
        self.total_items_label.pack(anchor="w", padx=10, pady=5)

        self.total_bets_label = ttk.Label(stats_frame, text="총 배팅 이벤트: 0")
        self.total_bets_label.pack(anchor="w", padx=10, pady=5)

        event_frame = ttk.LabelFrame(parent, text="이벤트")
        event_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(event_frame, text="포인트 배율:").pack(side="left", padx=10, pady=10)

        self.multiplier_var = tk.StringVar(value="1.0")
        multiplier_combo = ttk.Combobox(
            event_frame,
            textvariable=self.multiplier_var,
            values=["0.5", "1.0", "1.5", "2.0", "3.0", "5.0", "10.0"],
        )
        multiplier_combo.pack(side="left", padx=10, pady=10)
        multiplier_combo.bind("<<ComboboxSelected>>", self.update_multiplier)

        self.event_button = ttk.Button(
            event_frame, text="이벤트 시작", command=self.toggle_event
        )
        self.event_button.pack(side="right", padx=10, pady=10)

        self.event_status_label = ttk.Label(event_frame, text="이벤트 비활성화")
        self.event_status_label.pack(side="right", padx=10, pady=10)

        message_frame = ttk.LabelFrame(parent, text="메시지 설정")
        message_frame.pack(fill="x", padx=10, pady=10)

        self.show_point_messages_var = tk.BooleanVar(value=self.show_point_messages)
        self.point_message_toggle = ttk.Checkbutton(
            message_frame,
            text="채팅에 포인트 획득 메시지 표시",
            variable=self.show_point_messages_var,
            command=self.toggle_point_messages,
        )
        self.point_message_toggle.pack(anchor="w", padx=10, pady=5)

        self.show_betting_messages_var = tk.BooleanVar(value=self.show_betting_messages)
        self.betting_message_toggle = ttk.Checkbutton(
            message_frame,
            text="채팅에 배팅 관련 메시지 표시",
            variable=self.show_betting_messages_var,
            command=self.toggle_betting_messages,
        )
        self.betting_message_toggle.pack(anchor="w", padx=10, pady=5)

    def toggle_point_messages(self):
        self.show_point_messages = self.show_point_messages_var.get()
        self.settings_show_point_messages_var.set(self.show_point_messages)

        message_status = "활성화" if self.show_point_messages else "비활성화"
        self.log(f"포인트 획득 메시지 표시 {message_status}")

        self.save_settings(silent=True)

        if self.is_connected:
            if self.show_point_messages:
                self.send_chat_message("✅ 포인트 획득 메시지 표시가 활성화되었습니다.")
            else:
                self.send_chat_message(
                    "🔕 포인트 획득 메시지 표시가 비활성화되었습니다."
                )

        messagebox.showinfo(
            "설정 변경", f"포인트 획득 메시지 표시가 {message_status}되었습니다."
        )

    def settings_toggle_point_messages(self):
        self.show_point_messages = self.settings_show_point_messages_var.get()
        self.show_point_messages_var.set(self.show_point_messages)

        message_status = "활성화" if self.show_point_messages else "비활성화"
        self.log(f"포인트 획득 메시지 표시 {message_status} (설정 탭에서 변경)")

        self.save_settings(silent=True)

    def create_settings_tab(self, parent):
        bot_settings_frame = ttk.LabelFrame(parent, text="봇 설정")
        bot_settings_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(bot_settings_frame, text="채널 ID:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.channel_id_entry = ttk.Entry(bot_settings_frame, width=30)
        self.channel_id_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(bot_settings_frame, text="엑세스 토큰:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.api_key_entry = ttk.Entry(bot_settings_frame, width=30, show="*")
        self.api_key_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(bot_settings_frame, text="클라이언트 ID:").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        self.client_id_entry = ttk.Entry(bot_settings_frame, width=30)
        self.client_id_entry.grid(row=2, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(bot_settings_frame, text="클라이언트 secret:").grid(
            row=3, column=0, sticky="w", padx=10, pady=5
        )
        self.client_secret_entry = ttk.Entry(bot_settings_frame, width=30, show="*")
        self.client_secret_entry.grid(row=3, column=1, sticky="w", padx=10, pady=5)

        points_settings_frame = ttk.LabelFrame(parent, text="포인트 설정")
        points_settings_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(points_settings_frame, text="최소 포인트:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.min_points_entry = ttk.Entry(points_settings_frame, width=10)
        self.min_points_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)
        self.min_points_entry.insert(0, str(self.min_points))

        ttk.Label(points_settings_frame, text="최대 포인트:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.max_points_entry = ttk.Entry(points_settings_frame, width=10)
        self.max_points_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        self.max_points_entry.insert(0, str(self.max_points))

        ttk.Label(points_settings_frame, text="잭팟 포인트:").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        self.jackpot_points_entry = ttk.Entry(points_settings_frame, width=10)
        self.jackpot_points_entry.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        self.jackpot_points_entry.insert(0, str(self.jackpot_points))

        ttk.Label(points_settings_frame, text="잭팟 확률 (%):").grid(
            row=3, column=0, sticky="w", padx=10, pady=5
        )
        self.jackpot_chance_entry = ttk.Entry(points_settings_frame, width=10)
        self.jackpot_chance_entry.grid(row=3, column=1, sticky="w", padx=10, pady=5)
        self.jackpot_chance_entry.insert(0, str(self.jackpot_chance))

        ttk.Label(points_settings_frame, text="쿨다운 (분):").grid(
            row=4, column=0, sticky="w", padx=10, pady=5
        )
        self.cooldown_entry = ttk.Entry(points_settings_frame, width=10)
        self.cooldown_entry.grid(row=4, column=1, sticky="w", padx=10, pady=5)
        self.cooldown_entry.insert(0, str(self.cooldown_minutes))

        self.settings_show_point_messages_var = tk.BooleanVar(
            value=self.show_point_messages
        )

        # 오버레이 서버 설정
        server_frame = ttk.LabelFrame(parent, text="오버레이 서버 설정")
        server_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(server_frame, text="서버 포트:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )

        self.server_port_var = tk.StringVar(value=str(self.flask_port))
        port_entry = ttk.Entry(
            server_frame, textvariable=self.server_port_var, width=10
        )
        port_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        def change_port():
            try:
                new_port = int(self.server_port_var.get())
                if 1024 <= new_port <= 65535:
                    if new_port != self.flask_port:
                        if messagebox.askyesno(
                            "서버 재시작",
                            "포트를 변경하려면 서버를 재시작해야 합니다. 계속하시겠습니까?",
                        ):
                            self.flask_port = new_port
                            self.overlay_url = (
                                f"http://localhost:{self.flask_port}/overlay"
                            )
                            self.restart_flask_server()
                            self.save_settings(silent=True)
                            messagebox.showinfo(
                                "설정 변경", f"서버 포트가 {new_port}로 변경되었습니다."
                            )
                    else:
                        messagebox.showinfo("알림", "이미 해당 포트를 사용 중입니다.")
                else:
                    messagebox.showwarning(
                        "오류", "포트는 1024~65535 사이의 값이어야 합니다."
                    )
                    self.server_port_var.set(str(self.flask_port))
            except ValueError:
                messagebox.showwarning("오류", "유효한 포트 번호를 입력하세요.")
                self.server_port_var.set(str(self.flask_port))

        ttk.Button(server_frame, text="포트 변경", command=change_port).grid(
            row=0, column=2, padx=10, pady=5
        )

        path_frame = ttk.LabelFrame(parent, text="데이터 저장 경로")
        path_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(path_frame, text="현재 경로:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        path_label = ttk.Label(path_frame, text=self.data_dir, foreground="blue")
        path_label.grid(row=0, column=1, columnspan=2, sticky="w", padx=10, pady=5)

        ttk.Button(path_frame, text="폴더 열기", command=self.open_data_folder).grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )

        button_frame = ttk.Frame(parent)
        button_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(button_frame, text="설정 저장", command=self.save_settings).pack(
            side="left", padx=10, pady=10
        )
        ttk.Button(button_frame, text="포인트 초기화", command=self.reset_points).pack(
            side="right", padx=10, pady=10
        )

    def restart_flask_server(self):
        """Flask 서버 재시작"""
        try:
            self.log("Flask 서버 재시작 중...")

            # 기존 서버 종료 (실제로는 스레드가 데몬이라 종료되지 않지만 포트 변경 표시용)
            if self.flask_thread and self.flask_thread.is_alive():
                self.log("기존 서버 스레드가 실행 중입니다. (데몬 스레드)")

            # 새 서버 시작
            self.start_flask_server()
            self.log(f"서버가 포트 {self.flask_port}에서 재시작되었습니다.")

            return True
        except Exception as e:
            self.log(f"서버 재시작 오류: {str(e)}")
            messagebox.showerror(
                "서버 오류", f"서버를 재시작하는 중 오류가 발생했습니다: {str(e)}"
            )
            return False

    def open_data_folder(self):
        try:
            if os.path.exists(self.data_dir):
                if sys.platform == "win32":
                    os.startfile(self.data_dir)
                elif sys.platform == "darwin":
                    os.system(f'open "{self.data_dir}"')
                else:
                    os.system(f'xdg-open "{self.data_dir}"')
                self.log(f"데이터 폴더 열기: {self.data_dir}")
            else:
                messagebox.showerror(
                    "오류", f"데이터 폴더를 찾을 수 없습니다: {self.data_dir}"
                )
        except Exception as e:
            self.log(f"폴더 열기 오류: {str(e)}")
            messagebox.showerror("오류", f"폴더를 열 수 없습니다: {str(e)}")

    def create_logs_tab(self, parent):
        self.log_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD, height=20)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text.config(state=tk.DISABLED)

        log_control_frame = ttk.Frame(parent)
        log_control_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(log_control_frame, text="로그 지우기", command=self.clear_logs).pack(
            side="right", padx=10, pady=5
        )

    def create_users_tab(self, parent):
        columns = ("username", "points", "last_reward")
        self.user_tree = ttk.Treeview(parent, columns=columns, show="headings")

        self.user_tree.heading("username", text="유저명")
        self.user_tree.heading("points", text="포인트")
        self.user_tree.heading("last_reward", text="마지막 보상 시간")

        self.user_tree.column("username", width=150)
        self.user_tree.column("points", width=100)
        self.user_tree.column("last_reward", width=200)

        scrollbar = ttk.Scrollbar(
            parent, orient="vertical", command=self.user_tree.yview
        )
        self.user_tree.configure(yscrollcommand=scrollbar.set)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.user_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        user_actions_frame = ttk.LabelFrame(parent, text="유저 관리")
        user_actions_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(user_actions_frame, text="유저 삭제", command=self.delete_user).pack(
            side="left", padx=10, pady=5
        )

        ttk.Button(
            user_actions_frame, text="포인트 수정", command=self.edit_user_points
        ).pack(side="left", padx=10, pady=5)

        ttk.Button(
            user_actions_frame, text="인벤토리 확인", command=self.view_user_inventory
        ).pack(side="left", padx=10, pady=5)

        control_frame = ttk.Frame(parent)
        control_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(control_frame, text="유저 검색:").pack(side="left", padx=5, pady=5)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(control_frame, textvariable=self.search_var, width=20)
        search_entry.pack(side="left", padx=5, pady=5)

        ttk.Button(control_frame, text="검색", command=self.search_user).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(control_frame, text="새로고침", command=self.refresh_users).pack(
            side="right", padx=5, pady=5
        )

        self.user_tree.bind("<Double-1>", lambda event: self.edit_user_points())

    def create_shop_tab(self, parent):
        shop_items_frame = ttk.LabelFrame(parent, text="상점 아이템")
        shop_items_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("item_id", "item_name", "price", "description")
        self.shop_tree = ttk.Treeview(
            shop_items_frame, columns=columns, show="headings"
        )

        self.shop_tree.heading("item_id", text="ID")
        self.shop_tree.heading("item_name", text="아이템 이름")
        self.shop_tree.heading("price", text="가격(포인트)")
        self.shop_tree.heading("description", text="설명")

        self.shop_tree.column("item_id", width=50)
        self.shop_tree.column("item_name", width=150)
        self.shop_tree.column("price", width=100)
        self.shop_tree.column("description", width=300)

        scrollbar = ttk.Scrollbar(
            shop_items_frame, orient="vertical", command=self.shop_tree.yview
        )
        self.shop_tree.configure(yscrollcommand=scrollbar.set)

        self.shop_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        shop_actions_frame = ttk.LabelFrame(parent, text="상점 관리")
        shop_actions_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(
            shop_actions_frame, text="아이템 추가", command=self.add_shop_item
        ).pack(side="left", padx=10, pady=5)

        ttk.Button(
            shop_actions_frame, text="아이템 수정", command=self.edit_shop_item
        ).pack(side="left", padx=10, pady=5)

        ttk.Button(
            shop_actions_frame, text="아이템 삭제", command=self.delete_shop_item
        ).pack(side="left", padx=10, pady=5)

        ttk.Button(
            shop_actions_frame, text="상점 공지", command=self.announce_shop
        ).pack(side="right", padx=10, pady=5)

        ttk.Button(
            shop_actions_frame, text="새로고침", command=self.refresh_shop_items
        ).pack(side="right", padx=10, pady=5)

        self.shop_tree.bind("<Double-1>", lambda event: self.edit_shop_item())

        self.refresh_shop_items()

    def create_betting_tab(self, parent):
        betting_setup_frame = ttk.LabelFrame(parent, text="배팅 이벤트 설정")
        betting_setup_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(betting_setup_frame, text="배팅 주제:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        self.betting_topic_entry = ttk.Entry(betting_setup_frame, width=50)
        self.betting_topic_entry.grid(
            row=0, column=1, columnspan=3, sticky="w", padx=10, pady=5
        )

        options_frame = ttk.Frame(betting_setup_frame)
        options_frame.grid(row=1, column=0, columnspan=4, sticky="w", padx=10, pady=5)

        ttk.Label(options_frame, text="선택지:").pack(side="left", padx=5, pady=5)

        self.option_entries = []
        for i in range(5):
            option_frame = ttk.Frame(options_frame)
            option_frame.pack(side="left", padx=5, pady=5)

            ttk.Label(option_frame, text=f"{i+1}번:").pack(side="left")
            option_entry = ttk.Entry(option_frame, width=15)
            option_entry.pack(side="left")
            self.option_entries.append(option_entry)

        ttk.Label(betting_setup_frame, text="배팅 시간(분):").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        self.betting_time_var = tk.StringVar(value="5")
        betting_time_entry = ttk.Entry(
            betting_setup_frame, textvariable=self.betting_time_var, width=5
        )
        betting_time_entry.grid(row=2, column=1, sticky="w", padx=10, pady=5)

        self.start_betting_button = ttk.Button(
            betting_setup_frame, text="배팅 시작", command=self.start_betting
        )
        self.start_betting_button.grid(row=2, column=2, padx=10, pady=5)

        self.end_betting_button = ttk.Button(
            betting_setup_frame,
            text="배팅 종료",
            command=self.end_betting,
            state=tk.DISABLED,
        )
        self.end_betting_button.grid(row=2, column=3, padx=10, pady=5)

        betting_status_frame = ttk.LabelFrame(parent, text="배팅 현황")
        betting_status_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.current_betting_label = ttk.Label(
            betting_status_frame, text="현재 진행 중인 배팅이 없습니다."
        )
        self.current_betting_label.pack(anchor="w", padx=10, pady=5)

        self.betting_time_left_label = ttk.Label(betting_status_frame, text="")
        self.betting_time_left_label.pack(anchor="w", padx=10, pady=5)

        columns = ("option", "total_bets", "total_points", "participants", "odds")
        self.betting_tree = ttk.Treeview(
            betting_status_frame, columns=columns, show="headings", height=5
        )

        self.betting_tree.heading("option", text="선택지")
        self.betting_tree.heading("total_bets", text="총 배팅 수")
        self.betting_tree.heading("total_points", text="총 배팅 포인트")
        self.betting_tree.heading("participants", text="참여자 수")
        self.betting_tree.heading("odds", text="배당률")

        self.betting_tree.column("option", width=150)
        self.betting_tree.column("total_bets", width=80)
        self.betting_tree.column("total_points", width=120)
        self.betting_tree.column("participants", width=80)
        self.betting_tree.column("odds", width=80)

        scrollbar = ttk.Scrollbar(
            betting_status_frame, orient="vertical", command=self.betting_tree.yview
        )
        self.betting_tree.configure(yscrollcommand=scrollbar.set)

        self.betting_tree.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        scrollbar.pack(side="right", fill="y")

        betting_history_frame = ttk.LabelFrame(parent, text="배팅 이력")
        betting_history_frame.pack(fill="x", padx=10, pady=10)

        columns = ("date", "topic", "options", "total_points", "winner")
        self.history_tree = ttk.Treeview(
            betting_history_frame, columns=columns, show="headings", height=5
        )

        self.history_tree.heading("date", text="날짜")
        self.history_tree.heading("topic", text="주제")
        self.history_tree.heading("options", text="선택지 수")
        self.history_tree.heading("total_points", text="총 배팅 포인트")
        self.history_tree.heading("winner", text="당첨 선택지")

        self.history_tree.column("date", width=150)
        self.history_tree.column("topic", width=200)
        self.history_tree.column("options", width=80)
        self.history_tree.column("total_points", width=120)
        self.history_tree.column("winner", width=100)

        scrollbar = ttk.Scrollbar(
            betting_history_frame, orient="vertical", command=self.history_tree.yview
        )
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        self.history_tree.pack(side="left", fill="both", expand=True, padx=10, pady=5)
        scrollbar.pack(side="right", fill="y")

        result_frame = ttk.Frame(parent)
        result_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(result_frame, text="당첨 선택지:").pack(side="left", padx=5, pady=5)

        self.result_var = tk.StringVar()
        self.result_combo = ttk.Combobox(
            result_frame, textvariable=self.result_var, width=20, state="disabled"
        )
        self.result_combo.pack(side="left", padx=5, pady=5)

        self.apply_result_button = ttk.Button(
            result_frame,
            text="결과 적용",
            command=self.apply_betting_result,
            state=tk.DISABLED,
        )
        self.apply_result_button.pack(side="left", padx=5, pady=5)

        ttk.Button(
            result_frame, text="이력 새로고침", command=self.refresh_betting_history
        ).pack(side="right", padx=5, pady=5)

        self.refresh_betting_history()

    def add_shop_item(self):
        add_window = tk.Toplevel(self.root)
        add_window.title("아이템 추가")
        add_window.geometry("400x250")
        add_window.resizable(False, False)
        add_window.transient(self.root)
        add_window.grab_set()

        item_frame = ttk.Frame(add_window)
        item_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(item_frame, text="아이템 이름:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        item_name_var = tk.StringVar()
        item_name_entry = ttk.Entry(item_frame, textvariable=item_name_var, width=30)
        item_name_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(item_frame, text="가격(포인트):").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        item_price_var = tk.StringVar()
        item_price_entry = ttk.Entry(item_frame, textvariable=item_price_var, width=10)
        item_price_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(item_frame, text="설명:").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        item_desc_text = scrolledtext.ScrolledText(
            item_frame, wrap=tk.WORD, width=30, height=5
        )
        item_desc_text.grid(row=2, column=1, sticky="w", padx=10, pady=5)

        button_frame = ttk.Frame(add_window)
        button_frame.pack(fill="x", padx=10, pady=10)

        def save_item():
            item_name = item_name_var.get().strip()
            item_price = item_price_var.get().strip()
            item_desc = item_desc_text.get("1.0", tk.END).strip()

            if not item_name:
                messagebox.showwarning("경고", "아이템 이름을 입력해주세요.")
                return

            try:
                price = int(item_price)
                if price <= 0:
                    messagebox.showwarning("경고", "가격은 1 이상이어야 합니다.")
                    return
            except ValueError:
                messagebox.showwarning("경고", "유효한 가격을 입력해주세요.")
                return

            item_id = str(int(time.time()))

            self.shop_items[item_id] = {
                "name": item_name,
                "price": price,
                "description": item_desc,
            }

            self.shop_tree.insert(
                "", "end", values=(item_id, item_name, price, item_desc)
            )
            self.save_shop_items()
            self.update_stats()

            self.log(f"상점 아이템 '{item_name}' 추가됨 (가격: {price})")
            messagebox.showinfo(
                "알림", f"아이템 '{item_name}'이(가) 성공적으로 추가되었습니다."
            )
            add_window.destroy()

        ttk.Button(button_frame, text="저장", command=save_item).pack(
            side="left", padx=10
        )
        ttk.Button(button_frame, text="취소", command=add_window.destroy).pack(
            side="right", padx=10
        )

        item_name_entry.focus_set()

    def edit_shop_item(self):
        selected_item = self.shop_tree.selection()
        if not selected_item:
            messagebox.showwarning("경고", "수정할 아이템을 선택해주세요.")
            return

        item_values = self.shop_tree.item(selected_item[0], "values")
        item_id = item_values[0]
        item_name = item_values[1]
        item_price = item_values[2]
        item_desc = item_values[3]

        edit_window = tk.Toplevel(self.root)
        edit_window.title("아이템 수정")
        edit_window.geometry("400x250")
        edit_window.resizable(False, False)
        edit_window.transient(self.root)
        edit_window.grab_set()

        item_frame = ttk.Frame(edit_window)
        item_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(item_frame, text="아이템 이름:").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        item_name_var = tk.StringVar(value=item_name)
        item_name_entry = ttk.Entry(item_frame, textvariable=item_name_var, width=30)
        item_name_entry.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(item_frame, text="가격(포인트):").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        item_price_var = tk.StringVar(value=item_price)
        item_price_entry = ttk.Entry(item_frame, textvariable=item_price_var, width=10)
        item_price_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        ttk.Label(item_frame, text="설명:").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        item_desc_text = scrolledtext.ScrolledText(
            item_frame, wrap=tk.WORD, width=30, height=5
        )
        item_desc_text.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        item_desc_text.insert("1.0", item_desc)

        button_frame = ttk.Frame(edit_window)
        button_frame.pack(fill="x", padx=10, pady=10)

        def update_item():
            new_name = item_name_var.get().strip()
            new_price = item_price_var.get().strip()
            new_desc = item_desc_text.get("1.0", tk.END).strip()

            if not new_name:
                messagebox.showwarning("경고", "아이템 이름을 입력해주세요.")
                return

            try:
                price = int(new_price)
                if price <= 0:
                    messagebox.showwarning("경고", "가격은 1 이상이어야 합니다.")
                    return
            except ValueError:
                messagebox.showwarning("경고", "유효한 가격을 입력해주세요.")
                return

            self.shop_items[item_id] = {
                "name": new_name,
                "price": price,
                "description": new_desc,
            }

            self.shop_tree.item(
                selected_item[0], values=(item_id, new_name, price, new_desc)
            )
            self.save_shop_items()

            self.log(f"상점 아이템 '{new_name}' 수정됨 (가격: {price})")
            messagebox.showinfo(
                "알림", f"아이템 '{new_name}'이(가) 성공적으로 수정되었습니다."
            )
            edit_window.destroy()

        ttk.Button(button_frame, text="저장", command=update_item).pack(
            side="left", padx=10
        )
        ttk.Button(button_frame, text="취소", command=edit_window.destroy).pack(
            side="right", padx=10
        )

        item_name_entry.focus_set()

    def delete_shop_item(self):
        selected_item = self.shop_tree.selection()
        if not selected_item:
            messagebox.showwarning("경고", "삭제할 아이템을 선택해주세요.")
            return

        item_values = self.shop_tree.item(selected_item[0], "values")
        item_id = item_values[0]
        item_name = item_values[1]

        users_with_item = 0
        for user_id, inventory in self.user_inventory.items():
            if item_id in inventory:
                users_with_item += 1

        warning_text = f"정말로 '{item_name}' 아이템을 삭제하시겠습니까?\n"
        if users_with_item > 0:
            warning_text += (
                f"현재 {users_with_item}명의 유저가 이 아이템을 보유하고 있습니다.\n"
            )
            warning_text += (
                "아이템 삭제 시 모든 유저의 인벤토리에서도 이 아이템이 삭제됩니다.\n"
            )
        warning_text += "이 작업은 되돌릴 수 없습니다."

        confirm = messagebox.askyesno("아이템 삭제 확인", warning_text)

        if confirm:
            if item_id in self.shop_items:
                del self.shop_items[item_id]

            users_affected = 0
            for user_id, inventory in self.user_inventory.items():
                if item_id in inventory:
                    del self.user_inventory[user_id][item_id]
                    users_affected += 1

            self.shop_tree.delete(selected_item)
            self.save_shop_items()
            self.save_user_inventory()
            self.update_stats()

            self.log(f"상점 아이템 '{item_name}' 삭제됨")
            if users_affected > 0:
                self.log(
                    f"{users_affected}명의 유저 인벤토리에서 '{item_name}' 아이템이 삭제됨"
                )
                messagebox.showinfo(
                    "알림",
                    f"아이템 '{item_name}'이(가) 성공적으로 삭제되었습니다.\n{users_affected}명의 유저 인벤토리에서도 해당 아이템이 제거되었습니다.",
                )
            else:
                messagebox.showinfo(
                    "알림", f"아이템 '{item_name}'이(가) 성공적으로 삭제되었습니다."
                )

    def refresh_shop_items(self):
        for item in self.shop_tree.get_children():
            self.shop_tree.delete(item)

        for item_id, item_data in self.shop_items.items():
            self.shop_tree.insert(
                "",
                "end",
                values=(
                    item_id,
                    item_data["name"],
                    item_data["price"],
                    item_data["description"],
                ),
            )

        self.update_stats()

    def announce_shop(self):
        if not self.is_connected:
            messagebox.showwarning("경고", "채팅에 연결되어 있지 않습니다.")
            return

        if not self.shop_items:
            messagebox.showwarning("경고", "상점에 등록된 아이템이 없습니다.")
            return

        self.send_chat_message("🛒 포인트 상점 아이템 목록 🛒")
        time.sleep(0.5)

        for item_id, item_data in self.shop_items.items():
            message = f"[{item_data['name']}] - {item_data['price']}포인트 : {item_data['description']}"
            self.send_chat_message(message)
            time.sleep(0.5)

        self.send_chat_message(
            "🛒 '!상점' 명령어로 언제든지 확인 가능합니다. '!아이템이름'으로 구매할 수 있습니다. 🛒"
        )
        self.log("상점 아이템 목록이 채팅에 공지되었습니다.")

    def view_user_inventory(self):
        selected_item = self.user_tree.selection()
        if not selected_item:
            messagebox.showwarning("경고", "인벤토리를 확인할 유저를 선택해주세요.")
            return

        user_values = self.user_tree.item(selected_item[0], "values")
        username = user_values[0]

        inventory_window = tk.Toplevel(self.root)
        inventory_window.title(f"{username}의 인벤토리")
        inventory_window.geometry("500x400")
        inventory_window.transient(self.root)
        inventory_window.grab_set()

        inventory_frame = ttk.Frame(inventory_window)
        inventory_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("item_id", "item_name", "quantity", "purchase_date")
        inventory_tree = ttk.Treeview(inventory_frame, columns=columns, show="headings")

        inventory_tree.heading("item_id", text="ID")
        inventory_tree.heading("item_name", text="아이템 이름")
        inventory_tree.heading("quantity", text="수량")
        inventory_tree.heading("purchase_date", text="구매 일시")

        inventory_tree.column("item_id", width=80, stretch=False)
        inventory_tree.column("item_name", width=150)
        inventory_tree.column("quantity", width=50, stretch=False)
        inventory_tree.column("purchase_date", width=150)

        scrollbar = ttk.Scrollbar(
            inventory_frame, orient="vertical", command=inventory_tree.yview
        )
        inventory_tree.configure(yscrollcommand=scrollbar.set)

        inventory_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        user_inventory = self.user_inventory.get(username, {})

        if not user_inventory:
            inventory_tree.insert(
                "", "end", values=("", "인벤토리가 비어있습니다.", "", "")
            )
        else:
            for item_id, item_data in user_inventory.items():
                item_name = "알 수 없는 아이템"
                if item_id in self.shop_items:
                    item_name = self.shop_items[item_id]["name"]

                inventory_tree.insert(
                    "",
                    "end",
                    values=(
                        item_id,
                        item_name,
                        item_data["quantity"],
                        item_data["purchase_date"],
                    ),
                )

        button_frame = ttk.Frame(inventory_window)
        button_frame.pack(fill="x", padx=10, pady=5)

        def delete_inventory_item():
            selected = inventory_tree.selection()
            if not selected:
                messagebox.showwarning("경고", "삭제할 아이템을 선택해주세요.")
                return

            item_values = inventory_tree.item(selected[0], "values")
            item_id = item_values[0]
            item_name = item_values[1]
            item_quantity = int(item_values[2])

            if item_quantity > 1:
                quantity_window = tk.Toplevel(inventory_window)
                quantity_window.title("삭제할 수량 선택")
                quantity_window.geometry("300x150")
                quantity_window.transient(inventory_window)
                quantity_window.grab_set()

                ttk.Label(
                    quantity_window, text=f"'{item_name}'의 삭제할 수량을 선택하세요:"
                ).pack(pady=10)

                quantity_frame = ttk.Frame(quantity_window)
                quantity_frame.pack(pady=5)

                quantity_var = tk.IntVar(value=1)
                quantity_spinbox = ttk.Spinbox(
                    quantity_frame,
                    from_=1,
                    to=item_quantity,
                    textvariable=quantity_var,
                    width=5,
                )
                quantity_spinbox.pack(side="left", padx=5)

                ttk.Label(quantity_frame, text=f"/ {item_quantity}개").pack(side="left")

                btn_frame = ttk.Frame(quantity_window)
                btn_frame.pack(pady=10)

                def process_delete():
                    delete_quantity = quantity_var.get()
                    process_inventory_delete(item_id, item_name, delete_quantity)
                    quantity_window.destroy()

                ttk.Button(btn_frame, text="삭제", command=process_delete).pack(
                    side="left", padx=5
                )
                ttk.Button(
                    btn_frame, text="취소", command=quantity_window.destroy
                ).pack(side="left", padx=5)

                quantity_window.bind("<Return>", lambda e: process_delete())

                quantity_window.update_idletasks()
                width = quantity_window.winfo_width()
                height = quantity_window.winfo_height()
                x = (quantity_window.winfo_screenwidth() // 2) - (width // 2)
                y = (quantity_window.winfo_screenheight() // 2) - (height // 2)
                quantity_window.geometry("{}x{}+{}+{}".format(width, height, x, y))
            else:
                confirm = messagebox.askyesno(
                    "아이템 삭제 확인",
                    f"정말로 '{item_name}' 아이템을 삭제하시겠습니까?",
                )

                if confirm:
                    process_inventory_delete(item_id, item_name, 1)

        def process_inventory_delete(item_id, item_name, quantity):
            if item_id in self.user_inventory[username]:
                current_quantity = self.user_inventory[username][item_id]["quantity"]

                if current_quantity <= quantity:
                    del self.user_inventory[username][item_id]
                    self.log(
                        f"{username}의 인벤토리에서 '{item_name}' 아이템 완전 삭제"
                    )
                else:
                    self.user_inventory[username][item_id]["quantity"] = (
                        current_quantity - quantity
                    )
                    self.log(
                        f"{username}의 인벤토리에서 '{item_name}' 아이템 {quantity}개 삭제 (남은 수량: {current_quantity - quantity})"
                    )

                self.save_user_inventory()

                for item in inventory_tree.get_children():
                    inventory_tree.delete(item)

                user_inventory = self.user_inventory.get(username, {})

                if not user_inventory:
                    inventory_tree.insert(
                        "", "end", values=("", "인벤토리가 비어있습니다.", "", "")
                    )
                else:
                    for inv_item_id, item_data in user_inventory.items():
                        inv_item_name = "알 수 없는 아이템"
                        if inv_item_id in self.shop_items:
                            inv_item_name = self.shop_items[inv_item_id]["name"]

                        inventory_tree.insert(
                            "",
                            "end",
                            values=(
                                inv_item_id,
                                inv_item_name,
                                item_data["quantity"],
                                item_data["purchase_date"],
                            ),
                        )

                messagebox.showinfo(
                    "알림", f"'{item_name}' 아이템이 성공적으로 삭제되었습니다."
                )

        ttk.Button(
            button_frame, text="아이템 삭제", command=delete_inventory_item
        ).pack(side="left", padx=10, pady=5)

        ttk.Button(button_frame, text="닫기", command=inventory_window.destroy).pack(
            side="right", padx=10, pady=5
        )

        inventory_tree.bind("<Double-1>", lambda event: delete_inventory_item())

    def delete_user(self):
        selected_item = self.user_tree.selection()
        if not selected_item:
            messagebox.showwarning("경고", "삭제할 유저를 선택해주세요.")
            return

        user_values = self.user_tree.item(selected_item[0], "values")
        username = user_values[0]

        confirm = messagebox.askyesno(
            "유저 삭제 확인",
            f"정말로 '{username}' 유저를 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
        )

        if confirm:
            if username in self.user_points:
                del self.user_points[username]

            if username in self.user_last_reward:
                del self.user_last_reward[username]

            if username in self.user_inventory:
                del self.user_inventory[username]

            self.user_tree.delete(selected_item)
            self.update_stats()
            self.log(f"'{username}' 유저가 삭제되었습니다.")

            self.save_user_data()
            self.save_user_inventory()

            messagebox.showinfo(
                "알림", f"'{username}' 유저가 성공적으로 삭제되었습니다."
            )

    def edit_user_points(self):
        selected_item = self.user_tree.selection()
        if not selected_item:
            messagebox.showwarning("경고", "포인트를 수정할 유저를 선택해주세요.")
            return

        user_values = self.user_tree.item(selected_item[0], "values")
        username = user_values[0]
        current_points = int(user_values[1])

        edit_window = tk.Toplevel(self.root)
        edit_window.title("포인트 수정")
        edit_window.geometry("300x150")
        edit_window.resizable(False, False)
        edit_window.transient(self.root)
        edit_window.grab_set()

        ttk.Label(edit_window, text=f"유저: {username}").pack(pady=(10, 5))

        points_frame = ttk.Frame(edit_window)
        points_frame.pack(pady=5)

        ttk.Label(points_frame, text="포인트:").pack(side="left", padx=5)
        points_var = tk.StringVar(value=str(current_points))
        points_entry = ttk.Entry(points_frame, textvariable=points_var, width=10)
        points_entry.pack(side="left", padx=5)
        points_entry.select_range(0, tk.END)
        points_entry.focus_set()

        button_frame = ttk.Frame(edit_window)
        button_frame.pack(pady=10)

        def apply_edit():
            try:
                new_points = int(points_var.get())
                if new_points < 0:
                    messagebox.showwarning("경고", "포인트는 0 이상이어야 합니다.")
                    return

                self.user_points[username] = new_points

                self.user_tree.item(
                    selected_item, values=(username, new_points, user_values[2])
                )
                self.update_stats()
                self.log(
                    f"'{username}' 유저의 포인트가 {current_points}에서 {new_points}로 수정되었습니다."
                )

                self.save_user_data()

                edit_window.destroy()
                messagebox.showinfo(
                    "알림", f"'{username}' 유저의 포인트가 성공적으로 수정되었습니다."
                )
            except ValueError:
                messagebox.showwarning("경고", "유효한 숫자를 입력해주세요.")

        ttk.Button(button_frame, text="적용", command=apply_edit).pack(
            side="left", padx=5
        )
        ttk.Button(button_frame, text="취소", command=edit_window.destroy).pack(
            side="left", padx=5
        )

        edit_window.bind("<Return>", lambda event: apply_edit())

        edit_window.update_idletasks()
        width = edit_window.winfo_width()
        height = edit_window.winfo_height()
        x = (edit_window.winfo_screenwidth() // 2) - (width // 2)
        y = (edit_window.winfo_screenheight() // 2) - (height // 2)
        edit_window.geometry("{}x{}+{}+{}".format(width, height, x, y))

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, log_message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_logs(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def toggle_connection(self):
        if not self.is_connected:
            self.connect()
        else:
            self.disconnect()

    def update_multiplier(self, event=None):
        """포인트 배율 업데이트"""
        self.point_multiplier = float(self.multiplier_var.get())

        if self.point_multiplier != 1.0:
            self.event_status_label.config(
                text=f"이벤트 활성화 ({self.point_multiplier}배)"
            )
            self.event_button.config(text="이벤트 종료")
        else:
            self.event_status_label.config(text="이벤트 비활성화")
            self.event_button.config(text="이벤트 시작")

    def create_session(self):
        headers = {
            "Client-Id": self.client_id,
            "Client-Secret": self.client_secret,
            "Content-Type": "application/json",
        }
        response = requests.get(
            "https://openapi.chzzk.naver.com/open/v1/sessions/auth/client",
            headers=headers,
        )
        if response.status_code == 200:
            _tmp = json.loads(response.text)
            _tmp = _tmp["content"]["url"]
            print("\n\n\n")
            print(_tmp)
            print("\n\n\n")

            return _tmp
        else:
            return "error"

    def handle_system_message(self, data):
        print("\n\n\n")
        messagebox.showinfo("알림", data)
        data = json.loads(data)
        print(data)
        if data["type"] == "connected":
            self.session_key = data["data"]["sessionKey"]

            headers = {
                "Authorization": "Bearer " + str(self.access_token),
                "Content-Type": "application/json",
            }
            response = requests.post(
                "https://openapi.chzzk.naver.com/open/v1/sessions/events/subscribe/chat",
                params={"sessionKey": self.session_key},
                headers=headers,
            )
        return

    def connect(self):
        channel_id = self.channel_id_entry.get().strip()

        if not channel_id:
            messagebox.showerror("오류", "채널 ID를 입력해주세요.")
            return

        if self.is_connected:
            messagebox.showinfo("알림", "이미 연결되어 있습니다.")
            return

        self.channel_id = channel_id

        self.save_settings(silent=True)

        self.log(f"채널 {channel_id}에 연결 시도 중...")

        try:
            self.sio = socketio.Client()

            self.sio.on("connect", self.on_connect)
            self.sio.on("disconnect", self.on_disconnect)
            self.sio.on("CHAT", self.on_chat_message)
            self.sio.on("SYSTEM", self.handle_system_message)
            self.sio.on("connect_error", self.on_connect_error)

            ws_url = f"https://api.chzzk.com/chat/v1/channel/{channel_id}"

            self.log(f"연결 URL: {ws_url}")

            self.sio_thread = threading.Thread(
                target=self.connect_socketio, args=(ws_url,)
            )
            self.sio_thread.daemon = True
            self.sio_thread.start()

        except Exception as e:
            self.log(f"연결 오류: {str(e)}")
            self.log(f"오류 상세: {type(e).__name__}")
            messagebox.showerror("연결 오류", f"채팅 연결에 실패했습니다:\n{str(e)}")
            self.is_connected = False
            self.status_label.config(text="연결 실패", foreground="red")
            self.connect_button.config(text="연결")

    def connect_socketio(self, url):
        try:
            self.log("SocketIO 연결 시작...")
            url = self.create_session()
            self.sio.connect(url)
            self.sio.wait()
        except Exception as e:
            self.log(f"SocketIO 연결 오류: {str(e)}")
            self.root.after(
                0, lambda: self.status_label.config(text="연결 오류", foreground="red")
            )
            self.root.after(0, lambda: self.connect_button.config(text="연결"))
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "연결 오류", f"SocketIO 연결 중 오류 발생"
                ),
            )

    def on_connect(self):
        self.log("SocketIO 서버에 연결되었습니다.")
        self.is_connected = True
        self.is_running = True

        self.root.after(
            0, lambda: self.status_label.config(text="연결됨", foreground="green")
        )
        self.root.after(0, lambda: self.connect_button.config(text="연결 해제"))
        self.root.after(
            0, lambda: self.channel_display.config(text=f"채널: {self.channel_id}")
        )

    def on_disconnect(self):
        self.log("SocketIO 서버와 연결이 종료되었습니다.")
        self.is_connected = False
        self.is_running = False

        self.root.after(
            0, lambda: self.status_label.config(text="연결 안됨", foreground="red")
        )
        self.root.after(0, lambda: self.connect_button.config(text="연결"))
        self.root.after(0, lambda: self.channel_display.config(text=""))

    def on_connect_error(self, error):
        self.log(f"SocketIO 연결 오류: {error}")

    def on_chat_message(self, data):
        try:
            data = json.loads(data)
            user_id = data["profile"]["nickname"]
            username = data["profile"]["nickname"]
            content = data["content"]

            self.log(f"[채팅] {username}: {content}")

            # 명령어 처리 순서 변경: 먼저 정확한 명령어 체크, 그 다음 배팅 명령어
            content_stripped = content.strip()

            # 정확한 명령어 먼저 확인
            if content_stripped == "!포인트":
                self.handle_points_command(user_id, username)
            elif content_stripped == "!상점":
                self.handle_shop_command(user_id, username)
            elif content_stripped == "!아이템":
                self.handle_inventory_command(user_id, username)
            elif content_stripped == "!배팅":
                self.handle_betting_info_command(user_id, username)
            # 아이템 사용 명령어 처리 추가
            elif content_stripped.startswith("!사용 "):
                self.handle_item_use(user_id, username, content_stripped[4:].strip())
            # 배팅 명령어 처리 (패턴: !숫자 포인트)
            elif (
                self.is_betting_active
                and content_stripped.startswith("!")
                and len(content_stripped) > 1
            ):
                # 배팅 명령어 패턴 확인 (!숫자 ...)
                parts = content_stripped[1:].split()
                if parts and parts[0].isdigit():
                    self.handle_betting_command(user_id, username, content_stripped)
                else:
                    # 패턴이 맞지 않으면 아이템 구매로 처리
                    self.handle_item_purchase(
                        user_id, username, content_stripped[1:].strip()
                    )
            # 아이템 구매 처리
            elif content_stripped.startswith("!"):
                self.handle_item_purchase(
                    user_id, username, content_stripped[1:].strip()
                )
            # 일반 채팅 메시지 처리
            else:
                self.handle_chat_message(user_id, username)
        except Exception as e:
            self.log(f"메시지 처리 오류: {str(e)}")

    # 아이템 사용 처리 함수 추가
    def handle_item_use(self, user_id, username, item_name):
        """아이템 사용 명령어 처리"""
        if user_id not in self.user_inventory:
            self.send_chat_message(f"@{username} 님은 보유한 아이템이 없습니다.")
            return

        # 입력된 아이템 이름과 일치하는 아이템 찾기
        item_id = None
        item_data = None
        user_inventory = self.user_inventory.get(user_id, {})

        # 정확한 이름 일치 먼저 시도
        for inv_item_id, inv_item_data in user_inventory.items():
            if inv_item_id in self.shop_items:
                shop_item_name = self.shop_items[inv_item_id]["name"]
                if shop_item_name.lower() == item_name.lower():
                    item_id = inv_item_id
                    item_data = self.shop_items[inv_item_id]
                    break

        # 부분 일치로 확장
        if not item_id:
            for inv_item_id, inv_item_data in user_inventory.items():
                if inv_item_id in self.shop_items:
                    shop_item_name = self.shop_items[inv_item_id]["name"]
                    if item_name.lower() in shop_item_name.lower():
                        item_id = inv_item_id
                        item_data = self.shop_items[inv_item_id]
                        break

        if not item_id:
            self.send_chat_message(
                f"@{username} 님이 '{item_name}' 아이템을 보유하고 있지 않습니다."
            )
            return

        # 아이템 사용 처리
        if user_inventory[item_id]["quantity"] <= 0:
            self.send_chat_message(
                f"@{username} 님이 '{item_data['name']}' 아이템을 모두 사용하셨습니다."
            )
            return

        # 아이템 수량 감소
        user_inventory[item_id]["quantity"] -= 1

        # 아이템 수량이 0이 되면 인벤토리에서 제거
        if user_inventory[item_id]["quantity"] <= 0:
            del user_inventory[item_id]

        # 채팅에 사용 메시지 전송
        self.send_chat_message(
            f"🎮 @{username} 님이 '{item_data['name']}' 아이템을 사용하였습니다!"
        )

        # 오버레이에 아이템 사용 알림 표시
        self.show_item_used_overlay(username, item_data["name"])

        # 로그에 기록
        self.log(f"{username}님이 '{item_data['name']}' 아이템을 사용했습니다.")

        # 데이터 저장
        self.save_user_inventory()

    # 오버레이에 아이템 사용 알림 표시 함수 추가
    def show_item_used_overlay(self, username, item_name):
        """오버레이에 아이템 사용 알림 표시"""
        # 현재 시간을 기준으로 아이템 사용 ID 생성
        use_id = str(int(time.time()))

        # 아이템 사용 정보 저장
        item_use_info = {
            "id": use_id,
            "username": username,
            "item_name": item_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": (
                datetime.now() + timedelta(seconds=5)
            ).timestamp(),  # 5초 후 만료
        }

        # 아이템 사용 정보를 flask 앱에서 접근할 수 있도록 저장
        if not hasattr(self, "item_use_history"):
            self.item_use_history = []

        self.item_use_history.append(item_use_info)

        # 오래된 아이템 사용 정보 제거
        current_time = datetime.now().timestamp()
        self.item_use_history = [
            item for item in self.item_use_history if item["expires_at"] > current_time
        ]

    def disconnect(self):
        try:
            self.log("연결 해제 중...")

            self.channel_display.config(text="")

            self.is_running = False

            if self.sio and hasattr(self.sio, "connected") and self.sio.connected:
                try:
                    self.sio.disconnect()
                    self.log("Socket.IO 연결이 정상적으로 종료되었습니다.")
                except Exception as e:
                    self.log(f"Socket.IO 연결 종료 중 오류 발생: {str(e)}")

            self.is_connected = False
            self.status_label.config(text="연결 안됨", foreground="red")
            self.connect_button.config(text="연결")
            self.log("채팅 연결이 완전히 종료되었습니다.")

            messagebox.showinfo("연결 해제", "채팅 연결이 해제되었습니다.")
        except Exception as e:
            self.log(f"연결 해제 중 오류 발생: {str(e)}")
            messagebox.showerror("오류", f"연결 해제 중 오류가 발생했습니다: {str(e)}")

    def handle_points_command(self, user_id, username):
        if user_id in self.user_points:
            points = self.user_points[user_id]
            self.send_chat_message(f"@{username} 님의 현재 포인트: {points}점")
            self.log(f"{username}님의 포인트 조회: {points}점")
        else:
            self.send_chat_message(f"@{username} 님은 아직 포인트가 없습니다.")
            self.log(f"{username}님의 포인트 조회: 0점")

    def handle_shop_command(self, user_id, username):
        if not self.shop_items:
            self.send_chat_message("🛒 현재 상점에 아이템이 없습니다.")
            return

        self.send_chat_message("🛒 포인트 상점 아이템 목록 🛒")
        time.sleep(0.5)

        for item_id, item_data in self.shop_items.items():
            message = f"[{item_data['name']}] - {item_data['price']}포인트 : {item_data['description']}"
            self.send_chat_message(message)
            time.sleep(0.5)

        self.send_chat_message("🛒 '!아이템이름'으로 아이템을 구매할 수 있습니다. 🛒")
        self.log(f"{username}님이 상점 목록을 조회했습니다.")

    def handle_inventory_command(self, user_id, username):
        user_inventory = self.user_inventory.get(user_id, {})

        if not user_inventory:
            self.send_chat_message(f"@{username} 님은 보유한 아이템이 없습니다.")
            return

        self.send_chat_message(f"🎒 @{username} 님의 보유 아이템 목록 🎒")
        time.sleep(0.5)

        for item_id, item_data in user_inventory.items():
            item_name = "알 수 없는 아이템"
            if item_id in self.shop_items:
                item_name = self.shop_items[item_id]["name"]

            message = f"[{item_name}] - {item_data['quantity']}개"
            self.send_chat_message(message)
            time.sleep(0.3)

        self.log(f"{username}님이 인벤토리를 조회했습니다.")

    # 배팅 관련 명령어 및 함수 추가
    def handle_betting_info_command(self, user_id, username):
        """!배팅 명령어로 현재 배팅 정보 조회"""
        if not self.is_betting_active:
            self.send_chat_message("🎲 현재 진행 중인 배팅이 없습니다.")
            return

        # 배팅 메시지 설정이 꺼져 있더라도 !배팅 명령어에 대한 응답은 항상 보여줌
        # 현재 배팅 정보 표시
        self.send_chat_message(f"🎲 배팅 주제: {self.betting_event['topic']} 🎲")
        time.sleep(0.3)

        # 남은 시간 계산
        time_left = self.betting_end_time - datetime.now()
        minutes_left = int(time_left.total_seconds() / 60)
        seconds_left = int(time_left.total_seconds() % 60)

        # 옵션 및 배팅 방법 안내
        self.send_chat_message("📊 현재 배팅 옵션:")
        for idx, option in enumerate(self.betting_event["options"]):
            # 현재 배팅 금액과 배당률 계산
            total_bets = sum(
                bet["amount"] for bet in self.user_bets.values() if bet["option"] == idx
            )
            total_participants = len(
                [bet for bet in self.user_bets.values() if bet["option"] == idx]
            )

            message = (
                f"[{idx+1}] {option} - {total_bets}포인트 ({total_participants}명 참여)"
            )
            self.send_chat_message(message)
            time.sleep(0.3)

        self.send_chat_message(
            "💰 배팅 방법: !숫자 포인트 (예: !1 포인트 - 1번에 포인트/올인 배팅)"
        )

        self.log(f"{username}님이 배팅 정보를 조회했습니다.")

    def handle_betting_command(self, user_id, username, content):
        """배팅 명령어 처리 (!숫자 포인트)"""
        if not self.is_betting_active:
            self.send_chat_message(f"@{username} 님, 현재 진행 중인 배팅이 없습니다.")
            return

        # 이미 배팅한 유저인지 확인
        if user_id in self.user_bets:
            self.send_chat_message(
                f"@{username} 님, 이미 배팅에 참여하셨습니다. 중복 배팅은 불가능합니다."
            )
            return

        # 명령어 파싱
        try:
            parts = content[1:].strip().split()
            if len(parts) < 2:
                self.send_chat_message(
                    f"@{username} 님, 배팅 형식이 잘못되었습니다. !숫자 포인트 형식으로 배팅해주세요. (예: !1 500)"
                )
                return

            option_num = int(parts[0])

            # 옵션 번호 확인
            if option_num < 1 or option_num > len(self.betting_event["options"]):
                self.send_chat_message(
                    f"@{username} 님, 유효하지 않은 선택지입니다. 1~{len(self.betting_event['options'])} 사이의 번호를 입력해주세요."
                )
                return

            # 포인트 확인
            if parts[1].lower() == "올인":
                # 올인 처리
                if user_id not in self.user_points or self.user_points[user_id] <= 0:
                    self.send_chat_message(f"@{username} 님, 배팅할 포인트가 없습니다.")
                    return

                bet_amount = self.user_points[user_id]
            else:
                try:
                    bet_amount = int(parts[1])
                except ValueError:
                    self.send_chat_message(
                        f"@{username} 님, 유효한 포인트 수량을 입력해주세요."
                    )
                    return

            # 최소 배팅 금액 확인
            if bet_amount < 10:
                self.send_chat_message(
                    f"@{username} 님, 최소 배팅 금액은 10포인트입니다."
                )
                return

            # 유저 포인트 확인
            if user_id not in self.user_points:
                self.user_points[user_id] = 0

            if bet_amount > self.user_points[user_id]:
                self.send_chat_message(
                    f"@{username} 님, 보유 포인트가 부족합니다. (보유: {self.user_points[user_id]}점, 필요: {bet_amount}점)"
                )
                return

            # 배팅 처리
            self.user_points[user_id] -= bet_amount
            self.user_bets[user_id] = {
                "option": option_num - 1,  # 0-based 인덱스로 저장
                "amount": bet_amount,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            option_name = self.betting_event["options"][option_num - 1]

            # 배팅 메시지 설정에 따라 메시지 표시
            if self.show_betting_messages:
                self.send_chat_message(
                    f"💰 @{username} 님이 '{option_name}'에 {bet_amount}포인트를 배팅했습니다! (남은 포인트: {self.user_points[user_id]}점)"
                )

            # 배팅 현황 업데이트
            self.update_betting_status()
            self.save_user_data()
            self.log(f"{username}님이 '{option_name}'에 {bet_amount}포인트 배팅")

        except Exception as e:
            self.log(f"배팅 처리 오류: {str(e)}")
            self.send_chat_message(
                f"@{username} 님, 배팅 처리 중 오류가 발생했습니다. 다시 시도해주세요."
            )

    def handle_item_purchase(self, user_id, username, item_name):
        if user_id not in self.user_points:
            self.send_chat_message(
                f"@{username} 님은 포인트가 없습니다. 채팅을 통해 포인트를 모아보세요!"
            )
            return

        user_points = self.user_points[user_id]

        item_id = None
        item_data = None

        for id, data in self.shop_items.items():
            if data["name"].lower() == item_name.lower():
                item_id = id
                item_data = data
                break

        if not item_data:
            for id, data in self.shop_items.items():
                if item_name.lower() in data["name"].lower():
                    item_id = id
                    item_data = data
                    break

        if not item_data:
            # 아이템을 찾지 못한 경우
            self.send_chat_message(
                f"@{username} 님, 상점에서 '{item_name}' 아이템을 찾을 수 없습니다."
            )
            return

        # 포인트 확인
        if user_points < item_data["price"]:
            self.send_chat_message(
                f"@{username} 님, '{item_data['name']}' 아이템을 구매하기 위한 포인트가 부족합니다. (보유: {user_points}점, 필요: {item_data['price']}점)"
            )
            return

        # 아이템 구매 처리
        self.user_points[user_id] = user_points - item_data["price"]

        if user_id not in self.user_inventory:
            self.user_inventory[user_id] = {}

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if item_id in self.user_inventory[user_id]:
            self.user_inventory[user_id][item_id]["quantity"] += 1
        else:
            self.user_inventory[user_id][item_id] = {
                "quantity": 1,
                "purchase_date": current_time,
            }

        self.send_chat_message(
            f"🎉 @{username} 님이 '{item_data['name']}'을(를) 구매했습니다! (남은 포인트: {self.user_points[user_id]}점)"
        )

        self.log(
            f"{username}님이 '{item_data['name']}' 아이템을 {item_data['price']}포인트에 구매했습니다."
        )
        self.save_user_data()
        self.save_user_inventory()
        self.refresh_users()

    def handle_chat_message(self, user_id, username):
        now = datetime.now()

        if user_id not in self.user_points:
            self.user_points[user_id] = 0
            self.user_last_reward[user_id] = now - timedelta(
                minutes=self.cooldown_minutes + 1
            )
            self.refresh_users()

        last_reward = self.user_last_reward.get(user_id, datetime.min)
        time_diff = now - last_reward

        if time_diff.total_seconds() >= self.cooldown_minutes * 60:
            if random.randint(1, 100) <= self.jackpot_chance:
                points = int(self.jackpot_points * self.point_multiplier)
                # 포인트 메시지 표시 설정 적용
                if self.show_point_messages:
                    self.send_chat_message(
                        f"🎉 {username}님 축하합니다! 잭팟 {points}포인트를 획득하셨습니다!"
                    )
            else:
                points = int(
                    random.randint(self.min_points, self.max_points)
                    * self.point_multiplier
                )
                # 포인트 메시지 표시 설정 적용
                if self.show_point_messages:
                    self.send_chat_message(
                        f"✨ {username}님이 {points}포인트를 획득했습니다!"
                    )

            self.user_points[user_id] = self.user_points.get(user_id, 0) + points
            self.user_last_reward[user_id] = now

            # 로그에는 항상 기록
            self.log(
                f"{username}님에게 {points}포인트 지급 (총 {self.user_points[user_id]}점)"
            )
            self.refresh_users()
            self.update_stats()

    def send_chat_message(self, message):
        if not self.is_connected:
            self.log("메시지 전송 실패: 연결되어 있지 않음")
            return

        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }

            payload = {"channelId": self.channel_id, "message": message}

            response = requests.post(
                "https://openapi.chzzk.naver.com/open/v1/chats/send",
                headers=headers,
                json=payload,
            )

            if response.status_code == 200:
                self.log(f"[봇] {message}")
            else:
                self.log(
                    f"메시지 전송 실패: 상태 코드 {response.status_code}, 응답: {response.text}"
                )

        except Exception as e:
            self.log(f"메시지 전송 오류: {str(e)}")

    def toggle_event(self):
        current_multiplier = float(self.multiplier_var.get())

        if current_multiplier != 1.0:
            self.point_multiplier = current_multiplier
            self.event_status_label.config(
                text=f"이벤트 활성화 ({current_multiplier}배)"
            )
            self.event_button.config(text="이벤트 종료")
            self.log(f"포인트 이벤트 시작: {current_multiplier}배 배율 적용")
            self.send_chat_message(
                f"🎮 포인트 이벤트 시작! 모든 포인트가 {current_multiplier}배로 지급됩니다! 🎮"
            )
        else:
            self.point_multiplier = 1.0
            self.event_status_label.config(text="이벤트 비활성화")
            self.event_button.config(text="이벤트 시작")
            self.log("포인트 이벤트 종료")
            self.send_chat_message("🎮 포인트 이벤트가 종료되었습니다. 🎮")

    def refresh_users(self):
        for item in self.user_tree.get_children():
            self.user_tree.delete(item)

        for user_id, points in self.user_points.items():
            username = user_id
            last_reward = self.user_last_reward.get(user_id, datetime.min)
            last_reward_str = last_reward.strftime("%Y-%m-%d %H:%M:%S")

            self.user_tree.insert("", "end", values=(username, points, last_reward_str))

    def search_user(self):
        search_term = self.search_var.get().lower()

        for item in self.user_tree.get_children():
            self.user_tree.delete(item)

        for user_id, points in self.user_points.items():
            if search_term in user_id.lower():
                username = user_id
                last_reward = self.user_last_reward.get(user_id, datetime.min)
                last_reward_str = last_reward.strftime("%Y-%m-%d %H:%M:%S")

                self.user_tree.insert(
                    "", "end", values=(username, points, last_reward_str)
                )

    def update_stats(self):
        total_users = len(self.user_points)
        total_points = sum(self.user_points.values())
        total_items = len(self.shop_items)
        total_bets = len(self.betting_history)

        self.total_users_label.config(text=f"총 유저 수: {total_users}")
        self.total_points_label.config(text=f"총 지급 포인트: {total_points}")
        self.total_items_label.config(text=f"총 상점 아이템: {total_items}")
        self.total_bets_label.config(text=f"총 배팅 이벤트: {total_bets}")

    def save_settings(self, silent=False):
        try:
            if not silent:
                self.log("설정 저장 시도 중...")

            try:
                # 입력값 가져오기
                self.channel_id = self.channel_id_entry.get().strip()
                self.access_token = self.api_key_entry.get().strip()
                self.client_id = self.client_id_entry.get().strip()
                self.client_secret = self.client_secret_entry.get().strip()

                # 디버깅용 로그 추가
                self.log(f"저장할 클라이언트 ID: {self.client_id}")
                self.log(f"저장할 클라이언트 시크릿: [보안 정보 숨김]")

                try:
                    self.min_points = int(self.min_points_entry.get())
                except ValueError:
                    if not silent:
                        self.log("최소 포인트 값이 올바르지 않습니다. 기본값 50 사용")
                    self.min_points = 50
                    self.min_points_entry.delete(0, tk.END)
                    self.min_points_entry.insert(0, "50")

                try:
                    self.max_points = int(self.max_points_entry.get())
                except ValueError:
                    if not silent:
                        self.log("최대 포인트 값이 올바르지 않습니다. 기본값 200 사용")
                    self.max_points = 200
                    self.max_points_entry.delete(0, tk.END)
                    self.max_points_entry.insert(0, "200")

                try:
                    self.jackpot_points = int(self.jackpot_points_entry.get())
                except ValueError:
                    if not silent:
                        self.log("잭팟 포인트 값이 올바르지 않습니다. 기본값 500 사용")
                    self.jackpot_points = 500
                    self.jackpot_points_entry.delete(0, tk.END)
                    self.jackpot_points_entry.insert(0, "500")

                try:
                    self.jackpot_chance = int(self.jackpot_chance_entry.get())
                except ValueError:
                    if not silent:
                        self.log("잭팟 확률 값이 올바르지 않습니다. 기본값 5 사용")
                    self.jackpot_chance = 5
                    self.jackpot_chance_entry.delete(0, tk.END)
                    self.jackpot_chance_entry.insert(0, "5")

                try:
                    self.cooldown_minutes = int(self.cooldown_entry.get())
                except ValueError:
                    if not silent:
                        self.log("쿨다운 시간 값이 올바르지 않습니다. 기본값 10 사용")
                    self.cooldown_minutes = 10
                    self.cooldown_entry.delete(0, tk.END)
                    self.cooldown_entry.insert(0, "10")

                # 설정 탭의 메시지 표시 체크박스 값 가져오기 (안전 검사 추가)
                if hasattr(self, "settings_show_point_messages_var"):
                    self.show_point_messages = (
                        self.settings_show_point_messages_var.get()
                    )

                if hasattr(self, "settings_show_betting_messages_var"):
                    self.show_betting_messages = (
                        self.settings_show_betting_messages_var.get()
                    )

                # 대시보드의 체크박스 동기화 (안전 검사 추가)
                if hasattr(self, "show_point_messages_var"):
                    self.show_point_messages_var.set(self.show_point_messages)

                if hasattr(self, "show_betting_messages_var"):
                    self.show_betting_messages_var.set(self.show_betting_messages)

                # 서버 포트 저장
                try:
                    self.flask_port = int(self.server_port_var.get())
                except ValueError:
                    if not silent:
                        self.log("서버 포트 값이 올바르지 않습니다. 기본값 5000 사용")
                    self.flask_port = 5000
                    self.server_port_var.set("5000")

                self.log(
                    f"포인트 메시지 표시 설정: {'켜짐' if self.show_point_messages else '꺼짐'}"
                )
                self.log(
                    f"배팅 메시지 표시 설정: {'켜짐' if self.show_betting_messages else '꺼짐'}"
                )

                if not silent:
                    self.log("입력값 가져오기 성공")
            except Exception as e:
                if not silent:
                    self.log(f"입력값 가져오기 오류: {str(e)}")
                raise Exception(f"입력값 처리 중 오류 발생: {str(e)}")

            if not silent:
                self.log("값 검증 완료, 설정 저장 준비 완료")

            # 설정 파일에 저장
            if not silent:
                self.log(f"설정 파일 생성 중: {self.settings_file}")

            # 설정 객체 생성
            settings = {
                "channel_id": self.channel_id,
                "access_token": self.access_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "min_points": self.min_points,
                "max_points": self.max_points,
                "jackpot_points": self.jackpot_points,
                "jackpot_chance": self.jackpot_chance,
                "cooldown_minutes": self.cooldown_minutes,
                "point_multiplier": self.point_multiplier,
                "show_point_messages": self.show_point_messages,
                "show_betting_messages": self.show_betting_messages,
                "flask_port": self.flask_port,
            }

            # 디버깅: 설정 객체 확인 (민감 정보 마스킹)
            debug_settings = settings.copy()
            if "client_secret" in debug_settings:
                debug_settings["client_secret"] = "[보안 정보 숨김]"
            if "access_token" in debug_settings:
                debug_settings["access_token"] = "[보안 정보 숨김]"
            self.log(f"저장할 설정 내용: {debug_settings}")

            # 파일 쓰기 시도
            try:
                with open(self.settings_file, "w", encoding="utf-8") as f:
                    json.dump(settings, f, ensure_ascii=False, indent=4)
                if not silent:
                    self.log("설정 파일이 성공적으로 저장되었습니다.")
            except Exception as e:
                if not silent:
                    self.log(f"파일 쓰기 오류: {str(e)}")
                raise Exception(f"설정 파일 쓰기 실패: {str(e)}")

            # 성공 메시지 표시 (silent 모드가 아닐 때만)
            if not silent:
                try:
                    messagebox.showinfo(
                        "설정 저장", "설정이 성공적으로 저장되었습니다."
                    )
                except Exception as e:
                    self.log(f"메시지 표시 오류: {str(e)}")
                self.log("설정이 저장되었습니다.")

            return True

        except Exception as e:
            if not silent:
                self.log(f"설정 저장 오류: {str(e)}")
                messagebox.showerror(
                    "설정 저장 오류", f"설정 저장에 실패했습니다:\n\n{str(e)}"
                )
            return False

    def load_settings(self):
        """설정 로드"""
        try:
            self.log(f"설정 파일 로드 중: {self.settings_file}")
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

                # 디버깅: 로드된 설정 확인 (민감 정보 마스킹)
                debug_settings = settings.copy()
                if "client_secret" in debug_settings:
                    debug_settings["client_secret"] = "[보안 정보 숨김]"
                if "access_token" in debug_settings:
                    debug_settings["access_token"] = "[보안 정보 숨김]"
                self.log(f"로드된 설정 내용: {debug_settings}")

                self.channel_id = settings.get("channel_id", "")
                self.access_token = settings.get("access_token", "")
                self.client_id = settings.get("client_id", "")
                self.client_secret = settings.get("client_secret", "")
                self.min_points = settings.get("min_points", 50)
                self.max_points = settings.get("max_points", 200)
                self.jackpot_points = settings.get("jackpot_points", 500)
                self.jackpot_chance = settings.get("jackpot_chance", 5)
                self.cooldown_minutes = settings.get("cooldown_minutes", 10)
                self.point_multiplier = settings.get("point_multiplier", 1.0)
                self.show_point_messages = settings.get("show_point_messages", True)
                self.show_betting_messages = settings.get("show_betting_messages", True)
                self.flask_port = settings.get("flask_port", 5000)
                self.overlay_url = f"http://localhost:{self.flask_port}/overlay"

                # 디버깅: 클라이언트 ID/시크릿 확인
                self.log(f"로드된 클라이언트 ID: {self.client_id}")
                self.log(
                    f"클라이언트 시크릿 로드됨: {'예' if self.client_secret else '아니오'}"
                )

                # UI
                self.channel_id_entry.delete(0, tk.END)
                self.channel_id_entry.insert(0, self.channel_id)

                self.api_key_entry.delete(0, tk.END)
                self.api_key_entry.insert(0, self.access_token)

                self.client_id_entry.delete(0, tk.END)
                self.client_id_entry.insert(0, self.client_id)

                self.client_secret_entry.delete(0, tk.END)
                self.client_secret_entry.insert(0, self.client_secret)

                self.min_points_entry.delete(0, tk.END)
                self.min_points_entry.insert(0, str(self.min_points))

                self.max_points_entry.delete(0, tk.END)
                self.max_points_entry.insert(0, str(self.max_points))

                self.jackpot_points_entry.delete(0, tk.END)
                self.jackpot_points_entry.insert(0, str(self.jackpot_points))

                self.jackpot_chance_entry.delete(0, tk.END)
                self.jackpot_chance_entry.insert(0, str(self.jackpot_chance))

                self.cooldown_entry.delete(0, tk.END)
                self.cooldown_entry.insert(0, str(self.cooldown_minutes))

                self.multiplier_var.set(str(self.point_multiplier))

                # 서버 포트 설정
                self.server_port_var.set(str(self.flask_port))

                # 포인트 메시지 표시 체크박스 업데이트
                self.show_point_messages_var.set(self.show_point_messages)
                self.settings_show_point_messages_var.set(self.show_point_messages)

                # 배팅 메시지 표시 체크박스 업데이트
                self.show_betting_messages_var.set(self.show_betting_messages)
                self.settings_show_betting_messages_var.set(self.show_betting_messages)

                self.log("설정이 로드되었습니다.")
            else:
                self.log("설정 파일을 찾을 수 없습니다. 기본값을 사용합니다.")
        except Exception as e:
            self.log(f"설정 로드 오류: {str(e)}")
            self.log("기본 설정값을 사용합니다.")

    def reset_points(self):
        """포인트 초기화"""
        if messagebox.askyesno(
            "포인트 초기화", "모든 유저의 포인트를 초기화하시겠습니까?"
        ):
            self.user_points = {}
            self.user_last_reward = {}
            self.refresh_users()
            self.update_stats()
            self.log("모든 유저의 포인트가 초기화되었습니다.")
            # 데이터 저장
            self.save_user_data()
            messagebox.showinfo("알림", "모든 유저의 포인트가 초기화되었습니다.")

    def save_user_data(self):
        """유저 데이터 저장"""
        try:
            self.log(f"유저 데이터 저장 중: {self.user_data_file}")
            # 유저 포인트 데이터
            user_data = {
                "points": self.user_points,
                "last_reward": {
                    user_id: time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(last_reward.timestamp())
                    )
                    for user_id, last_reward in self.user_last_reward.items()
                },
            }

            with open(self.user_data_file, "w", encoding="utf-8") as f:
                json.dump(user_data, f, ensure_ascii=False, indent=4)

            self.log("유저 데이터가 성공적으로 저장되었습니다.")
            return True
        except Exception as e:
            self.log(f"유저 데이터 저장 오류: {str(e)}")
            messagebox.showerror(
                "데이터 저장 오류", f"유저 데이터 저장에 실패했습니다: {str(e)}"
            )
            return False

    def load_user_data(self):
        """유저 데이터 로드"""
        try:
            self.log(f"유저 데이터 로드 중: {self.user_data_file}")
            if os.path.exists(self.user_data_file):
                with open(self.user_data_file, "r", encoding="utf-8") as f:
                    user_data = json.load(f)

                self.user_points = user_data.get("points", {})

                # 마지막 보상 시간 변환
                last_reward_data = user_data.get("last_reward", {})
                self.user_last_reward = {}

                for user_id, time_str in last_reward_data.items():
                    try:
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                        self.user_last_reward[user_id] = dt
                    except:
                        self.user_last_reward[user_id] = datetime.now()

                self.refresh_users()
                self.update_stats()
                self.log("유저 데이터가 로드되었습니다.")
                return True
            else:
                self.log("유저 데이터 파일을 찾을 수 없습니다. 빈 데이터로 시작합니다.")
                return False
        except Exception as e:
            self.log(f"유저 데이터 로드 오류: {str(e)}")
            self.log("기본 유저 데이터를 사용합니다.")
            return False

    def save_shop_items(self):
        """상점 아이템 저장"""
        try:
            self.log(f"상점 아이템 저장 중: {self.shop_items_file}")

            with open(self.shop_items_file, "w", encoding="utf-8") as f:
                json.dump(self.shop_items, f, ensure_ascii=False, indent=4)

            self.log("상점 아이템이 저장되었습니다.")
            return True
        except Exception as e:
            self.log(f"상점 아이템 저장 오류: {str(e)}")
            messagebox.showerror(
                "데이터 저장 오류", f"상점 아이템 저장에 실패했습니다: {str(e)}"
            )
            return False

    def load_shop_items(self):
        """상점 아이템 로드"""
        try:
            self.log(f"상점 아이템 로드 중: {self.shop_items_file}")
            if os.path.exists(self.shop_items_file):
                with open(self.shop_items_file, "r", encoding="utf-8") as f:
                    self.shop_items = json.load(f)

                self.log("상점 아이템이 로드되었습니다.")
                return True
            else:
                self.log("상점 아이템 파일을 찾을 수 없습니다. 빈 데이터로 시작합니다.")
                self.shop_items = {}
                return False
        except Exception as e:
            self.log(f"상점 아이템 로드 오류: {str(e)}")
            self.log("기본 상점 아이템을 사용합니다.")
            self.shop_items = {}
            return False

    def save_user_inventory(self):
        """유저 인벤토리 저장"""
        try:
            self.log(f"유저 인벤토리 저장 중: {self.user_inventory_file}")

            with open(self.user_inventory_file, "w", encoding="utf-8") as f:
                json.dump(self.user_inventory, f, ensure_ascii=False, indent=4)

            self.log("유저 인벤토리가 성공적으로 저장되었습니다.")
            return True
        except Exception as e:
            self.log(f"유저 인벤토리 저장 오류: {str(e)}")
            messagebox.showerror(
                "데이터 저장 오류", f"유저 인벤토리 저장에 실패했습니다: {str(e)}"
            )
            return False

    def load_user_inventory(self):
        """유저 인벤토리 로드"""
        try:
            self.log(f"유저 인벤토리 로드 중: {self.user_inventory_file}")
            if os.path.exists(self.user_inventory_file):
                with open(self.user_inventory_file, "r", encoding="utf-8") as f:
                    self.user_inventory = json.load(f)

                self.log("유저 인벤토리가 로드되었습니다.")
                return True
            else:
                self.log(
                    "유저 인벤토리 파일을 찾을 수 없습니다. 빈 데이터로 시작합니다."
                )
                self.user_inventory = {}
                return False
        except Exception as e:
            self.log(f"유저 인벤토리 로드 오류: {str(e)}")
            self.log("기본 유저 인벤토리를 사용합니다.")
            self.user_inventory = {}
            return False

    def settings_toggle_betting_messages(self):
        """배팅 메시지 표시 설정 변경 (설정 탭에서 변경시)"""
        self.show_betting_messages = self.settings_show_betting_messages_var.get()
        # 대시보드의 체크박스와 동기화
        self.show_betting_messages_var.set(self.show_betting_messages)

        message_status = "활성화" if self.show_betting_messages else "비활성화"
        self.log(f"배팅 메시지 표시 {message_status} (설정 탭에서 변경)")

        # 설정을 즉시 저장
        self.save_settings(silent=True)

    # 배팅 시스템 메서드
    def start_betting(self):
        """배팅 이벤트 시작"""
        if not self.is_connected:
            messagebox.showwarning("경고", "채팅에 연결되어 있지 않습니다.")
            return

        if self.is_betting_active:
            messagebox.showwarning("경고", "이미 진행 중인 배팅이 있습니다.")
            return

        # 배팅 주제 가져오기
        topic = self.betting_topic_entry.get().strip()
        if not topic:
            messagebox.showwarning("경고", "배팅 주제를 입력해주세요.")
            return

        # 배팅 옵션 가져오기
        options = []
        for entry in self.option_entries:
            option_text = entry.get().strip()
            if option_text:
                options.append(option_text)

        if len(options) < 2:
            messagebox.showwarning(
                "경고", "최소 2개 이상의 배팅 선택지를 설정해주세요."
            )
            return

        # 배팅 시간 가져오기
        try:
            betting_time = int(self.betting_time_var.get())
            if betting_time < 1:
                messagebox.showwarning(
                    "경고", "배팅 시간은 최소 1분 이상이어야 합니다."
                )
                return
        except ValueError:
            messagebox.showwarning("경고", "유효한 배팅 시간을 입력해주세요.")
            return

        # 배팅 이벤트 시작
        self.betting_event = {
            "topic": topic,
            "options": options,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.is_betting_active = True
        self.user_bets = {}  # 배팅 초기화
        self.betting_end_time = datetime.now() + timedelta(minutes=betting_time)

        # UI 업데이트
        self.start_betting_button.config(state=tk.DISABLED)
        self.end_betting_button.config(state=tk.NORMAL)
        self.current_betting_label.config(text=f"현재 배팅: {topic}")

        # 결과 선택지 콤보박스 업데이트
        self.result_combo["values"] = options

        # 배팅 상태 트리뷰 초기화
        for item in self.betting_tree.get_children():
            self.betting_tree.delete(item)

        for idx, option in enumerate(options):
            self.betting_tree.insert("", "end", values=(option, "0", "0", "0", "0.00"))

        # 타이머 시작
        self.update_betting_timer()

        # 오버레이 관련 로그 추가
        self.log(f"오버레이에 배팅 표시 시작: {topic}")
        self.log(f"오버레이 확인 URL: {self.overlay_url}")

        # 채팅에 배팅 시작 알림 (메시지 표시 설정에 따라)
        if self.show_betting_messages:
            self.send_chat_message(f"🎲 배팅 이벤트가 시작되었습니다! 🎲")
            time.sleep(0.3)
            self.send_chat_message(f"📢 주제: {topic}")
            time.sleep(0.3)

            # 배팅 옵션 안내
            self.send_chat_message("📊 배팅 선택지:")
            for idx, option in enumerate(options):
                self.send_chat_message(f"[{idx+1}] {option}")
                time.sleep(0.2)

            # 배팅 방법 안내
            time.sleep(0.3)
            self.send_chat_message(
                "💰 배팅 방법: !숫자 포인트 (예: !1 포인트 - 1번에 포인트/올인 배팅)"
            )

        self.log(
            f"배팅 이벤트 시작: {topic} (선택지: {len(options)}개, 시간: {betting_time}분)"
        )

    def update_betting_timer(self):
        """배팅 타이머 업데이트"""
        if not self.is_betting_active:
            return

        now = datetime.now()
        time_left = self.betting_end_time - now

        # 시간이 다 되면 자동으로 배팅 종료
        if time_left.total_seconds() <= 0:
            self.end_betting()
            return

        minutes_left = int(time_left.total_seconds() / 60)
        seconds_left = int(time_left.total_seconds() % 60)

        self.betting_time_left_label.config(
            text=f"남은 시간: {minutes_left}분 {seconds_left}초"
        )

        # 1분, 30초, 10초 남았을 때 채팅에 알림
        total_seconds = int(time_left.total_seconds())
        if self.show_betting_messages and total_seconds in [60, 30, 10]:
            self.send_chat_message(f"⏰ 배팅 마감까지 {total_seconds}초 남았습니다!")

        # 1초마다 타이머 업데이트
        self.betting_timer = self.root.after(1000, self.update_betting_timer)

    def update_betting_status(self):
        """배팅 현황 업데이트"""
        if not self.is_betting_active or not self.betting_event:
            return

        # 배팅 트리뷰 초기화
        for item in self.betting_tree.get_children():
            self.betting_tree.delete(item)

        # 각 옵션별 총 배팅액 계산
        option_stats = {}
        for option_idx in range(len(self.betting_event["options"])):
            option_stats[option_idx] = {
                "total_bets": 0,  # 배팅 수
                "total_points": 0,  # 총 배팅 포인트
                "participants": 0,  # 참여자 수
            }

        total_points = 0

        # 각 유저 배팅 정보 처리
        for user_id, bet_info in self.user_bets.items():
            option_idx = bet_info["option"]
            bet_amount = bet_info["amount"]

            option_stats[option_idx]["total_bets"] += 1
            option_stats[option_idx]["total_points"] += bet_amount
            option_stats[option_idx]["participants"] += 1

            total_points += bet_amount

        # 각 옵션별 배당률 계산 (최소 배당률은 1.0)
        for option_idx, stats in option_stats.items():
            if total_points > 0 and stats["total_points"] > 0:
                # 배당률 = 총 배팅액 / 해당 옵션 배팅액
                odds = round(total_points / stats["total_points"], 2)
            else:
                odds = 0.0

            option_name = self.betting_event["options"][option_idx]

            # 트리뷰에 추가
            self.betting_tree.insert(
                "",
                "end",
                values=(
                    option_name,
                    stats["total_bets"],
                    stats["total_points"],
                    stats["participants"],
                    f"{odds:.2f}",
                ),
            )

    def end_betting(self):
        """배팅 이벤트 종료"""
        if not self.is_betting_active:
            messagebox.showwarning("경고", "진행 중인 배팅이 없습니다.")
            return

        # 타이머 중지
        if self.betting_timer:
            self.root.after_cancel(self.betting_timer)
            self.betting_timer = None

        # 채팅에 배팅 종료 알림
        if self.show_betting_messages:
            self.send_chat_message("🚨 배팅이 마감되었습니다! 🚨")
            time.sleep(0.3)

        # UI 업데이트
        self.betting_time_left_label.config(text="배팅 종료")
        self.start_betting_button.config(state=tk.NORMAL)
        self.end_betting_button.config(state=tk.DISABLED)
        self.apply_result_button.config(state=tk.NORMAL)
        self.result_combo.config(state="readonly")

        self.log(f"배팅 '{self.betting_event['topic']}' 종료됨")

    def apply_betting_result(self):
        """배팅 결과 적용"""
        if not self.betting_event:
            messagebox.showwarning("경고", "적용할 배팅 결과가 없습니다.")
            return

        # 선택된 결과 확인
        selected_option = self.result_var.get()
        if not selected_option:
            messagebox.showwarning("경고", "당첨 선택지를 선택해주세요.")
            return

        # 선택지 인덱스 찾기
        selected_idx = -1
        for idx, option in enumerate(self.betting_event["options"]):
            if option == selected_option:
                selected_idx = idx
                break

        if selected_idx == -1:
            messagebox.showwarning("경고", "유효하지 않은 선택지입니다.")
            return

        # 총 배팅액 계산
        total_points = sum(bet["amount"] for bet in self.user_bets.values())

        # 당첨된 선택지에 배팅한 총액
        winning_points = sum(
            bet["amount"]
            for bet in self.user_bets.values()
            if bet["option"] == selected_idx
        )

        # 배당률 계산 (최소 1.0)
        if winning_points > 0:
            odds = max(1.0, total_points / winning_points)
        else:
            odds = 1.0

        # 당첨자 처리
        winners = []
        for user_id, bet_info in self.user_bets.items():
            if bet_info["option"] == selected_idx:
                # 배팅액 * 배당률로 포인트 지급
                win_amount = int(bet_info["amount"] * odds)

                # 포인트 지급
                if user_id not in self.user_points:
                    self.user_points[user_id] = 0

                self.user_points[user_id] += win_amount

                winners.append(
                    {
                        "user_id": user_id,
                        "bet_amount": bet_info["amount"],
                        "win_amount": win_amount,
                    }
                )

                self.log(
                    f"{user_id}님 배팅 당첨: {bet_info['amount']}포인트 배팅, {win_amount}포인트 획득"
                )

        # 배팅 결과 저장
        betting_result = {
            "topic": self.betting_event["topic"],
            "options": self.betting_event["options"],
            "start_time": self.betting_event["start_time"],
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "winning_option": selected_option,
            "winning_option_idx": selected_idx,
            "total_points": total_points,
            "odds": odds,
            "winners": winners,
            "user_bets": self.user_bets,
        }

        # 배팅 이력에 추가
        self.betting_history.append(betting_result)
        self.save_betting_history()

        # 채팅에 결과 발표
        if self.show_betting_messages:
            self.send_chat_message("🎉 배팅 결과가 발표되었습니다! 🎉")
            time.sleep(0.3)
            self.send_chat_message(
                f"📢 당첨 선택지: [{selected_idx+1}] {selected_option}"
            )
            time.sleep(0.3)
            self.send_chat_message(f"💰 배당률: {odds:.2f}배")
            time.sleep(0.3)

            # 당첨자 수만 발표 (개별 당첨자 정보는 표시하지 않음)
            if winners:
                self.send_chat_message(f"🏆 당첨자: {len(winners)}명")
                # 당첨자 개별 정보는 로그에만 기록
                for winner in sorted(
                    winners, key=lambda x: x["win_amount"], reverse=True
                ):
                    user_id = winner["user_id"]
                    bet_amount = winner["bet_amount"]
                    win_amount = winner["win_amount"]
                    self.log(
                        f"배팅 당첨자: {user_id} - {bet_amount}포인트 -> {win_amount}포인트 획득"
                    )
            else:
                self.send_chat_message("😢 당첨자가 없습니다.")

        # 배팅 상태 초기화
        self.betting_event = None
        self.is_betting_active = False
        self.user_bets = {}
        self.betting_end_time = None

        # UI 초기화
        self.current_betting_label.config(text="현재 진행 중인 배팅이 없습니다.")
        self.betting_time_left_label.config(text="")
        self.result_combo.config(state=tk.DISABLED)
        self.apply_result_button.config(state=tk.DISABLED)

        # 배팅 이력 새로고침
        self.refresh_betting_history()

        # 유저 포인트 저장
        self.save_user_data()
        self.refresh_users()

        self.log("배팅 결과 적용 완료")
        messagebox.showinfo("알림", "배팅 결과가 성공적으로 적용되었습니다.")

    def save_betting_history(self):
        """배팅 이력 저장"""
        try:
            self.log(f"배팅 이력 저장 중: {self.betting_results_file}")

            with open(self.betting_results_file, "w", encoding="utf-8") as f:
                json.dump(self.betting_history, f, ensure_ascii=False, indent=4)

            self.log("배팅 이력이 성공적으로 저장되었습니다.")
            return True
        except Exception as e:
            self.log(f"배팅 이력 저장 오류: {str(e)}")
            return False

    def load_betting_history(self):
        """배팅 이력 로드"""
        try:
            self.log(f"배팅 이력 로드 중: {self.betting_results_file}")

            if os.path.exists(self.betting_results_file):
                with open(self.betting_results_file, "r", encoding="utf-8") as f:
                    self.betting_history = json.load(f)

                self.log(f"배팅 이력 로드 완료: {len(self.betting_history)}개 이벤트")
                return True
            else:
                self.log("배팅 이력 파일이 없습니다. 새로 시작합니다.")
                self.betting_history = []
                return False
        except Exception as e:
            self.log(f"배팅 이력 로드 오류: {str(e)}")
            self.betting_history = []
            return False

    def refresh_betting_history(self):
        """배팅 이력 목록 새로고침"""
        # 트리뷰 초기화
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        # 최근 이력부터 표시
        for event in reversed(self.betting_history):
            date = event.get("end_time", "알 수 없음")
            topic = event.get("topic", "알 수 없음")
            options_count = len(event.get("options", []))
            total_points = event.get("total_points", 0)
            winner = event.get("winning_option", "알 수 없음")

            self.history_tree.insert(
                "", "end", values=(date, topic, options_count, total_points, winner)
            )

        self.update_stats()

    def toggle_betting_messages(self):
        """배팅 메시지 표시 설정 변경 (대시보드에서 변경시)"""
        self.show_betting_messages = self.show_betting_messages_var.get()
        # 설정 탭의 체크박스와 동기화
        self.settings_show_betting_messages_var.set(self.show_betting_messages)

        message_status = "활성화" if self.show_betting_messages else "비활성화"
        self.log(f"배팅 메시지 표시 {message_status}")

        # 설정을 즉시 저장
        self.save_settings(silent=True)

        # 설정이 변경되었음을 알림
        if self.is_connected:
            if self.show_betting_messages:
                self.send_chat_message("✅ 배팅 관련 메시지 표시가 활성화되었습니다.")
            else:
                self.send_chat_message("🔕 배팅 관련 메시지 표시가 비활성화되었습니다.")

        # 메시지 변경 확인
        messagebox.showinfo(
            "설정 변경", f"배팅 관련 메시지 표시가 {message_status}되었습니다."
        )

    def exit_handler(self):
        """프로그램 종료 시 처리"""
        try:
            self.log("프로그램 종료 중...")

            # 테스트 모드 중지
            self.is_running = False

            # 배팅 타이머 중지
            if self.betting_timer:
                self.root.after_cancel(self.betting_timer)
                self.betting_timer = None

            # 연결 종료
            if self.is_connected:
                self.log("연결된 상태에서 종료: 연결 해제 중...")
                if self.sio and hasattr(self.sio, "connected") and self.sio.connected:
                    try:
                        self.sio.disconnect()
                        self.log("Socket.IO 연결 정상 종료")
                    except Exception as e:
                        self.log(f"Socket.IO 연결 종료 중 오류: {str(e)}")

            # 데이터 저장
            try:
                self.log("설정 저장 중...")
                self.save_settings(silent=True)
            except Exception as e:
                self.log(f"설정 저장 중 오류: {str(e)}")

            try:
                self.log("유저 데이터 저장 중...")
                self.save_user_data()
            except Exception as e:
                self.log(f"유저 데이터 저장 중 오류: {str(e)}")

            try:
                self.log("상점 아이템 저장 중...")
                self.save_shop_items()
            except Exception as e:
                self.log(f"상점 아이템 저장 중 오류: {str(e)}")

            try:
                self.log("유저 인벤토리 저장 중...")
                self.save_user_inventory()
            except Exception as e:
                self.log(f"유저 인벤토리 저장 중 오류: {str(e)}")

            # 배팅 이력 저장
            try:
                self.log("배팅 이력 저장 중...")
                self.save_betting_history()
            except Exception as e:
                self.log(f"배팅 이력 저장 중 오류: {str(e)}")

            self.log("프로그램이 안전하게 종료됩니다.")
        except Exception as e:
            self.log(f"종료 중 오류 발생: {str(e)}")
        finally:
            # 종료 전 마지막 로그
            print("프로그램이 종료됩니다.")
            self.root.destroy()


def run_app():
    root = tk.Tk()

    # 앱 아이콘 설정 (옵션)
    try:
        if sys.platform == "win32":
            root.iconbitmap("icon.ico")  # Windows용 아이콘 (필요시 파일 준비)
    except:
        pass  # 아이콘 로드 실패 시 기본 아이콘 사용

    app = ChzzkPointsBot(root)

    # 종료 이벤트 처리
    root.protocol("WM_DELETE_WINDOW", app.exit_handler)

    # 시작 시 데이터 로드
    app.load_user_data()
    app.load_shop_items()
    app.load_user_inventory()
    app.load_betting_history()

    # 창 중앙에 표시
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f"+{x}+{y}")

    # 메인 루프 시작
    root.mainloop()

    return app


if __name__ == "__main__":
    run_app()
else:
    # 모듈로 임포트될 때도 실행
    root = tk.Tk()
    app = ChzzkPointsBot(root)
