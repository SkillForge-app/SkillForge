"""DE-09: the domain knowledge cache: coverage, freshness, the re-crawl schedule, and "a second request reuses the cache"."""
from datetime import timedelta

import pytest
from fakes import T0, FakeEmbed, FakeExtract, fake_normalise_url, page_bytes

from skillforge_data.cache import (
    domain_and_parents,
    due_for_recrawl,
    ensure_domain,
    plan_domain,
)
from skillforge_data.freshness import FreshnessRules
from skillforge_data.pipeline.config import PipelineConfig
from skillforge_data.pipeline.process import RawPage, process_document

CONFIG = PipelineConfig(pipeline_version="p1", embedding_version="rev-1")
NOW = T0 + timedelta(days=100)
RULES = FreshnessRules(min_documents=3)          # 30 days for web pages, 90 for skill_md and repo_file


class World:
    def __init__(self, db):
        self.db = db
        self.extract, self.embed = FakeExtract(), FakeEmbed()

    def add(self, name, domains=("technology/ai",), age_days=1, *, source_type="web_page", text=None, reject=()):
        """Store a page of `name`, fetched `age_days` before NOW."""
        page = RawPage(
            url=f"https://{name}.example.org/page", content=page_bytes((text or f"text of {name}",), title=name, reject=reject),
            fetched_at=NOW - timedelta(days=age_days), domains=list(domains), content_type="text/html", source_type=source_type,
        )
        result = process_document(self.db, page, config=CONFIG, extract=self.extract, embed=self.embed,
                                  normalise_url=fake_normalise_url)
        assert result.status in ("processed", "rejected"), result.error
        return result

    def one(self, sql, *params):
        return self.db.execute(sql, params).fetchone()[0]


@pytest.fixture
def world(db):
    return World(db)


def plan(world, domain="technology/ai", rules=RULES):
    return plan_domain(world.db, domain, rules=rules, now=NOW)


def test_domain_and_parents():
    assert domain_and_parents("marketing/email/newsletters") == ["marketing", "marketing/email", "marketing/email/newsletters"]
    assert domain_and_parents("technology") == ["technology"]
    with pytest.raises(ValueError):
        domain_and_parents("/")


def test_the_rules_are_validated_and_per_source_type():
    assert RULES.max_age_for("web_page") == timedelta(days=30) and RULES.max_age_for("skill_md") == timedelta(days=90)
    with pytest.raises(ValueError):
        FreshnessRules(min_documents=0)
    with pytest.raises(ValueError):
        FreshnessRules(max_age=timedelta(0))


# ---------------------------------------------------------------------------------------------- coverage
def test_enough_fresh_documents_means_reuse(world):
    for n in range(3):
        world.add(f"fresh{n}")
    p = plan(world)
    assert (p.action, p.fresh, p.stale, p.covered) == ("reuse", 3, 0, True)


def test_pages_older_than_the_window_do_not_count_but_can_be_refreshed(world):
    world.add("fresh0")
    world.add("fresh1")
    world.add("old0", age_days=45)
    world.add("old1", age_days=60)
    p = plan(world)
    assert (p.action, p.fresh, p.stale) == ("refresh", 2, 2)
    assert [s.url for s in p.stale_sources] == ["https://old1.example.org/page", "https://old0.example.org/page"], "oldest first"


def test_too_few_known_sources_means_crawl_and_says_how_many_are_missing(world):
    world.add("only")
    p = plan(world)
    assert (p.action, p.fresh, p.missing) == ("crawl", 1, 2)
    assert plan(world, "finance/accounting").action == "crawl" and plan(world, "finance/accounting").missing == 3


def test_what_does_not_count(world):
    world.add("good")
    world.add("rejected", reject=("paywall_or_login",))
    dup = world.add("copy")
    world.db.execute("UPDATE knowledge.documents SET duplicate_of = (SELECT id FROM knowledge.documents WHERE title = 'good') "
                     "WHERE id = %s", (dup.document_id,))
    world.add("changed", text="first version")
    world.add("changed", text="second version")                      # the first version is not current any more
    assert plan(world).fresh == 2, "the good page and the current version of 'changed'; not the rejected page or the copy"


