"""Unit tests for the checker's pure logic. Run:  python -m pytest -q"""
from agent.verifier import compare, invoice_numbers_from, norm_date, parse_invoice_page, to_float, verify

PAGE = ("<h1>Invoice INV-1004</h1><p>Vendor: Company X</p>\n"
        "<p>Due date: Sep 14, 2026</p><p>Total: $2,450.75</p><p>Status: unpaid</p>")
SOURCE = {"vendor": "Company X", "amount": 2450.75, "due_date": "14-09-2026", "status": "unpaid"}


def test_to_float():
    assert to_float("$2,450.75") == 2450.75
    assert to_float(12) == 12.0
    assert to_float("n/a") is None


def test_norm_date():
    assert norm_date("Sep 14, 2026") == "14-09-2026"
    assert norm_date("14-09-2026") == "14-09-2026"
    assert norm_date("2026-09-14") == "14-09-2026"
    assert norm_date("14/09/2026") is None


def test_parse_invoice_page():
    assert parse_invoice_page(PAGE) == SOURCE
    assert parse_invoice_page("<p>nothing useful</p>") is None


def test_compare_match_and_mismatch():
    good = {"vendor": "Company X", "amount": 2450.75, "due_date": "14-09-2026"}
    assert compare(good, SOURCE) == []
    bad = {"vendor": "Company X", "amount": 2540.75, "due_date": "15-09-2026"}
    assert len(compare(bad, SOURCE)) == 2


def test_invoice_numbers_from_facts():
    assert invoice_numbers_from({"invoice_number": "INV-1004"}) == ["INV-1004"]
    assert invoice_numbers_from({"invoice_numbers": ["INV-1", "INV-1", "INV-2"]}) == ["INV-1", "INV-2"]
    assert invoice_numbers_from({}) == []


def test_verify_unverifiable_without_invoice_number():
    result = verify([], [], {}, expect_write=False)
    assert result["verdict"] == "UNVERIFIABLE"
