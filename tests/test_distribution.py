from api.distribution import build_test_distribution


def test_build_test_distribution_composes_dry_run_messages_and_audit_payload():
    preview = {
        "customer": {"company": "Biniris", "contact_name": "Matthew King"},
        "register": {"title": "Chemical Register", "date": "2026-07-01"},
        "products": [
            {
                "code": "ALLPURP5L",
                "name": "All Purpose Sanitiser Soak",
                "sds": {"matched": True, "url": "https://ccs.example.test/api/documents/source/allpurp.pdf"},
                "risk_assessment": {"matched": False, "url": None},
            }
        ],
    }

    result = build_test_distribution(
        preview=preview,
        contacts=[{"name": "Test Contact", "email": "test@example.com"}],
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["summary"]["contacts"] == 1
    assert result["summary"]["products"] == 1
    assert result["messages"][0]["to"] == "test@example.com"
    assert "All Purpose Sanitiser Soak" in result["messages"][0]["subject"]
    assert "https://ccs.example.test/api/documents/source/allpurp.pdf" in result["messages"][0]["html"]
    assert result["audit_events"][0]["event_type"] == "dry_run_email_prepared"
