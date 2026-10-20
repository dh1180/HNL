"""Web parser and live HTTP tests for HNL."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from hnl import HNLError
from hnl_web import Expression, Request, WebApplication, _tokens

BASE = Path(__file__).resolve().parents[1] / 'examples' / 'web'
SOURCE = (BASE / 'site.hnl').read_text(encoding='utf-8')


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.app = WebApplication(SOURCE, base_dir=BASE)

    def test_quoted_string_tokenizer(self):
        self.assertEqual(_tokens('"hello world" 어~!note ㅋㅋ~ㅋㅋ'),
                         ['"hello world"', '어~!note', 'ㅋㅋ', '~', 'ㅋㅋ'])

    def test_string_concat_and_math(self):
        ev = Expression(Request('GET', '/', {}), {1: 4}, {})
        self.assertEqual(ev.evaluate('ㅋㅋ~ㅋㅋㅋ ㅠ'), 5)
        self.assertEqual(ev.evaluate('"yo " 어'), 'yo 4')
        self.assertEqual(ev.evaluate('"a"~ㅋㅋㅋ'), 'aaa')

    def test_quoted_literal_does_not_exec(self):
        ev = Expression(Request('GET', '/', {}), {}, {})
        with self.assertRaises(HNLError):
            ev.evaluate('__import__("os").system("id")')

    def test_invalid_source(self):
        for source in ('엄.\n동탄어?준 8080\n티~원 GET /\n줴줴이야',
                       '엄.\n동탄어?준 8080\n티~원 GET /\n식어어ㅋ\n티~원 GET /\n식어어ㅋ\n줴줴이야',
                       '엄.\n동탄어?준 8080\n티~원 정적 /assets ../outside\n줴줴이야'):
            with self.subTest(source=source), self.assertRaises(HNLError):
                WebApplication(source, base_dir=BASE)

    def test_path_param_html_escapes(self):
        r = self.app.dispatch(Request('GET', '/hello/%3Cscript%3E', {}))
        self.assertEqual(r.status, 200)
        self.assertIn(b'&lt;script&gt;', r.body)
        self.assertNotIn(b'<script>', r.body)

    def test_home_page(self):
        r = self.app.dispatch(Request('GET', '/', {}))
        self.assertEqual(r.status, 200)
        self.assertIn('text/html', r.content_type)
        self.assertIn('방명록', r.body.decode())

    def test_form_and_global_state_html_escaping(self):
        self.app.dispatch(Request('POST', '/note', {}, form={'message': '<img src=x onerror=alert(1)>'}))
        home = self.app.dispatch(Request('GET', '/', {}))
        self.assertIn(b'&lt;img', home.body)
        self.assertNotIn(b'<img src=x', home.body)

    def test_counter_increments_atomically(self):
        self.assertEqual(json.loads(self.app.dispatch(Request('GET', '/api/visits', {})).body)['visits'], 1)
        self.assertEqual(json.loads(self.app.dispatch(Request('GET', '/api/visits', {})).body)['visits'], 2)

    def test_json_response_escapes_user_data(self):
        r = self.app.dispatch(Request('POST', '/api/echo', {}, json_data={'message': '안녕 "\\hi\n'}))
        self.assertEqual(json.loads(r.body)['message'], '안녕 "\\hi\n')

    def test_static_assets(self):
        r = self.app.dispatch(Request('GET', '/assets/style.css', {}))
        self.assertEqual(r.status, 200)
        self.assertIn(b'font-family', r.body)
        js = self.app.dispatch(Request('GET', '/assets/app.js', {}))
        self.assertIn('javascript', js.content_type)

    def test_deny_static_traversal_and_dotfiles(self):
        for path in ('/assets/../site.hnl', '/assets/.env', '/assets/%2e%2e/site.hnl'):
            with self.subTest(path=path):
                self.assertEqual(self.app.dispatch(Request('GET', path, {})).status, 404)

    def test_not_found_and_method_not_allowed(self):
        self.assertEqual(self.app.dispatch(Request('GET', '/missing', {})).status, 404)
        r = self.app.dispatch(Request('POST', '/hello/someone', {}))
        self.assertEqual(r.status, 405)
        self.assertIn('GET', r.headers['Allow'])

    def test_condition_and_response_status(self):
        source = "\n".join([
            '엄.', '동탄어?준 8080', '티~원 GET /status',
            '아뇨아뇨아뇨! text', '예에에! 201',
            '엄~ 동탄어?준.query.value',
            '예에에? 어 : ㅋㅋㅋㅋㅋㅋ',
            '요이~ㅋㅋ "yes"', '요이~ㅋㅋ "no"',
            '식어어ㅋ', '줴줴이야',
        ])
        app = WebApplication(source, base_dir=BASE)
        r = app.dispatch(Request('GET', '/status', {'value': ''}))
        self.assertEqual(r.status, 201)
        self.assertEqual(r.body, b'no')

    def test_step_limit(self):
        source = '엄.\n동탄어?준 8080\n티~원 GET /\n티~원 ㅋ\n식어어ㅋ\n줴줴이야'
        app = WebApplication(source, base_dir=BASE, max_steps=5)
        with self.assertRaisesRegex(HNLError, '제한 초과'):
            app.dispatch(Request('GET', '/', {}))


class LiveHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = WebApplication(SOURCE, base_dir=BASE)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), cls.app.make_handler())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_http_page(self):
        with urlopen(self.url + '/') as r:
            self.assertEqual(r.status, 200)
            self.assertIn('방명록', r.read().decode())

    def test_http_api_and_query(self):
        with urlopen(self.url + '/hello/A%26B?foo=bar') as r:
            self.assertIn('A&amp;B', r.read().decode())
        request = URLRequest(self.url + '/api/echo', data=json.dumps({'message': '요이~ㅋㅋ'}).encode(),
                             headers={'Content-Type': 'application/json'})
        with urlopen(request) as r:
            self.assertEqual(json.load(r)['message'], '요이~ㅋㅋ')

    def test_http_post_form_and_redirect(self):
        request = URLRequest(self.url + '/note', data=urlencode({'message': '엄!'}).encode(), method='POST')
        with urlopen(request) as r:
            self.assertEqual(r.status, 200)
            self.assertIn('엄!', r.read().decode())

    def test_http_bad_json(self):
        request = URLRequest(self.url + '/api/echo', data=b'not json',
                             headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request)
        self.assertEqual(ctx.exception.code, 400)

    def test_http_no_directory_traversal(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.url + '/assets/%2e%2e/site.hnl')
        self.assertEqual(ctx.exception.code, 404)

    def test_http_head(self):
        request = URLRequest(self.url + '/', method='HEAD')
        with urlopen(request) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), b'')

    def test_http_payload_limit(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.putrequest('POST', '/api/echo')
            connection.putheader('Content-Length', str(1024 * 1024 + 1))
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
