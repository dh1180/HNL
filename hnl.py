"""HanNamLang (HNL): a deliberately awkward, Korean-meme esolang.

This is a standalone interpreter: no Python eval/exec, no third-party packages.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


class HNLError(Exception):
    """Invalid HNL source or a runtime error."""


@dataclass(frozen=True)
class Instruction:
    command: str
    operand: str
    line: int


def parse(source: str) -> list[Instruction]:
    """Validate the ritual boundaries and compile logical source lines."""
    meaningful = [
        (line_no, line.strip())
        for line_no, line in enumerate(source.splitlines(), 1)
        if line.strip() and not line.lstrip().startswith('#')
    ]
    if not meaningful or meaningful[0][1] != '엄.':
        raise HNLError("프로그램 첫 줄은 '엄.'이어야 합니다.")
    if len(meaningful) < 2 or meaningful[-1][1] != '줴줴이야':
        raise HNLError("프로그램 마지막 줄은 '줴줴이야'여야 합니다.")

    instructions: list[Instruction] = []
    for line_no, line in meaningful[1:-1]:
        if line in ('엄.', '줴줴이야'):
            raise HNLError(f'{line_no}행: 시작과 종료 구문은 중간에 올 수 없습니다.')
        match = re.fullmatch(r'엄(~+)(?:\s+(.+))?', line)
        if match:
            instructions.append(Instruction('store:' + str(len(match.group(1))), match.group(2) or '', line_no))
            continue
        if line.startswith('요이~ㅋㅋㅋㅋ') and line == '요이~ㅋㅋㅋㅋ':
            instructions.append(Instruction('newline', '', line_no))
            continue
        if line.startswith('요이~ㅋㅋㅋ') and line[len('요이~ㅋㅋㅋ'):].startswith(' '):
            instructions.append(Instruction('char', line[len('요이~ㅋㅋㅋ'):].strip(), line_no))
            continue
        if line.startswith('요이~ㅋㅋ') and line[len('요이~ㅋㅋ'):].startswith(' '):
            instructions.append(Instruction('number', line[len('요이~ㅋㅋ'):].strip(), line_no))
            continue
        if line.startswith('티~원 '):
            instructions.append(Instruction('goto', line[len('티~원 '):].strip(), line_no))
            continue
        for prefix, command in (('예에에? ', 'ifzero'), ('아뇨아뇨아뇨 ', 'ifnotzero')):
            if line.startswith(prefix):
                instructions.append(Instruction(command, line[len(prefix):].strip(), line_no))
                break
        else:
            raise HNLError(f'{line_no}행: 이게 무슨 말이야? 알 수 없는 명령어: {line!r}')
    return instructions


def evaluate(expression: str, registers: dict[int, int], stdin: TextIO) -> int:
    """Space separates additions, ~ separates multiplication, and no digits exist."""
    if not expression:
        return 0
    total = 0
    for product in expression.split():
        factors = product.split('~')
        if any(not factor for factor in factors):
            raise HNLError(f'잘못된 곱셈식: {product!r}')
        value = 1
        for factor in factors:
            if re.fullmatch(r'[ㅋㅠ]+', factor):
                atom = factor.count('ㅋ') - factor.count('ㅠ')
            elif re.fullmatch(r'어+', factor):
                atom = registers.get(len(factor), 0)
            elif factor == '예에에!':
                raw = stdin.readline()
                if not raw:
                    raise HNLError('입력값이 없습니다. 예에에!')
                try:
                    atom = int(raw.strip())
                except ValueError as exc:
                    raise HNLError('정수를 입력해야 합니다. 예에에!') from exc
            else:
                raise HNLError(f'잘못된 값: {factor!r}')
            value *= atom
        total += value
    return total


def run(
    source: str,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    max_steps: int = 1_000_000,
) -> dict[int, int]:
    """Execute HNL and return final registers (1-based, initially all zero)."""
    if max_steps < 1:
        raise ValueError('max_steps must be positive')
    inputs = stdin if stdin is not None else sys.stdin
    outputs = stdout if stdout is not None else sys.stdout
    instructions = parse(source)
    registers: dict[int, int] = {}
    ip = 0
    steps = 0
    while ip < len(instructions):
        instruction = instructions[ip]
        steps += 1
        if steps > max_steps:
            raise HNLError(f'{instruction.line}행: 실행 제한({max_steps}단계) 초과. 무한 반복인가요?')
        command, operand = instruction.command, instruction.operand
        try:
            if command.startswith('store:'):
                index = int(command.partition(':')[2])
                registers[index] = evaluate(operand, registers, inputs)
            elif command == 'number':
                outputs.write(str(evaluate(operand, registers, inputs)))
            elif command == 'char':
                codepoint = evaluate(operand, registers, inputs)
                if not 0 <= codepoint <= 0x10FFFF:
                    raise HNLError(f'유효하지 않은 유니코드 코드 포인트: {codepoint}')
                outputs.write(chr(codepoint))
            elif command == 'newline':
                outputs.write('\n')
            elif command == 'goto':
                target = evaluate(operand, registers, inputs)
                if not 1 <= target <= len(instructions):
                    raise HNLError(f'잘못된 이동 위치: {target} (1~{len(instructions)}만 가능)')
                ip = target - 1
                continue
            elif command in ('ifzero', 'ifnotzero'):
                parts = operand.split(':')
                if len(parts) != 2 or not all(piece.strip() for piece in parts):
                    raise HNLError('조건문은 <값> : <이동할 명령 번호> 형태여야 합니다.')
                test, target_expr = parts
                condition = evaluate(test.strip(), registers, inputs)
                should_jump = condition == 0 if command == 'ifzero' else condition != 0
                if should_jump:
                    target = evaluate(target_expr.strip(), registers, inputs)
                    if not 1 <= target <= len(instructions):
                        raise HNLError(f'잘못된 이동 위치: {target} (1~{len(instructions)}만 가능)')
                    ip = target - 1
                    continue
            else:
                raise HNLError(f'지원하지 않는 명령: {command}')
        except HNLError as exc:
            raise HNLError(f'{instruction.line}행: {exc}') from exc
        ip += 1
    return registers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='HanNamLang v0.1 - 요이~ㅋㅋ')
    parser.add_argument('file', type=Path, help='실행할 .hnl 소스 파일')
    parser.add_argument('--max-steps', type=int, default=None, help='무한 반복 방지 명령 횟수')
    parser.add_argument('--host', default=None, help='웹 서버 바인딩 주소 덮어쓰기 (기본 127.0.0.1)')
    parser.add_argument('--port', type=int, default=None, help='웹 서버 포트 덮어쓰기')
    args = parser.parse_args(argv)
    try:
        source = args.file.read_text(encoding='utf-8-sig')
        if any(line.strip().startswith('동탄어?준 ') for line in source.splitlines()):
            from hnl_web import HNLError as WebHNLError, serve
            try:
                serve(source, base_dir=args.file.resolve().parent, host=args.host, port=args.port,
                      max_steps=args.max_steps if args.max_steps is not None else 20_000)
            except WebHNLError as exc:
                raise HNLError(str(exc)) from exc
        else:
            run(source, max_steps=args.max_steps if args.max_steps is not None else 1_000_000)
    except (HNLError, OSError, UnicodeError, ValueError) as exc:
        print(f'HNL 오류: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
