import io
import unittest
from pathlib import Path

from hnl import HNLError, evaluate, parse, run


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def output(source: str, user_input: str = '', *, max_steps: int = 1000) -> str:
    sink = io.StringIO()
    run(source, stdin=io.StringIO(user_input), stdout=sink, max_steps=max_steps)
    return sink.getvalue()


class HNLTests(unittest.TestCase):
    def test_hello_world(self):
        self.assertEqual(output((EXAMPLES / 'hello.hnl').read_text(encoding='utf-8')), 'Hello, World!\n')

    def test_countdown(self):
        self.assertEqual(output((EXAMPLES / 'countdown.hnl').read_text(encoding='utf-8')), '54321\n')

    def test_input_zero_branch(self):
        source = (EXAMPLES / 'input.hnl').read_text(encoding='utf-8')
        self.assertEqual(output(source, '0\n'), '0\n')
        self.assertEqual(output(source, '3\n'), '3\n')

    def test_expression(self):
        self.assertEqual(evaluate('ㅋㅋㅋ~ㅋㅋ ㅠ 어어', {2: 7}, io.StringIO()), 12)
        self.assertEqual(evaluate('ㅋㅠ', {}, io.StringIO()), 0)
        self.assertEqual(evaluate('어어어', {}, io.StringIO()), 0)

    def test_variable_assignment(self):
        source = '엄.\n엄~~ ㅋㅋㅋㅋ\n요이~ㅋㅋ 어어\n줴줴이야'
        self.assertEqual(output(source), '4')

    def test_invalid_boundaries(self):
        for source in ('요이~ㅋㅋ ㅋ\n줴줴이야', '엄.\n요이~ㅋㅋ ㅋ'):
            with self.subTest(source=source), self.assertRaises(HNLError):
                parse(source)

    def test_unknown_instruction(self):
        with self.assertRaisesRegex(HNLError, '알 수 없는 명령어'):
            parse('엄.\npython print(1)\n줴줴이야')

    def test_unary_operators(self):
        self.assertEqual(output('엄.\n요이~ㅋㅋ ㅋㅋㅋ~ㅋㅋㅋㅋ ㅠㅠ\n줴줴이야'), '10')

    def test_ifzero(self):
        src = '엄.\n엄~ ㅋㅠ\n예에에? 어 : ㅋㅋㅋㅋ\n요이~ㅋㅋ ㅋㅋㅋㅋ\n요이~ㅋㅋ ㅋ\n줴줴이야'
        self.assertEqual(output(src), '1')

    def test_goto_invalid_target(self):
        with self.assertRaisesRegex(HNLError, '잘못된 이동 위치'):
            output('엄.\n티~원 ㅋㅋㅋㅋㅋ\n줴줴이야')

    def test_step_limit(self):
        with self.assertRaisesRegex(HNLError, '실행 제한'):
            output('엄.\n티~원 ㅋ\n줴줴이야', max_steps=5)

    def test_missing_input(self):
        with self.assertRaisesRegex(HNLError, '입력값이 없습니다'):
            output('엄.\n엄~ 예에에!\n줴줴이야'.replace('예에에!', '예에에!'))

    def test_bad_unicode(self):
        with self.assertRaisesRegex(HNLError, '유효하지 않은'):
            output('엄.\n요이~ㅋㅋㅋ ㅠ\n줴줴이야')


if __name__ == '__main__':
    unittest.main()
