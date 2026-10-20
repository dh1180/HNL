# HNL Web v0.2 문법 가이드

엄랭처럼 일부러 불편하게 만든 HNL 문법으로 **실제 HTTP 서버**를 개발할 수 있습니다. 웹 엔진은 Python 표준 라이브러리만 사용합니다(Python 3.10+).

## 실행

```bash
python hnl.py examples/web/site.hnl
# 요이~ㅋㅋ HNL 웹 서버: http://127.0.0.1:8080
```

브라우저에서 <http://127.0.0.1:8080/>를 엽니다. 종료는 `Ctrl+C`입니다.

```bash
python hnl.py examples/web/site.hnl --port 9090
python hnl.py examples/web/site.hnl --host 0.0.0.0 --port 8080
```

**주의:** `0.0.0.0`은 모든 네트워크 인터페이스에서 요청을 받습니다. HNL Web v0.2는 학습용 개발 서버이며, 인증·TLS·DB·운영 수준 보안 설정이 구현되지 않았으므로 그대로 인터넷에 공개하지 마세요.

## 파일 구성

```text
hnl.py                   기존 CLI 및 웹 프로그램 구동
hnl_web.py               HTTP 서버/웹 구문 파서/인터프리터
examples/web/site.hnl    HNL 웹 애플리케이션
examples/web/public/     일반적인 CSS, JavaScript 파일
```

## 웹 프로그램 형식

```text
엄.
동탄어?준 127.0.0.1:8080

티~원 정적 /assets public

티~원 GET /
아뇨아뇨아뇨! html
요이~ㅋㅋ "<h1>요이~ㅋㅋ</h1>"
식어어ㅋ

티~원 GET /hello/:name
요이~ㅋㅋ "<h1>반가워, " 동탄어?준.path.name|html "</h1>"
식어어ㅋ

줴줴이야
```

시작/종료는 기존과 동일합니다. `동탄어?준`은 웹 서버 시작 주소/포트입니다. `티~원 METHOD /path`부터 `식어어ㅋ`까지가 하나의 라우트입니다. `티~원 정적 /assets public`은 파일을 제공하는 정적 라우트 선언입니다.

## 웹 구문

| HNL 구문 | 의미 |
| --- | --- |
| `동탄어?준 127.0.0.1:8080` | 웹 서버 실행 주소와 포트 |
| `티~원 GET /url` | GET 라우트 시작 (`POST`, `PUT`, `PATCH`, `DELETE`, `HEAD` 지원) |
| `식어어ㅋ` | 라우트 끝 |
| `티~원 정적 /assets public` | `public` 폴더를 `/assets/...`로 서빙 |
| `아뇨아뇨아뇨! html` | `html` / `text` / `json` / `css` / `js` 응답 타입 |
| `예에에! 201` | HTTP 응답 상태 (100~599, 이 설정에서만 일반 숫자 허용) |
| `요이~ㅋㅋ "텍스트"` | 문자열 출력(웹 모드에서만 허용) |
| `티~원! "/"` | 사이트 내부 경로로 HTTP 303 리다이렉트 |
| `엄~ "abc"` | 요청 내에서 1번 변수에 문자열 대입 |
| `엄~! key : "abc"` | 여러 요청에서 공유하는 **메모리** 상태 저장 |
| `어~!key` | 공유 메모리 상태 읽기(미존재시 0) |

기존의 `ㅋㅋ`, `ㅠ`, `어`, `ㅋㅋ~ㅋㅋㅋ`, `티~원 <명령번호>`, `예에에?`, `아뇨아뇨아뇨`, `요이~ㅋㅋㅋ`, `요이~ㅋㅋㅋㅋ`는 **라우트 내부에서 그대로** 사용할 수 있습니다. 점프 번호는 각 라우트 안의 명령을 1부터 셉니다(라우트 선언/종료 구문 제외).

공백으로 더하기(문자열이면 이어붙이기), `~`로 곱하기(문자열 × 양의 정수면 반복) 등 HNL식 계산을 유지합니다.

### 요청값 읽기

| 표현 | 뜻 |
| --- | --- |
| `동탄어?준.method` | HTTP 메서드 (`GET` 등) |
| `동탄어?준.url` | URL의 경로 |
| `동탄어?준.query.name` | `?name=...` 쿼리 |
| `동탄어?준.path.name` | `/hello/:name` 경로 매개변수 |
| `동탄어?준.form.message` | `application/x-www-form-urlencoded` 폼 값 |
| `동탄어?준.json.message` | JSON 객체의 `message` 값 |
| `동탄어?준.header.user-agent` | HTTP 요청 헤더 |
| `동탄어?준.body` | UTF-8 요청 본문 문자열 |

`|html`은 HTML 특수문자를 이스케이프하고, `|json`은 JSON 문자열/값으로 안전하게 직렬화합니다. 사용자 입력을 HTML/JSON에 출력할 때 반드시 사용하세요.

```text
요이~ㅋㅋ "<h1>" 동탄어?준.query.name|html "</h1>"
요이~ㅋㅋ "{\"name\":" 동탄어?준.json.name|json "}"
```

### 폼 입력·리다이렉트 예제

```text
티~원 POST /save
엄~! last_note : 동탄어?준.form.message
티~원! "/"
식어어ㅋ
```

방문 상태 같은 값도 `엄~! visits : 어~!visits ㅋ`로 증가시킬 수 있습니다. 공유 메모리는 서버를 재시작하면 모두 초기화되며 데이터베이스가 아닙니다.

## 기술적 한계 및 안전

- 프런트엔드의 CSS/JavaScript는 일반 웹 표준 파일을 정적으로 제공합니다. JavaScript까지 HNL로 실행하는 기능은 아직 없습니다.
- 웹 서버는 Python `ThreadingHTTPServer`를 사용하며 라우트별 레지스터는 요청마다 초기화, 공유 상태는 잠금을 통해 보호합니다.
- 크기 제한: 요청 본문 1 MiB, 응답 본문 2 MiB, 정적 파일 8 MiB, 공유 상태 항목 1000개. 웹 라우트 명령 기본 2만 회 제한.
- 정적 파일은 소스 하위의 지정 폴더만 읽고 경로 이탈 및 숨김 파일 접근을 차단합니다.
- 요청 실패는 HTTP `400`/`404`/`405`/`413`, 서버 실행 오류는 `500`으로 응답합니다. 오류 스택을 방문자에게 보여주지 않습니다.
- 데이터베이스, 인증, 세션, CSRF 방어, TLS, 프로덕션 WSGI/ASGI 연동, 웹소켓, 배포 자동화 등은 **미지원**입니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

HNL v0.1의 CLI 기능과 웹 기능 테스트가 같이 실행됩니다.
