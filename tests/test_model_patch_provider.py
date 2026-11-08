import pytest

from local_coding_copilot.coding.models import CodingTask
from local_coding_copilot.coding.patches import ModelPatchProvider
from local_coding_copilot.coding.worktree import (
    PatchRejectedError,
    validate_unified_diff,
)
from local_coding_copilot.models import ChatRequest, ChatResponse, ToolCall

VALID_PATCH = """diff --git a/src/example.py b/src/example.py
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-return False
+return True
"""


class StubLLM:
    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.request: ChatRequest | None = None

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.request = request
        return self.response


def test_model_patch_provider_requests_raw_diff_and_includes_rag_context() -> None:
    llm = StubLLM(ChatResponse(content=VALID_PATCH))
    provider = ModelPatchProvider(llm)
    patch = provider.propose_patch(
        CodingTask(
            "repair",
            "Fix the exact boundary.",
            context=("src/example.py:1-1@abc\nreturn False",),
            context_commit_sha="abc",
        ),
        0,
        (),
    )

    assert patch == VALID_PATCH
    assert llm.request is not None
    assert llm.request.temperature == 0.0
    content = llm.request.messages[1].content
    assert "Fix the exact boundary" in content
    assert "return False" in content
    assert "@abc" in content


@pytest.mark.parametrize(
    "content",
    [
        "Here is the patch:\n" + VALID_PATCH,
        "```diff\n" + VALID_PATCH + "```",
        "",
    ],
)
def test_model_patch_provider_rejects_non_raw_diff(content: str) -> None:
    provider = ModelPatchProvider(StubLLM(ChatResponse(content=content)))
    with pytest.raises(PatchRejectedError):
        provider.propose_patch(CodingTask("repair", "Fix it"), 0, ())


def test_model_patch_provider_rejects_tool_calls() -> None:
    provider = ModelPatchProvider(
        StubLLM(ChatResponse(content=VALID_PATCH, tool_calls=(ToolCall("exec", {}),)))
    )
    with pytest.raises(PatchRejectedError, match="tool calls"):
        provider.propose_patch(CodingTask("repair", "Fix it"), 0, ())


@pytest.mark.parametrize(
    "patch",
    [
        VALID_PATCH.replace("src/example.py", "../../outside.py"),
        VALID_PATCH + "GIT binary patch\n",
        VALID_PATCH.replace("diff --git", "diff --git", 1).replace(
            "@@ -1 +1 @@", "new file mode 100644\n@@ -1 +1 @@"
        ),
        VALID_PATCH.replace("src/example.py", "src/../secret.py"),
        VALID_PATCH.replace(
            "diff --git a/src/example.py b/src/example.py", "not a diff"
        ),
    ],
)
def test_unified_diff_validator_rejects_unsafe_or_malformed_patch(patch: str) -> None:
    with pytest.raises(PatchRejectedError):
        validate_unified_diff(patch)


def test_unified_diff_validator_accepts_normal_patch() -> None:
    assert validate_unified_diff(VALID_PATCH) == ("src/example.py",)
