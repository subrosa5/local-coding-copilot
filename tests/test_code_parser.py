from local_coding_copilot.code.parser import parse_python_file


def test_tree_sitter_extracts_classes_functions_and_methods() -> None:
    content = (
        "class Engine:\n"
        "    def match(self):\n"
        "        return True\n"
        "\n"
        "def calculate_fee(notional):\n"
        "    return notional * 0.01\n"
    )

    chunks = parse_python_file("project", "repo", "engine.py", content, "sha", "abc")

    assert [(chunk.symbol, chunk.symbol_kind) for chunk in chunks] == [
        ("Engine", "class"),
        ("Engine.match", "method"),
        ("calculate_fee", "function"),
    ]
    function = chunks[-1]
    assert function.start_line == 5
    assert function.end_line == 6
    assert function.content.startswith("def calculate_fee")
    assert function.commit_sha == "abc"


def test_python_file_without_symbols_has_file_chunk() -> None:
    chunks = parse_python_file(
        "project", "repo", "settings.py", "MAX_LIMIT = 100\n", "sha", "abc"
    )

    assert len(chunks) == 1
    assert chunks[0].symbol is None
    assert chunks[0].symbol_kind == "file"
    assert chunks[0].content == "MAX_LIMIT = 100\n"
