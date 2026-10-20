"""The HNL web dialect: small, standard-library-only HTTP runtime.

Route programs keep HNL's register arithmetic and branching, while adding
quoted text, request atoms, HTML/JSON escaping, and response instructions.
"""
from __future__ import annotations

import ast
import html
import json
import mimetypes
import re
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from hnl import HNLError

MAX_BODY = 1_048_576
MAX_RESPONSE = 2_097_152
MAX_STEPS = 20_000
MAX_STATIC = 8_388_608
MAX_STATE_KEYS = 1000
CONTENT_TYPES = {
    'html': 'text/html; charset=utf-8',
    'text': 'text/plain; charset=utf-8',
    'json': 'application/json; charset=utf-8',
    'css': 'text/css; charset=utf-8',
    'js': 'text/javascript; charset=utf-8',
}
METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'}
TOKEN = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|어~![^\s~"']+|~|[^\s~"']+''')
ROUTE = re.compile(r'^티~원\s+(GET|POST|PUT|PATCH|DELETE|HEAD)\s+(/\S*)$')
STATIC = re.compile(r'^티~원\s+정적\s+(/\S*)\s+(\S+)$')
STORAGE = re.compile(r'^엄~!\s+([\w.\-]+)\s*:\s*(.+)$')
ASSIGN = re.compile(r'^엄(~+)\s*(.*)$')


@dataclass(frozen=True)
class Instruction:
    command: str
    operand: str
    line: int


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    regex: re.Pattern[str]
    fields: tuple[str, ...]
    instructions: tuple[Instruction, ...]


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    form: dict[str, str] = field(default_factory=dict)
    json_data: dict[str, object] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ''


def _tokens(expr: str) -> list[str]:
    pos = 0
    items = []
    for match in TOKEN.finditer(expr):
        if expr[pos:match.start()].strip():
            raise HNLError('잘못된 문자열 또는 식입니다.')
        items.append(match.group())
        pos = match.end()
    if expr[pos:].strip():
        raise HNLError('닫히지 않은 따옴표 또는 잘못된 식입니다.')
    return items


def _truth(value: str | int) -> bool:
    return value != 0 and value != ''


def _str(value: str | int) -> str:
    return str(value)


def _add(left: str | int, right: str | int) -> str | int:
    if isinstance(left, str) or isinstance(right, str):
        return _str(left) + _str(right)
    return left + right


def _multiply(a: str | int, b: str | int) -> str | int:
    if isinstance(a, int) and isinstance(b, int):
        return a * b
    if isinstance(a, str) and isinstance(b, int) and 0 <= b <= 10000:
        return a * b
    if isinstance(b, str) and isinstance(a, int) and 0 <= a <= 10000:
        return b * a
    raise HNLError('문자열끼리는 곱할 수 없습니다.')


