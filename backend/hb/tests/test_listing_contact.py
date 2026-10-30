"""hb/listing_contact — the listing side parsed out of `listings.raw` (docs/07 §Listings)."""

from hb import listing_contact
from hb.listing_contact import digits, from_raw, normalize_phones


def _raw(**over):
    r = {
        "agent_name": "Jane Lister",
        "agent_email": "jlister@example.com",
        "agent_phones": [
            {"ext": None, "primary": True, "type": "Mobile", "number": "6505550123"},
            {"ext": None, "primary": False, "type": "Fax", "number": "6500000000"},
        ],
        "agent_mls_set": "A-TEST-00000001",
        "agent_nrds_id": "123456789",
        "office_name": "Example Realty Group",
        "office_email": "office@example.com",
        "office_phones": [{"number": "(650) 555-0177", "type": "Office", "primary": True, "ext": None}],
        "broker_name": "Example Realty Group - Broker",
        "mls": "SJCA",
        "mls_id": "ML81000001",
    }
    r.update(over)
    return r


def test_no_advertiser_means_none():
    assert from_raw(None) is None
    assert from_raw({}) is None
    # a broker alone is not someone you can call
    assert from_raw({"broker_name": "Compass - Broker"}) is None
    # whitespace-only names are padding, not a name
    assert from_raw({"agent_name": " ", "office_name": ""}) is None


def test_full_record_shape():
    side = from_raw(_raw())
    assert side["agent"] == {
        "name": "Jane Lister",
        "email": "jlister@example.com",
        "phones": [{"number": "6505550123", "type": "mobile", "primary": True, "sms": True}],
        "mls_id": "A-TEST-00000001",
        "nrds_id": "123456789",
    }
    assert side["office"]["name"] == "Example Realty Group"
    assert side["office"]["phones"] == [
        {"number": "6505550177", "type": "office", "primary": True, "sms": False}
    ]
    assert side["broker"] == {"name": "Example Realty Group - Broker"}
    assert side["builder"] is None
    assert side["mls"] == {"system": "SJCA", "id": "ML81000001"}


def test_office_only_record_has_no_agent():
    side = from_raw(_raw(agent_name=None, agent_email=None, agent_phones=None))
    assert side["agent"] is None
    assert side["office"]["name"] == "Example Realty Group"


def test_builder_surfaces_for_new_construction():
    side = from_raw(_raw(builder_name="Taylor Morrison"))
    assert side["builder"] == {"name": "Taylor Morrison"}


def test_digits_normalizes_us_numbers():
    assert digits("(650) 555-0177") == "6505550177"
    assert digits("+1 650 555 0123") == "6505550123"
    assert digits(6505550123) == "6505550123"
    assert digits("") is None
    assert digits(None) is None
    assert digits("12345") is None  # not a dialable number


def test_phone_type_mapping_covers_the_live_labels():
    def kind(label):
        return normalize_phones([{"number": "6505550100", "type": label}])[0]["type"]
    assert kind("BUSINESS_MOBILE") == "mobile"
    assert kind("Cell") == "mobile"
    assert kind("office") == "office"
    assert kind("Home Office") == "office"
    assert kind("PERSONAL_PHONE") == "home"
    assert kind("tfn") == "toll_free"
    assert kind("Toll Free") == "toll_free"
    assert kind(None) == "other"
    assert kind("Pager") == "other"
    assert set(listing_contact.PHONE_TYPES.values()) <= {
        "mobile", "office", "home", "toll_free", "fax"}


def test_fax_and_junk_dropped_and_ordering():
    phones = normalize_phones([
        {"number": "6505550001", "type": "Office", "primary": False},
        {"number": "6505550002", "type": "Fax", "primary": True},
        {"number": "6505550003", "type": "Mobile", "primary": False},
        {"number": "", "type": "Mobile"},
        {"number": "6505550004", "type": "Home", "primary": True},
        "not a dict",
    ])
    # primary first, then mobile before office before home
    assert [p["number"] for p in phones] == ["6505550004", "6505550003", "6505550001"]
    assert all(p["type"] != "fax" for p in phones)


def test_duplicate_numbers_collapse_to_first():
    phones = normalize_phones([
        {"number": "650-555-0100", "type": "Mobile", "primary": True},
        {"number": "(650) 555-0100", "type": "Office", "primary": False},
    ])
    assert phones == [{"number": "6505550100", "type": "mobile", "primary": True, "sms": True}]


def test_repr_string_is_not_a_second_format():
    # the scan used to str() the list; the migration rewrote those rows, and this
    # reader deliberately does not parse the repr form — no dual read
    side = from_raw(_raw(agent_phones="[{'number': '6505550123', 'type': 'Mobile'}]"))
    assert side["agent"]["phones"] == []
