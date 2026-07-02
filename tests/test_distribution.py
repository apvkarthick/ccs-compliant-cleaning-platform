from api.distribution import (
    build_test_distribution,
    contact_matches_product,
    distribution_rows_for_supabase,
    tag_slug_for_chemical,
    tracking_signature,
    tracking_url,
)


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


def test_contact_matches_product_from_custom_fields_or_tags():
    contact = {
        "customFields": [
            {"id": "products_used", "value": ["Neutral Floor Cleaner", "Bleach 4%"]},
        ],
        "tags": ["childcare", "msds_all_purpose_sanitiser_soak"],
    }

    assert contact_matches_product(contact, "Neutral Floor Cleaner") is True
    assert contact_matches_product(contact, "All Purpose Sanitiser Soak") is True
    assert contact_matches_product(contact, "Laundry Powder") is False


def test_tracking_url_uses_hmac_signature_and_safe_slug():
    sig = tracking_signature("doc-123", "contact-456", "secret")
    url = tracking_url(
        public_base_url="https://ccs.example.test",
        document_id="doc-123",
        contact_id="contact-456",
        chemical_name="Floor & Surface Cleaner",
        redirect_url="https://files.example.test/sds.pdf",
        secret="secret",
    )

    assert sig == "28bce41a4afc3423"
    assert tag_slug_for_chemical("Floor & Surface Cleaner") == "msds_floor_surface_cleaner"
    assert "doc=doc-123" in url
    assert "contact=contact-456" in url
    assert "sig=28bce41a4afc3423" in url
    assert "chem=Floor+%26+Surface+Cleaner" in url
    assert "redirect=https%3A%2F%2Ffiles.example.test%2Fsds.pdf" in url


def test_distribution_rows_skip_non_uuid_document_ids_for_ccs_distributions():
    messages = [
        {
            "to": "test@example.com",
            "contact_id": "contact-123",
            "documents": [
                {"document_id": "TESTPDF001"},
                {"document_id": "b7ee7fb1-bb38-463f-97e6-f71634bb93d1"},
            ],
        }
    ]

    rows = distribution_rows_for_supabase(messages, dry_run=False, table="ccs_distributions")

    assert rows == [
        {
            "document_id": "b7ee7fb1-bb38-463f-97e6-f71634bb93d1",
            "customer_email": "test@example.com",
            "ghl_contact_id": "contact-123",
            "status": "sent",
        }
    ]
