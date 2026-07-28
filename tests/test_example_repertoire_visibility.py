import pytest
from opening_fenix.core.utils import filter_repertoires_by_build_type, is_example_repertoire

def test_is_example_repertoire():
    assert is_example_repertoire("Tarrasch Example Course") is True
    assert is_example_repertoire("Sicilian Dragon Example Course") is True
    assert is_example_repertoire("Sample Defense") is True
    assert is_example_repertoire("My Custom Sicilian") is False
    assert is_example_repertoire("French Defense") is False

def test_filter_repertoires_in_private_mode(monkeypatch):
    """In Private mode, filter_repertoires_by_build_type should return ALL repertoires (personal + example)."""
    monkeypatch.setattr("opening_fenix.core.utils.is_public_version", lambda: False)
    
    input_repos = ["My Custom Sicilian", "Tarrasch Example Course", "French Defense", "Sicilian Dragon Example Course"]
    filtered = filter_repertoires_by_build_type(input_repos)
    
    assert "My Custom Sicilian" in filtered
    assert "Tarrasch Example Course" in filtered
    assert "French Defense" in filtered
    assert "Sicilian Dragon Example Course" in filtered
    assert len(filtered) == 4

def test_filter_repertoires_in_public_mode(monkeypatch):
    """In Public mode, filter_repertoires_by_build_type should return ONLY example repertoires."""
    monkeypatch.setattr("opening_fenix.core.utils.is_public_version", lambda: True)
    
    input_repos = ["My Custom Sicilian", "Tarrasch Example Course", "French Defense", "Sicilian Dragon Example Course"]
    filtered = filter_repertoires_by_build_type(input_repos)
    
    assert "My Custom Sicilian" not in filtered
    assert "French Defense" not in filtered
    assert "Tarrasch Example Course" in filtered
    assert "Sicilian Dragon Example Course" in filtered
    assert len(filtered) == 2

def test_faq_dialog_donation_hidden_in_private_mode(monkeypatch):
    """Ensure donation FAQ item (buymeacoffee) is omitted in Private mode."""
    monkeypatch.setattr("opening_fenix.core.utils.is_public_version", lambda: False)
    from opening_fenix.gui.dialogs.faq_dialog import get_faq_items
    
    faqs = get_faq_items()
    questions = [q for q, a in faqs]
    answers = [a for q, a in faqs]
    
    assert not any("buymeacoffee" in a for a in answers)
    assert not any("unterstützen" in q.lower() for q in questions)

