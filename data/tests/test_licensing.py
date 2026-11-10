"""DE-08: the licence policy: open-licence SKILL.md files, and the crawl_list label mapping for web pages."""
import pytest
from test_crawler import crawl, site  # noqa: F401  (fixtures: a local HTTP server and a Crawler factory)

from skillforge_data.crawler.run import CrawlTarget, as_target
from skillforge_data.licensing import (
    OPEN_LICENCES,
    check_skill_file_licence,
    detect_licence_text,
    normalise_licence,
    register_skill_file,
    web_page_licence,
)

ALLOWED = ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC0-1.0", "Unlicense", "CC-BY-4.0"]


# ---------------------------------------------------------------------------- (a) SKILL.md files
def test_the_open_list_is_exactly_the_agreed_one():
    assert OPEN_LICENCES == frozenset(ALLOWED)


@pytest.mark.parametrize("licence", ALLOWED)
def test_every_open_licence_is_allowed(licence):
    decision = check_skill_file_licence(licence)
    assert decision.allowed and decision.license == licence


@pytest.mark.parametrize("written", ["mit", "MIT License", "apache license 2.0", "Apache 2.0", "cc0", "the unlicense", "  ISC  "])
def test_common_spellings_are_normalised(written):
    assert check_skill_file_licence(written).allowed


@pytest.mark.parametrize(
    ("licence", "why"),
    [
        ("CC-BY-SA-4.0", "share-alike"), ("CC-BY-SA-3.0", "share-alike"),
        ("GPL-3.0-only", "GPL"), ("GPL-2.0-or-later", "GPL"), ("LGPL-3.0", "GPL"), ("AGPL-3.0-only", "GPL"),
        ("MPL-2.0", "MPL"),
        ("CC-BY-NC-4.0", "non-commercial"), ("CC-BY-NC-SA-4.0", "non-commercial"), ("CC-BY-NC-ND-4.0", "non-commercial"),
        ("CC-BY-ND-4.0", "no-derivatives"),
        ("unknown", "all rights are reserved"), (None, "all rights are reserved"), ("", "all rights are reserved"),
        ("All rights reserved", "all rights are reserved"), ("NOASSERTION", "all rights are reserved"),
        ("bsd", "not on the open-licence list"),
        ("LicenseRef-custom", "not on the open-licence list"), ("EPL-2.0", "not on the open-licence list"),
    ],
)
def test_everything_else_is_refused_with_a_reason(licence, why):
    decision = check_skill_file_licence(licence)
    assert not decision.allowed and why in decision.reason


def test_expressions_or_is_one_open_alternative_and_is_all_open():
    assert check_skill_file_licence("MIT OR Apache-2.0").allowed
    assert check_skill_file_licence("GPL-3.0-only OR MIT").allowed, "the user may choose MIT"
    assert not check_skill_file_licence("GPL-3.0-only OR MPL-2.0").allowed
    assert check_skill_file_licence("MIT AND BSD-3-Clause").allowed
    assert not check_skill_file_licence("MIT AND GPL-3.0-only").allowed
    assert not check_skill_file_licence("(MIT OR Apache-2.0)").allowed
    assert not check_skill_file_licence("GPL-2.0 WITH Classpath-exception-2.0").allowed


def test_normalise_licence():
    assert normalise_licence("mit") == "MIT" and normalise_licence(None) == "unknown" and normalise_licence("Foo-1.0") == "Foo-1.0"


MIT_TEXT = (
    "MIT License\n\nCopyright (c) 2026 X\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\n"
    "of this software"
)


@pytest.mark.parametrize(
    ("text", "spdx"),
    [
        (MIT_TEXT, "MIT"),
        ("Apache License\n                           Version 2.0, January 2004", "Apache-2.0"),
        ("This is free and unencumbered software released into the public domain.", "Unlicense"),
        ("Creative Commons Legal Code\n\nCC0 1.0 Universal", "CC0-1.0"),
        ("Attribution 4.0 International\nCreative Commons Attribution 4.0 International Public License", "CC-BY-4.0"),
        ("Attribution-ShareAlike 4.0 International", "CC-BY-SA-4.0"),
        ("GNU GENERAL PUBLIC LICENSE Version 3", "GPL-3.0-only"),
        ("GNU LESSER GENERAL PUBLIC LICENSE Version 3", "LGPL-3.0-only"),
        ("Mozilla Public License Version 2.0", "MPL-2.0"),
        ("Redistribution and use in source and binary forms, with or without\nmodification, are permitted. Neither the name of X",
         "BSD-3-Clause"),
        ("Redistribution and use in source and binary forms, with or without\nmodification, are permitted.", "BSD-2-Clause"),
        ("Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted",
         "ISC"),
        ("Copyright 2026 Me. Do what you like.", "unknown"),
    ],
)
def test_a_license_file_is_recognised_and_nothing_is_guessed(text, spdx):
    assert detect_licence_text(text) == spdx