class Expression:
    def __init__(self, request: Request, registers: dict[int, str | int], state: dict[str, str | int]):
        self.request, self.registers, self.state = request, registers, state

    def atom(self, token: str) -> str | int:
        if token.startswith(('"', "'")):
            try:
                literal = ast.literal_eval(token)
            except (SyntaxError, ValueError) as exc:
                raise HNLError('잘못된 문자열 리터럴입니다.') from exc
            if not isinstance(literal, str):
                raise HNLError('문자열만 사용할 수 있습니다.')
            return literal
        if re.fullmatch('[ㅋㅠ]+', token):
            return token.count('ㅋ') - token.count('ㅠ')
        if re.fullmatch('어+', token):
            return self.registers.get(len(token), 0)
        if token.startswith('어~!'):
            key, separator, filt = token[3:].partition('|')
            value = self.state.get(key, 0)
            if not separator:
                return value
            if filt == 'html':
                return html.escape(str(value), quote=True)
            if filt == 'json':
                return json.dumps(value, ensure_ascii=False)
            raise HNLError(f'알 수 없는 필터: {filt}')
        if token.startswith('동탄어?준.'):
            stem, separator, filter_name = token.partition('|')
            path = stem[len('동탄어?준.'):]
            sections = path.split('.', 1)
            category = sections[0]
            key = sections[1] if len(sections) > 1 else ''
            sources = {
                'query': self.request.query,
                'form': self.request.form,
                'json': self.request.json_data,
                'path': self.request.params,
                'header': self.request.headers,
            }
            if category == 'method' and not key:
                result = self.request.method
            elif category == 'url' and not key:
                result = self.request.path
            elif category == 'body' and not key:
                result = self.request.body
            elif category in sources and key:
                result = sources[category].get(key, '')
            else:
                raise HNLError(f'존재하지 않는 요청 항목: {stem}')
            if result is None:
                result = ''
            if isinstance(result, (dict, list)):
                result = json.dumps(result, ensure_ascii=False)
            if separator:
                if filter_name == 'html':
                    return html.escape(str(result), quote=True)
                if filter_name == 'json':
                    return json.dumps(result, ensure_ascii=False)
                raise HNLError(f'알 수 없는 필터: {filter_name}')
            if isinstance(result, (int, str)):
                return result
            return str(result)
        raise HNLError(f'알 수 없는 값: {token!r}')

    def evaluate(self, expr: str) -> str | int:
        tokens = _tokens(expr)
        if not tokens:
            return 0
        operands: list[str | int] = []
        current: str | int | None = None
        needs_factor = False
        for token in tokens:
            if token == '~':
                if current is None or needs_factor:
                    raise HNLError('잘못된 곱셈식입니다.')
                needs_factor = True
                continue
            # Backwards-compatible support: legacy expressions can write
            # ㅋㅋ~ㅋㅋ without whitespace.
            part = self.atom(token)
            if needs_factor:
                current = _multiply(current, part)  # type: ignore[arg-type]
                needs_factor = False
            else:
                if current is not None:
                    operands.append(current)
                current = part
        if needs_factor:
            raise HNLError('곱셈식 뒤에 값이 없습니다.')
        if current is not None:
            operands.append(current)
        result: str | int = operands[0]
        for item in operands[1:]:
            result = _add(result, item)
        return result


def _compile_instruction(line: str, lineno: int) -> Instruction:
    match = STORAGE.fullmatch(line)
    if match:
        return Instruction('state:' + match.group(1), match.group(2), lineno)
    match = ASSIGN.fullmatch(line)
    if match:
        return Instruction('store:' + str(len(match.group(1))), match.group(2), lineno)
    if line == '요이~ㅋㅋㅋㅋ':
        return Instruction('newline', '', lineno)
    if line.startswith('요이~ㅋㅋㅋ '):
        return Instruction('char', line[len('요이~ㅋㅋㅋ '):].strip(), lineno)
    if line.startswith('요이~ㅋㅋ '):
        return Instruction('print', line[len('요이~ㅋㅋ '):].strip(), lineno)
    if line.startswith('아뇨아뇨아뇨! '):
        return Instruction('content-type', line[len('아뇨아뇨아뇨! '):].strip(), lineno)
    if line.startswith('예에에! '):
        return Instruction('status', line[len('예에에! '):].strip(), lineno)
    if line.startswith('티~원! '):
        return Instruction('redirect', line[len('티~원! '):].strip(), lineno)
    if line.startswith('티~원 '):
        return Instruction('goto', line[len('티~원 '):].strip(), lineno)
    for prefix, command in (('예에에? ', 'ifzero'), ('아뇨아뇨아뇨 ', 'ifnotzero')):
        if line.startswith(prefix):
            return Instruction(command, line[len(prefix):].strip(), lineno)
    raise HNLError(f'{lineno}행: 알 수 없는 웹 명령어: {line}')


