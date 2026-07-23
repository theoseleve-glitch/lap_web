import pytest
from coaching.vocabulary_check import RESOLVABLE_CAUSE_IDS, assert_cause_vocabulary_integrity
from coaching.taxonomy.causes import CauseTaxonomy
from coaching.templates.drills import DRILL_LIBRARY


def _drill_causes() -> set[str]:
    out: set[str] = set()
    for d in DRILL_LIBRARY.values():
        out.update(d.get("applicable_causes", []))
    return out


def test_every_resolvable_cause_is_in_taxonomy_and_drills():
    tax = CauseTaxonomy()
    drill_causes = _drill_causes()
    for cid in RESOLVABLE_CAUSE_IDS:
        assert tax.get_cause(cid) is not None, f"{cid} missing from taxonomy"
        assert cid in drill_causes, f"{cid} missing from DRILL_LIBRARY.applicable_causes"


def test_integrity_assertion_passes():
    assert_cause_vocabulary_integrity()  # must not raise
