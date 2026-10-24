from sandbox_analyst.agent.codeparse import extract_code


def test_extracts_code_from_a_single_python_block():
    reply = 'Here is the script:\n```python\nprint("hi")\n```\nDone.'
    assert extract_code(reply) == 'print("hi")'


def test_extracts_multiline_code():
    reply = "```python\nimport pandas as pd\ndf = pd.read_csv('x')\nprint(df)\n```"
    assert extract_code(reply) == "import pandas as pd\ndf = pd.read_csv('x')\nprint(df)"


def test_returns_none_when_no_code_block_present():
    assert extract_code("I think the answer is 42.") is None


def test_returns_none_for_a_non_python_fenced_block():
    reply = "```text\nnot code\n```"
    assert extract_code(reply) is None


def test_only_the_first_python_block_is_used_when_multiple_are_present():
    reply = "```python\nprint('first')\n```\nand also\n```python\nprint('second')\n```"
    assert extract_code(reply) == "print('first')"


def test_trailing_blank_lines_inside_the_block_are_stripped():
    reply = "```python\nprint(1)\n\n\n```"
    assert extract_code(reply) == "print(1)"


def test_leading_and_trailing_prose_around_the_block_is_ignored():
    reply = "Sure! Here you go:\n\n```python\nx = 1\n```\n\nLet me know if you need anything else."
    assert extract_code(reply) == "x = 1"