def test_the_window_depends_on_the_source_type(world):
    world.add("web", age_days=45)
    world.add("skill", age_days=45, source_type="skill_md")
    p = plan(world)
    assert p.fresh == 1 and p.stale == 1, "45 days: too old for a web page, fresh for a SKILL.md (90 days)"


def test_a_source_that_robots_txt_forbids_is_not_offered_for_refresh(world):
    world.add("old", age_days=60)
    world.db.execute("UPDATE knowledge.sources SET robots_allowed = false")
    p = plan(world)
    assert p.stale == 1 and p.stale_sources == []


# ------------------------------------------------------------------------ domains, parents and children
def test_parents_and_children_of_a_domain_count_and_other_domains_do_not(world):
    world.add("parent", domains=("marketing",))
    world.add("exact", domains=("marketing/email",))
    world.add("child", domains=("marketing/email/newsletters",))
    world.add("sibling", domains=("marketing/seo",))
    world.add("elsewhere", domains=("finance/accounting",))
    assert plan(world, "marketing/email").fresh == 3
    assert plan(world, "marketing/seo").fresh == 2, "its parent 'marketing' and itself"


def test_one_source_serves_several_skills(world):
    world.add("shared", domains=("technology/ai", "marketing/email"))
    assert plan(world, "technology/ai").fresh == 1 and plan(world, "marketing/email").fresh == 1


# ------------------------------------------------------------------------- "a second request reuses it"
def test_a_second_request_in_the_same_domain_reuses_the_cache(world):
    crawled = []

    def crawl(p):
        crawled.append(p.action)
        for n in range(p.missing):
            world.add(f"new{n}")

    first = ensure_domain(world.db, "technology/ai", rules=RULES, now=NOW, crawl=crawl)
    second = ensure_domain(world.db, "technology/ai", rules=RULES, now=NOW, crawl=crawl)
    assert (first.action, second.action) == ("crawl", "reuse")
    assert crawled == ["crawl"], "the second request did not crawl"
    assert second.fresh == 3


def test_a_request_for_a_covered_parent_domain_is_a_cache_hit_for_a_child(world):
    for n in range(3):
        world.add(f"p{n}", domains=("marketing",))
    calls = []
    plan_ = ensure_domain(world.db, "marketing/email", rules=RULES, now=NOW, crawl=calls.append)
    assert plan_.action == "reuse" and calls == []


# --------------------------------------------------------------------------------------------- schedule
def test_the_recrawl_schedule_lists_what_is_due_oldest_first(world):
    world.add("fresh", age_days=2)
    world.add("old10", age_days=40)
    world.add("old20", age_days=80)
    world.add("skill-fresh", age_days=60, source_type="skill_md")
    world.add("skill-old", age_days=120, source_type="skill_md")
    world.db.execute("INSERT INTO knowledge.sources (url, host, source_type) VALUES ('https://never.example.org/x', "
                     "'never.example.org', 'web_page')")
    due = due_for_recrawl(world.db, rules=RULES, now=NOW)
    assert [d.url for d in due] == [
        "https://never.example.org/x",                      # never fetched: first
        "https://skill-old.example.org/page",               # 120 days
        "https://old20.example.org/page",                   # 80 days
        "https://old10.example.org/page",                   # 40 days
    ]
    assert due[0].last_fetched_at is None


def test_the_schedule_skips_forbidden_sources_and_can_be_limited_or_filtered_by_domain(world):
    world.add("a", domains=("technology/ai",), age_days=50)
    world.add("b", domains=("marketing/email",), age_days=60)
    world.add("c", domains=("marketing/email",), age_days=70)
    world.db.execute("UPDATE knowledge.sources SET robots_allowed = false WHERE url LIKE '%//c.%'")
    assert [d.url for d in due_for_recrawl(world.db, rules=RULES, now=NOW)] == [
        "https://b.example.org/page", "https://a.example.org/page"]
    assert [d.url for d in due_for_recrawl(world.db, rules=RULES, now=NOW, domain="marketing/email")] == [
        "https://b.example.org/page"]
    assert len(due_for_recrawl(world.db, rules=RULES, now=NOW, limit=1)) == 1
