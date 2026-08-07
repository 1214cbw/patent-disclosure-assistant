"""A small, dependency-light LaTeX subset to native Word OMML renderer.

The renderer deliberately creates Office Math XML, never images, SVG, or a
plain-text approximation.  It covers the patent-oriented subset exercised by
the PoC and fails loudly for unsupported commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from lxml import etree

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NSMAP = {"m": M}


def q(tag: str) -> str:
    return f"{{{M}}}{tag}"


def el(tag: str, text: str | None = None, **attrs: str) -> etree._Element:
    node = etree.Element(q(tag))
    for key, value in attrs.items():
        node.set(q(key), value)
    if text is not None:
        node.text = text
    return node


def math_arg(children: list[etree._Element] | etree._Element) -> etree._Element:
    node = el("e")
    if isinstance(children, list):
        for child in children:
            node.append(child)
    else:
        node.append(children)
    return node


def run(text: str, *, bold: bool = False, normal: bool = False) -> etree._Element:
    node = el("r")
    if bold or normal:
        props = el("rPr")
        if bold:
            props.append(el("sty", val="b"))
        if normal:
            props.append(el("nor"))
        node.append(props)
    node.append(el("t", text))
    return node


GREEK = {"psi": "ψ", "alpha": "α", "beta": "β", "lambda": "λ", "omega": "ω", "Delta": "Δ"}
SYMBOLS = {"partial": "∂", "sin": "sin", "cos": "cos", "tan": "tan", "to": "→", "ge": "≥", "le": "≤", "leq": "≤", "geq": "≥", "ldots": "…", "cdots": "⋯", "times": "×", "pm": "±", "infty": "∞", "min": "min"}


class LatexParseError(ValueError):
    pass


@dataclass
class Nary:
    char: str
    lower: list[etree._Element] | None = None
    upper: list[etree._Element] | None = None


@dataclass
class Limit:
    lower: list[etree._Element] | None = None


class Parser:
    def __init__(self, source: str):
        self.s = source.replace("\r", "").replace("\n", " ")
        self.i = 0

    def eof(self) -> bool:
        return self.i >= len(self.s)

    def peek(self) -> str:
        return "" if self.eof() else self.s[self.i]

    def take(self) -> str:
        value = self.peek()
        self.i += 1
        return value

    def command(self) -> str:
        if self.take() != "\\":
            raise LatexParseError("Expected LaTeX command")
        start = self.i
        while not self.eof() and self.peek().isalpha():
            self.i += 1
        if start == self.i:
            return self.take()
        return self.s[start:self.i]

    def raw_group(self) -> str:
        if self.take() != "{":
            raise LatexParseError(f"Expected '{{' at character {self.i}")
        start, depth = self.i, 1
        while not self.eof() and depth:
            c = self.take()
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        if depth:
            raise LatexParseError("Unclosed group")
        return self.s[start:self.i - 1]

    def argument(self) -> list[etree._Element]:
        while self.peek().isspace():
            self.take()
        if self.peek() == "{":
            return Parser(self.raw_group()).parse()
        return [self.atom()]

    def parse(self, stop_right: bool = False) -> list[etree._Element]:
        out: list[etree._Element] = []
        while not self.eof():
            if self.peek() == "}" or self.peek() == "&":
                break
            if stop_right and self.s.startswith("\\right", self.i):
                break
            if self.s.startswith("\\\\", self.i):
                break
            if self.peek().isspace():
                self.take()
                continue
            base = self.atom()
            if isinstance(base, Nary):
                # In OMML, the operand belongs inside m:nary/m:e.  Leaving this
                # field empty makes Word display a dotted placeholder box.
                resolved = self.scripts(base)
                operand = self.parse(stop_right=stop_right)
                if not operand:
                    raise LatexParseError("\\sum and \\int require an operand")
                expression = resolved.find(q("e"))
                for child in operand:
                    expression.append(child)
                out.append(resolved)
                break
            resolved = self.scripts(base)
            if isinstance(resolved, list):
                out.extend(resolved)
            else:
                out.append(resolved)
        return out

    def atom(self):
        c = self.peek()
        if c == "{":
            return self.argument()
        if c == "\\":
            command = self.command()
            if command in (",", ";", "!", " ", "quad", "qquad"):
                # Spacing is intentionally not emitted as an empty math run:
                # Word represents that as an editable dotted placeholder.
                return []
            if command == "frac":
                node = el("f")
                num, den = self.argument(), self.argument()
                node.append(self.container("num", num))
                node.append(self.container("den", den))
                return node
            if command == "sqrt":
                node = el("rad")
                props = el("radPr"); props.append(el("degHide", val="1")); node.append(props)
                node.append(el("deg")); node.append(math_arg(self.argument()))
                return node
            if command == "sum":
                return Nary("∑")
            if command == "int":
                return Nary("∫")
            if command == "lim":
                return Limit()
            if command in GREEK:
                return run(GREEK[command])
            if command in SYMBOLS:
                return run(SYMBOLS[command], normal=command in {"sin", "cos", "tan", "min"})
            if command in {"mathbf", "mathrm"}:
                group = self.argument()
                return self.style(group, bold=command == "mathbf", normal=command == "mathrm")
            if command == "left":
                left = self.delimiter()
                inside = self.parse(stop_right=True)
                if not self.s.startswith("\\right", self.i):
                    raise LatexParseError("\\left has no matching \\right")
                self.command()
                right = self.delimiter()
                return self.delimited(inside, left, right)
            if command == "begin":
                environment = self.raw_group()
                return self.environment(environment)
            if command == "right":
                raise LatexParseError("Unexpected \\right")
            raise LatexParseError(f"Unsupported LaTeX command: \\{command}")
        self.take()
        return run(c)

    def scripts(self, base):
        lower = upper = None
        while self.peek() in "_^" and self.peek():
            kind = self.take()
            value = self.argument()
            if kind == "_": lower = value
            else: upper = value
        if lower is None and upper is None:
            return base
        if isinstance(base, Nary):
            base.lower, base.upper = lower, upper
            return self.nary(base)
        if isinstance(base, Limit):
            if lower is None:
                raise LatexParseError("\\lim requires a lower limit")
            node = el("limLow"); node.append(math_arg([run("lim", normal=True)])); node.append(self.container("lim", lower)); return node
        if isinstance(base, list):
            base = math_arg(base)
        if lower is not None and upper is not None:
            node = el("sSubSup"); node.append(math_arg(base)); node.append(self.container("sub", lower)); node.append(self.container("sup", upper)); return node
        node = el("sSub" if lower is not None else "sSup")
        node.append(math_arg(base))
        node.append(self.container("sub" if lower is not None else "sup", lower if lower is not None else upper))
        return node

    @staticmethod
    def container(tag: str, values: list[etree._Element]) -> etree._Element:
        node = el(tag)
        for value in values:
            node.append(value)
        return node

    def style(self, nodes, *, bold: bool, normal: bool):
        styled: list[etree._Element] = []
        for node in nodes:
            if node.tag == q("r"):
                text = node.find(q("t")).text or ""
                styled.append(run(text, bold=bold, normal=normal))
            else:
                styled.append(node)
        return styled

    def delimiter(self) -> str:
        if self.peek() == "\\":
            return {"{": "{", "}": "}"}.get(self.command(), "")
        return self.take()

    def delimited(self, inside, left: str, right: str):
        node = el("d")
        props = el("dPr"); props.append(el("begChr", val=left)); props.append(el("endChr", val=right)); node.append(props)
        node.append(math_arg(inside)); return node

    def environment(self, name: str):
        end = f"\\end{{{name}}}"
        position = self.s.find(end, self.i)
        if position < 0:
            raise LatexParseError(f"Environment {name} has no end marker")
        body, self.i = self.s[self.i:position], position + len(end)
        rows = body.split("\\\\")
        parsed_rows: list[list[list[etree._Element]]] = []
        for raw_row in rows:
            parsed_rows.append([Parser(cell.strip()).parse() for cell in raw_row.split("&")])
        matrix = el("m")
        for cells in parsed_rows:
            row = el("mr")
            for cell in cells:
                row.append(math_arg(cell))
            matrix.append(row)
        if name == "bmatrix":
            return self.delimited([matrix], "[", "]")
        if name == "cases":
            return self.delimited([matrix], "{", "")
        raise LatexParseError(f"Unsupported environment: {name}")

    def nary(self, value: Nary):
        node = el("nary")
        props = el("naryPr"); props.append(el("chr", val=value.char)); props.append(el("limLoc", val="undOvr")); node.append(props)
        node.append(self.container("sub", value.lower or [])); node.append(self.container("sup", value.upper or [])); node.append(el("e"))
        return node


def latex_to_omml(latex: str, *, display: bool = False) -> etree._Element:
    """Convert a supported LaTeX expression into an ``m:oMath`` element."""
    parser = Parser(latex)
    children = parser.parse()
    if not parser.eof():
        raise LatexParseError(f"Unparsed input at character {parser.i}")
    math = el("oMath")
    for child in children:
        if isinstance(child, list):
            for nested in child: math.append(nested)
        elif isinstance(child, (Nary, Limit)):
            raise LatexParseError("Operator needs an argument or limit")
        else:
            math.append(child)
    if not display:
        return math
    paragraph = el("oMathPara"); paragraph.append(math); return paragraph

