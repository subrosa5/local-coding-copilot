import tree_sitter_python
from tree_sitter import Language, Node, Parser

from local_coding_copilot.code.models import CodeChunk

_PYTHON_LANGUAGE = Language(tree_sitter_python.language())


def parse_python_file(
    project_id: str,
    repository: str,
    path: str,
    content: str,
    content_sha256: str,
    commit_sha: str,
) -> tuple[CodeChunk, ...]:
    source = content.encode()
    tree = Parser(_PYTHON_LANGUAGE).parse(source)
    chunks = []

    def add_chunk(node: Node, symbol: str, kind: str) -> None:
        start_line = node.start_point[0] + 1
        chunks.append(
            CodeChunk(
                chunk_id=(f"{project_id}:{repository}:{path}:{symbol}:{start_line}"),
                project_id=project_id,
                repository=repository,
                path=path,
                content_sha256=content_sha256,
                symbol=symbol,
                symbol_kind=kind,
                start_line=start_line,
                end_line=node.end_point[0] + 1,
                content=source[node.start_byte : node.end_byte].decode(),
                commit_sha=commit_sha,
            )
        )

    def visit(node: Node, containing_class: str | None = None) -> None:
        for child in node.named_children:
            if child.type == "class_definition":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = source[name_node.start_byte : name_node.end_byte].decode()
                qualified_name = (
                    f"{containing_class}.{name}" if containing_class else name
                )
                add_chunk(child, qualified_name, "class")
                visit(child, qualified_name)
            elif child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = source[name_node.start_byte : name_node.end_byte].decode()
                qualified_name = (
                    f"{containing_class}.{name}" if containing_class else name
                )
                kind = "method" if containing_class else "function"
                add_chunk(child, qualified_name, kind)
                visit(child, containing_class)
            else:
                visit(child, containing_class)

    visit(tree.root_node)
    if not chunks and content.strip():
        chunks.append(
            CodeChunk(
                chunk_id=f"{project_id}:{repository}:{path}:<file>:1",
                project_id=project_id,
                repository=repository,
                path=path,
                content_sha256=content_sha256,
                symbol=None,
                symbol_kind="file",
                start_line=1,
                end_line=len(content.splitlines()),
                content=content,
                commit_sha=commit_sha,
            )
        )
    return tuple(chunks)
