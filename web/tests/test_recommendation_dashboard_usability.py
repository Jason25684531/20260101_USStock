from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "web" / "templates" / "index.html"


def test_recommendation_table_uses_core_default_columns():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="recBody"' in template
    assert "Source" in template
    assert "Reasons" in template
    assert "Risk Flags" in template
    assert 'colspan="14"' in template


def test_recommendation_advanced_flags_are_in_detail_row():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "rec-advanced-flags" in template
    assert "breakout_pass" in template
    assert "sector_rotation_pass" in template
    assert "advancedFlags" in template


def test_recommendation_reasons_are_bounded_and_provider_source_visible():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "boundedReasons" in template
    assert ".slice(0, 3)" in template
    assert "recommendationSource" in template
    assert "providerIncident" in template
