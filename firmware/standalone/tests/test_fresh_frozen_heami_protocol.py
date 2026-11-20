"""Freeze before testing fresh synth files; no CI generates private audio."""

import json
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"


@pytest.fixture
def mods(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    import evaluate_fresh_frozen_heami as eval_fresh
    import generate_fresh_heami_holdout as synth

    return synth, eval_fresh


def test_fresh_plan_does_not_overlap_training_rates_or_labels(mods):
    synth, _ = mods
    rows = synth.NEW_HELDOUT
    assert len(rows) == 16
    assert sum(label == "wake" for label, _, _ in rows) == 4
    assert sum(label == "nonwake" for label, _, _ in rows) == 12
    training_rates = {0, -3, -2, -1, 1, 2}
    for label, phrase, rate in rows:
        assert phrase == "조수야" if label == "wake" else phrase != "조수야"
        if label == "wake":
            assert rate not in training_rates


def test_frozen_recipe_digest_is_constant(mods):
    _, eval_fresh = mods
    assert eval_fresh.FROZEN_CANDIDATE_SHA256 == (
        "b0231cbe83f5dccdb0adc129ccb4ec899f410abcb83d50007c51247a3b7f7aec"
    )


def test_sealed_output_parser_rejects_wrong_denominator(mods):
    _, eval_fresh = mods
    reply = (
        "UNVERIFIED_USER_LABELED_WAKE_EVALUATION\npositive_accepted=3/4\nnegative_accepted=2/12\n"
    )
    parsed = eval_fresh._read_evaluation(reply)
    assert parsed["wake"] == {"accepted": 3, "total": 4}
    assert parsed["nonwake"] == {"accepted": 2, "total": 12}
    with pytest.raises(eval_fresh.HoldoutRejected):
        eval_fresh._read_evaluation(reply.replace("3/4", "3/3"))
    with pytest.raises(eval_fresh.HoldoutRejected):
        eval_fresh._read_evaluation(reply.replace("2/12", "13/12"))


def test_evaluation_requires_only_sealed_role(mods, tmp_path):
    _, eval_fresh = mods
    manifest = tmp_path / "private.wake-corpus.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "stackchan-private-wake-corpus-v1",
                "samples": [
                    {
                        "id": "bad",
                        "stage": "enrollment",
                        "label": "wake",
                        "session": "s",
                        "file": "missing.wav",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(eval_fresh.HoldoutRejected):
        eval_fresh.load_new_holdout(manifest)