def _compile_route(path: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    if not path.startswith('/') or any(c in path for c in ('?', '#')):
        raise HNLError(f'잘못된 URL 경로: {path!r}')
    segments = path.split('/')
    fields: list[str] = []
    regex_parts = []
    for seg in segments:
        if seg.startswith(':'):
            name = seg[1:]
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name) or name in fields:
                raise HNLError(f'잘못된 URL 매개변수: {seg}')
            fields.append(name)
            regex_parts.append(f'(?P<{name}>[^/]+)')
        else:
            regex_parts.append(re.escape(seg))
    return re.compile('^' + '/'.join(regex_parts) + '$'), tuple(fields)


class WebApplication:
    def __init__(self, source: str, *, base_dir: Path | str = '.', max_steps: int = MAX_STEPS):
        if max_steps < 1:
            raise ValueError('max_steps must be positive')
        lines = [(i, line.strip()) for i, line in enumerate(source.splitlines(), 1)
                 if line.strip() and not line.lstrip().startswith('#')]
        if len(lines) < 4 or lines[0][1] != '엄.' or lines[-1][1] != '줴줴이야':
            raise HNLError('웹 프로그램은 엄.으로 시작하고 줴줴이야로 끝나야 합니다.')
        header = re.fullmatch(r'동탄어\?준\s+(?:(\d{1,3}(?:\.\d{1,3}){3}):)?(\d{1,5})', lines[1][1])
        if not header:
            raise HNLError('두 번째 명령은 동탄어?준 [IPv4:]포트여야 합니다.')
        self.host = header.group(1) or '127.0.0.1'
        self.port = int(header.group(2))
        if not 0 <= self.port <= 65535:
            raise HNLError('포트는 0~65535여야 합니다.')
        self.base_dir = Path(base_dir).resolve()
        self.routes: list[Route] = []
        self.static: list[tuple[str, Path]] = []
        self.state: dict[str, str | int] = {}
        self.lock = threading.RLock()
        self.max_steps = max_steps
        active: tuple[str, str, re.Pattern[str], tuple[str, ...]] | None = None
        instructions: list[Instruction] = []
        for line_no, line in lines[2:-1]:
            route = ROUTE.fullmatch(line)
            static = STATIC.fullmatch(line)
            if active is None:
                if route:
                    method, path = route.groups()
                    regex, fields = _compile_route(path)
                    if any(r.method == method and r.pattern == path for r in self.routes):
                        raise HNLError(f'{line_no}행: 중복 라우트: {method} {path}')
                    active = method, path, regex, fields
                    instructions = []
                elif static:
                    prefix, directory = static.groups()
                    if prefix == '/' or ':' in prefix or '?' in prefix:
                        raise HNLError(f'{line_no}행: 정적 경로는 /static처럼 지정해야 합니다.')
                    root = (self.base_dir / directory).resolve()
                    if not root.is_relative_to(self.base_dir):
                        raise HNLError(f'{line_no}행: 정적 폴더는 소스 폴더 내부에 있어야 합니다.')
                    if not root.is_dir():
                        raise HNLError(f'{line_no}행: 정적 폴더가 없습니다: {directory}')
                    self.static.append((prefix.rstrip('/'), root))
                else:
                    raise HNLError(f'{line_no}행: 라우트 밖에는 티~원 GET/POST 또는 티~원 정적만 가능합니다.')
            else:
                if line == '식어어ㅋ':
                    method, path, regex, fields = active
                    self.routes.append(Route(method, path, regex, fields, tuple(instructions)))
                    active = None
                elif route or static:
                    raise HNLError(f'{line_no}행: 기존 라우트를 식어어ㅋ로 닫아야 합니다.')
                else:
                    instructions.append(_compile_instruction(line, line_no))
        if active is not None:
            raise HNLError('라우트 끝에 식어어ㅋ가 없습니다.')
        if not self.routes and not self.static:
            raise HNLError('웹 라우트 또는 정적 폴더가 필요합니다.')

    def _execute(self, route: Route, request: Request) -> Response:
        regs: dict[int, str | int] = {}
        ev = Expression(request, regs, self.state)
        parts: list[str] = []
        length = 0
        status = 200
        content_type = CONTENT_TYPES['html']
        headers: dict[str, str] = {}
        pc = 0
        steps = 0
        with self.lock:
            while pc < len(route.instructions):
                inst = route.instructions[pc]
                steps += 1
                if steps > self.max_steps:
                    raise HNLError(f'{inst.line}행: 실행 횟수 제한 초과')
                cmd, arg = inst.command, inst.operand
                try:
                    if cmd.startswith('store:'):
                        regs[int(cmd.partition(':')[2])] = ev.evaluate(arg)
                    elif cmd.startswith('state:'):
                        key = cmd.partition(':')[2]
                        if key not in self.state and len(self.state) >= MAX_STATE_KEYS:
                            raise HNLError('전역 상태 개수 제한 초과')
                        self.state[key] = ev.evaluate(arg)
                    elif cmd in ('print', 'char', 'newline'):
                        if cmd == 'newline':
                            text = '\n'
                        elif cmd == 'char':
                            code = ev.evaluate(arg)
                            if not isinstance(code, int) or not 0 <= code <= 0x10FFFF:
                                raise HNLError('Unicode 문자는 0~0x10FFFF 정수만 가능합니다.')
                            text = chr(code)
                        else:
                            text = str(ev.evaluate(arg))
                        length += len(text.encode('utf-8'))
                        if length > MAX_RESPONSE:
                            raise HNLError('응답 크기 제한 초과')
                        parts.append(text)
                    elif cmd == 'content-type':
                        if arg not in CONTENT_TYPES:
                            raise HNLError('지원하지 않는 타입: ' + arg)
                        content_type = CONTENT_TYPES[arg]
                    elif cmd == 'status':
                        val = int(arg) if arg.isascii() and arg.isdigit() else ev.evaluate(arg)
                        if not isinstance(val, int) or not 100 <= val <= 599:
                            raise HNLError('HTTP 상태는 100~599 숫자여야 합니다.')
                        status = val
                    elif cmd == 'redirect':
                        location = str(ev.evaluate(arg))
                        if not location.startswith('/') or location.startswith('//') or any(x in location for x in ('\r', '\n', '\x00')):
                            raise HNLError('리다이렉트는 안전한 사이트 내부 절대 경로(/...)만 가능합니다.')
                        status = 303
                        headers['Location'] = location
                    elif cmd in ('goto', 'ifzero', 'ifnotzero'):
                        should_jump = True
                        destination = arg
                        if cmd != 'goto':
                            pieces = arg.rsplit(' : ', 1)
                            if len(pieces) != 2:
                                raise HNLError('조건문은 값 : 명령번호 형태여야 합니다.')
                            test = _truth(ev.evaluate(pieces[0]))
                            should_jump = not test if cmd == 'ifzero' else test
                            destination = pieces[1]
                        if should_jump:
                            value = ev.evaluate(destination)
                            if not isinstance(value, int) or not 1 <= value <= len(route.instructions):
                                raise HNLError(f'잘못된 이동 명령 번호: {value}')
                            pc = value - 1
                            continue
                    else:
                        raise HNLError(f'지원하지 않는 명령: {cmd}')
                except HNLError as exc:
                    raise HNLError(f'{inst.line}행: {exc}') from exc
                pc += 1
        return Response(status, content_type, ''.join(parts).encode('utf-8'), headers)

    def dispatch(self, request: Request) -> Response:
        for route in self.routes:
            if request.method not in (route.method, 'HEAD' if route.method == 'GET' else ''):
                continue
            match = route.regex.fullmatch(request.path)
            if match:
                request.params = {k: unquote(v) for k, v in match.groupdict().items()}
                return self._execute(route, request)
        for prefix, root in self.static:
            if request.path == prefix or request.path.startswith(prefix + '/'):
                if request.method not in ('GET', 'HEAD'):
                    return Response(405, CONTENT_TYPES['text'], b'Method Not Allowed', {'Allow': 'GET, HEAD'})
                relative = unquote(request.path[len(prefix):].lstrip('/'))
                if not relative or any(part.startswith('.') for part in Path(relative).parts):
                    return Response(404, CONTENT_TYPES['text'], b'Not Found')
                path = (root / relative).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    return Response(404, CONTENT_TYPES['text'], b'Not Found')
                if path.stat().st_size > MAX_STATIC:
                    return Response(413, CONTENT_TYPES['text'], b'File Too Large')
                content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
                if content_type.startswith('text/') or content_type in ('application/javascript', 'application/json'):
                    content_type += '; charset=utf-8'
                return Response(200, content_type, path.read_bytes(), {'X-Content-Type-Options': 'nosniff'})
        allowed = sorted({r.method for r in self.routes if r.regex.fullmatch(request.path)})
        if allowed:
            if 'GET' in allowed:
                allowed.append('HEAD')
            return Response(405, CONTENT_TYPES['text'], b'Method Not Allowed', {'Allow': ', '.join(allowed)})
        return Response(404, CONTENT_TYPES['text'], b'Not Found')

    def make_handler(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'HNL/0.2'

            def do_GET(self): self._handle()
            def do_HEAD(self): self._handle()
            def do_POST(self): self._handle()
            def do_PUT(self): self._handle()
            def do_PATCH(self): self._handle()
            def do_DELETE(self): self._handle()

            def _handle(self):
                split = urlsplit(self.path)
                try:
                    raw_length = self.headers.get('Content-Length', '0')
                    length = int(raw_length)
                    if length < 0:
                        raise ValueError('invalid Content-Length')
                    if length > MAX_BODY:
                        response = Response(413, CONTENT_TYPES['text'], b'Payload Too Large')
                    else:
                        raw = self.rfile.read(length) if length else b''
                        try:
                            body = raw.decode('utf-8')
                        except UnicodeDecodeError:
                            raise ValueError('body must be UTF-8')
                        content_type = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
                        form = {}
                        data = {}
                        if content_type == 'application/x-www-form-urlencoded':
                            form = {k: v[-1] for k, v in parse_qs(body, keep_blank_values=True).items()}
                        elif content_type == 'application/json' and body:
                            data = json.loads(body)
                            if not isinstance(data, dict):
                                raise ValueError('JSON payload must be an object')
                        req = Request(self.command, unquote(split.path),
                                      {k: v[-1] for k, v in parse_qs(split.query, keep_blank_values=True).items()},
                                      form, data, headers={k.lower(): v for k, v in self.headers.items()}, body=body)
                        try:
                            response = app.dispatch(req)
                        except Exception as exc:
                            print(f'HNL 웹 실행 오류: {exc}', file=sys.stderr)
                            response = Response(500, CONTENT_TYPES['text'], b'Internal Server Error')
                except (ValueError, json.JSONDecodeError):
                    response = Response(400, CONTENT_TYPES['text'], b'Bad Request')
                self.send_response(response.status)
                self.send_header('Content-Type', response.content_type)
                self.send_header('Content-Length', str(len(response.body)))
                self.send_header('X-Content-Type-Options', 'nosniff')
                for key, value in response.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(response.body)

        return Handler


def serve(source: str, *, base_dir: Path | str = '.', host: str | None = None,
          port: int | None = None, max_steps: int = MAX_STEPS) -> None:
    app = WebApplication(source, base_dir=base_dir, max_steps=max_steps)
    bind_host = app.host if host is None else host
    bind_port = app.port if port is None else port
    with ThreadingHTTPServer((bind_host, bind_port), app.make_handler()) as server:
        actual_host, actual_port = server.server_address[:2]
        print(f'요이~ㅋㅋ HNL 웹 서버: http://{actual_host}:{actual_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('\n줴줴이야')
