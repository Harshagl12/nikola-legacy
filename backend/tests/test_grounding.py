from backend.capabilities import EVIDENCE_UNAVAILABLE
from backend.grounding import verify_answer
from backend.network_policy import is_local_url


def test_grounding_removes_unsupported_claims():
    answer, result = verify_answer(
        "Nikola uses ChromaDB for retrieval. The moon is made of cheese.",
        ["Nikola uses ChromaDB for local retrieval."],
    )
    assert answer == "Nikola uses ChromaDB for retrieval."
    assert result["supported"] is False
    assert result["rejected_claims"] == 1


def test_grounding_refuses_when_no_claim_is_supported():
    answer, result = verify_answer("The moon is made of cheese.", ["Nikola uses local retrieval."])
    assert answer == EVIDENCE_UNAVAILABLE
    assert result["supported"] is False


def test_offline_network_policy_allows_loopback_only():
    assert is_local_url("http://127.0.0.1:8080/v1")
    assert is_local_url("http://localhost:8000")
    assert not is_local_url("https://example.com/api")
