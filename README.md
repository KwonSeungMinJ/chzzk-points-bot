# 🎯 치지직 포인트봇

**치지직 포인트봇**은 **치지직 공식 API**를 기반으로 작동하는 유저 참여형 봇입니다.  
**배팅 오버레이**와 **상점 아이템 사용 오버레이** 기능을 제공합니다.

> 💡 사용자는 프로그램 설정을 통해 직접 치지직 계정과 연동하여 사용합니다.

![image](https://github.com/user-attachments/assets/3d0595bc-c8c9-4e19-8631-6a62b89c881b)
![image](https://github.com/user-attachments/assets/d8ba9d9d-1dd6-4484-845a-1355d192f56e)


## 📦 주요 기능

### ✅ 명령어 안내

| 명령어 | 설명 |
|--------|------|
| `!상점` | 상점 아이템 리스트 출력 |
| `!<이름>` | 해당 이름의 상점 아이템 구매 |
| `!사용 <이름>` | 인벤토리에서 아이템 사용 |
| `!아이템` | 내 인벤토리 확인 |
| `!<숫자> <금액>` 또는 `!<숫자> 올인` | 해당 선택지에 배팅 |


![image](https://github.com/user-attachments/assets/2060cfe4-5767-46e5-8556-c0e99c3d4101)

## ⚙️ 봇 연결 및 설정 방법

1. **봇 상태 연결** 버튼 클릭 시 연결 시도  
2. 설정 값이 정확할 경우, **메시지 박스 2개**가 뜨며 정상 연결됨을 확인할 수 있습니다.

> 설정 항목: `채널 ID`, `Access Token`, `Client ID`, `Client Secret`  
한 번 등록하면 값은 저장되며, **Access Token만 주기적으로 갱신**하면 됩니다.
> 
> ## 🔧 설정 기능 요약

### 🎚️ 이벤트 포인트 배율
- 배율에 따라 포인트 획득량 조정 가능

### 💬 메시지 설정
- 채팅 출력 여부를 토글로 변경 가능

### 💰 포인트 및 오버레이 설정
- 포인트 기본값 설정  
- 오버레이 서버 포트 변경 가능

![image](https://github.com/user-attachments/assets/c70a2477-4ff2-47a8-b8af-3743db9ae015)

채널 ID, 액세서 토큰, 클라이언트 ID, 클라이언터 secret 정보를 넣어줘야 연결을 했을 때 오류가 뜨지않습니다 한번 등록 하면 저장이 되니 엑세스 토큰 값만 변경 해주시면 됩니다. [엑세서 토큰 반자동 프로그램은 아래에 설명과 파일을 올리겠습니다]

## 🛒 상점 & 인벤토리 관리

- 유저 클릭 → 인벤토리 확인 가능  
- 유저 더블 클릭 → 포인트 수정 가능  
- 아이템 **추가 / 수정 / 삭제** 가능

![image](https://github.com/user-attachments/assets/32c9a8d6-a17d-4454-80cf-72e6c0883583)

유저를 누르고 인벤토리 확인하면 유저의 인벤토리를 확인 가능합니다

![image](https://github.com/user-attachments/assets/a340365d-e311-48e4-a251-b5edad4087da)

유저만 더블 클릭하면 유저의 포인트를 수정 가능합니다.

![image](https://github.com/user-attachments/assets/540b24ac-e1b1-49ff-af74-3ff0cec613e0)

아이템을 추가 및 수정 삭제 가능합니다.

![image](https://github.com/user-attachments/assets/e398417c-e33c-43d0-a377-455a0fe99843)

## 🎰 배팅 기능

배팅 주제에 제목을 적어줍니다 그리고 선택지에 배팅 내용을 적습니다 

예 : 배팅 주제 : 누가 이길까요? , 선택지 1번 : 레드팀 2번 : 블루팀 3번 무승부

배팅 시간 : 배팅을 걸 수 있는 시간

오버레이 설정을 하면 방송 화면에 표시 할 수 있습니다 [다음]

![image](https://github.com/user-attachments/assets/db50f503-45a5-460d-85dd-2f22459d880b)

URL 복사 버튼을 누르면 링크가 저장 복사가 되는데 OBS 브라우저 열기에 그대로 넣고 크기 설정 해주시면 됩니다 [배팅 오버레이, 아이템 사용 오버레이]

로그는 말그대로 로그를 보여줍니다

ㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡㅡ

## 🪄 엑세스 토큰 발급 방법


 ![image](https://github.com/user-attachments/assets/bef2af4d-a21d-4b4b-8287-868d153b8d9f)

 먼저 위 사이트로 이동해서 네이버로 로그인 후 상단의 Application 버튼을 클릭한다.

![image](https://github.com/user-attachments/assets/50817bb4-58eb-41fd-8756-3f61164f7571)

이후 애플리케이션 목록 - 애플리케이션 등록 버튼을 클릭한다.

 ![image](https://github.com/user-attachments/assets/2f65dce7-af97-445a-8c76-3300060e71a9)

 애플리케이션 ID와 이름의 경우 사용자 마음대로 지정해도 되고, 본인처럼 테스트를 위한 경우나 잘 모르겠다면

로그인 리디렉션 URL을 https://localhost:8080으로 지정한다.

![image](https://github.com/user-attachments/assets/08490ae3-e0f4-4975-95e4-4486b1688282)

애플리케이션 ID 및 이름에 'chzzk', '치지직', 'naver', '네이버' 등 공식 서비스명은 포함하면 안된다는 메일이 날아왔다.

공식 서비스명을 포함하지 않도록 앱 이름 수정에 유의해야 한다.

![image](https://github.com/user-attachments/assets/cf4bf493-6efa-445f-b78b-44a12bb87cfd)

개발하고 싶은 기능에 맞춰 API Scope를 지정한다. 그냥 전부 체크해도 무관합니다.

해당 scope 지정의 경우 scope마다 필요로 하는 인증 방식이 다르고, 기능들을 사용하기 위해서는 치지직에서 권한에 대해 승인을 받아야 사용할 수 있다.

Scope 지정을 완료했다면 저장 후 등록 버튼을 클릭한다.

![image](https://github.com/user-attachments/assets/e266e3ff-f261-4598-986f-5a9047e727ab)

등록을 완료하고 애플리케이션에서 Client ID, Secret Key 값을 확인할 수 있고, 애플리케이션 이름, 리디렉션 URL, Scope 정보도 수정해 줄 수 있다.

Scope의 경우 기능 추가 및 변경 시, 해당 기능에 대해 치지직에 권한을 다시 승인받아야 한다.

그리고 승인 대기중에서 며칠 지나면 승인 됨으로 변경되면 그 때부터 봇 사용이 가능합니다.

![image](https://github.com/user-attachments/assets/edba3fef-08d1-4ce5-a806-a99e68c1c9a8)

굵은 글씨에 있는 정보는 개발자 센터에 있는 데이터를 그대로 넣으면 됩니다.

그리고 네이버 아이디 비밀번호 넣고 2차 인증이 필요한 계정이면 체크 박스에 체크를 하고 코드 받기 하면 인터넷 창이 자동으로 켜지고 기다리면 엑세스 토큰이 발급이 됩니다.


## 최신 버전은 인증 API 프로그램과 봇 프로그램을 합쳐 사용하기 더 편해졌습니다. ##

## 📝 문의

- 💌 **이메일**: `eovldkdlel1@naver.com`