def test_a_file_that_mentions_gpl_and_mit_is_read_as_the_stricter_one():
    assert not check_skill_file_licence(detect_licence_text(MIT_TEXT + "\nGNU GENERAL PUBLIC LICENSE")).allowed


def test_register_keeps_url_and_licence_of_an_open_file_and_refuses_the_rest(db):
    url = "https://github.com/acme/skills/blob/main/review/SKILL.md"
    decision, record = register_skill_file(db, url, "apache license 2.0")
    assert decision.allowed and record.license == "Apache-2.0"
    row = db.execute(
        "SELECT url, source_type, license, license_source, host FROM knowledge.sources WHERE id = %s", (record.source_id,)
    ).fetchone()
    assert row == (url, "skill_md", "Apache-2.0", "repo", "github.com")

    for bad in ("GPL-3.0-only", "CC-BY-SA-4.0", "unknown", None):
        decision, record = register_skill_file(db, "https://github.com/acme/other/blob/main/SKILL.md", bad)
        assert not decision.allowed and record is None
    assert db.execute("SELECT count(*) FROM knowledge.sources").fetchone()[0] == 1, "refused files are not stored"


def test_register_rejects_a_url_that_is_not_http(db):
    with pytest.raises(ValueError):
        register_skill_file(db, "file:///etc/SKILL.md", "MIT")


# ---------------------------------------------------------------------------- (b) web pages
@pytest.mark.parametrize(
    ("label", "licence", "source", "cite_only"),
    [
        ("public-domain-us-gov", "LicenseRef-us-gov-public-domain", "manual", False),
        ("cc-by-4.0", "CC-BY-4.0", "manual", False),
        ("cc-by-sa-4.0", "CC-BY-SA-4.0", "manual", False),
        ("copyright-summarise-and-cite", "unknown", "unknown", True),
    ],
)
def test_each_crawl_list_label_has_its_mapping(label, licence, source, cite_only):
    mapped = web_page_licence(label)
    assert (mapped.license, mapped.license_source, mapped.summarise_and_cite_only) == (licence, source, cite_only)


def test_an_unknown_or_missing_label_is_never_read_as_permission(caplog):
    assert web_page_licence("something-new") == web_page_licence(None) == web_page_licence("")
    assert web_page_licence(None).license == "unknown"
    assert "something-new" in caplog.text


def test_the_page_wins_when_it_declares_a_licence():
    mapped = web_page_licence("copyright-summarise-and-cite", page_licence="CC-BY-4.0")
    assert (mapped.license, mapped.license_source) == ("CC-BY-4.0", "page")
    assert web_page_licence("cc-by-4.0", page_licence="MIT").license == "MIT"
    assert web_page_licence("cc-by-4.0", page_licence="unknown").license == "CC-BY-4.0", "'unknown' is no declaration"


def test_the_crawler_maps_the_labels_of_crawl_list():
    target = as_target(("https://example.org/a", "public-domain-us-gov"))
    assert (target.license, target.license_source) == ("LicenseRef-us-gov-public-domain", "manual")
    assert as_target("https://example.org/a") == CrawlTarget("https://example.org/a")
    unknown = as_target(("https://example.org/a", "copyright-summarise-and-cite"))
    assert (unknown.license, unknown.license_source) == ("unknown", "unknown")


def test_a_crawl_stores_the_mapped_licence_and_the_page_wins(db, crawl):  # noqa: F811
    make, srv = crawl
    make().run(
        [(f"{srv.base}/doc-a", "public-domain-us-gov"), (f"{srv.base}/doc-b", "copyright-summarise-and-cite"),
         (f"{srv.base}/ok", "cc-by-sa-4.0")],
        domains=["technology/ai"],
    )
    rows = {url.rsplit("/", 1)[1]: (lic, src) for url, lic, src in db.execute(
        "SELECT url, license, license_source FROM knowledge.sources")}
    assert rows["doc-a"] == ("LicenseRef-us-gov-public-domain", "manual")
    assert rows["doc-b"] == ("unknown", "unknown")
    assert rows["ok"] == ("CC-BY-4.0", "page"), "the page declares CC-BY-4.0, so it wins over the list's cc-by-sa-4.0"
