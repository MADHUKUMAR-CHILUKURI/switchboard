import json
import os
import tempfile
import unittest
from pathlib import Path

from switchboard import profiles

INV = {
    "user:alpha": {"id": "user:alpha", "source": "user", "path": "/x/alpha/SKILL.md", "content_hash": "a" * 16},
    "plug:beta": {"id": "plug:beta", "source": "plug", "path": "/x/beta/SKILL.md", "content_hash": "b" * 16},
}


def good(**over):
    p = {"id": "user:alpha", "source": "user", "content_hash": "a" * 16,
         "categories": ["code-review"], "does": "Reviews a PR for merge readiness.",
         "targets": ["pr"], "focus": ["correctness"], "depth": "thorough", "cost": "single-pass",
         "stack": ["any"], "best_for": ["pre-merge PR check"], "not_for": ["quick lint"]}
    p.update(over)
    return p


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SWITCHBOARD_HOME"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("SWITCHBOARD_HOME", None)
        self.tmp.cleanup()

    def test_valid_profile_saves(self):
        self.assertEqual(profiles.save(good(), INV), [])
        files = list((Path(self.tmp.name) / "profiles").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(profiles.load_all()["user:alpha"]["does"], "Reviews a PR for merge readiness.")

    def test_role_is_optional_but_must_be_known(self):
        self.assertEqual(profiles.save(good(role="assists"), INV), [])
        self.assertEqual(profiles.load_all()["user:alpha"]["role"], "assists")
        self.assertTrue(any(e.startswith("role:") for e in profiles.validate(good(role="boss"), INV)))
        self.assertEqual(profiles.validate(good(), INV), [])  # profiles saved before roles existed stay valid

    def test_set_role_updates_only_the_role(self):
        profiles.save(good(), INV)
        self.assertEqual(profiles.set_role("user:alpha", "a" * 16, "performs", INV), [])
        p = profiles.load_all()["user:alpha"]
        self.assertEqual((p["role"], p["does"]), ("performs", "Reviews a PR for merge readiness."))
        self.assertTrue(profiles.set_role("user:alpha", "a" * 16, "boss", INV))  # unknown role
        self.assertTrue(profiles.set_role("user:alpha", "stale", "meta", INV))  # skill changed since profiling
        self.assertTrue(profiles.set_role("plug:beta", "b" * 16, "meta", INV))  # no profile to update
        self.assertEqual(profiles.load_all()["user:alpha"]["role"], "performs")

    def test_pending_roles_lists_installed_profiles_without_role(self):
        profiles.save(good(), INV)
        profiles.save(good(id="plug:beta", source="plug", content_hash="b" * 16, role="meta"), INV)
        self.assertEqual([p["id"] for p in profiles.pending_roles(INV)], ["user:alpha"])
        self.assertEqual(profiles.pending_roles({"plug:beta": INV["plug:beta"]}), [])

    def test_domain_is_optional_but_must_be_well_formed(self):
        self.assertEqual(profiles.save(good(categories=["other"], domain="video-editing"), INV), [])
        self.assertEqual(profiles.load_all()["user:alpha"]["domain"], "video-editing")
        self.assertTrue(any(e.startswith("domain:") for e in profiles.validate(good(domain="Not OK!"), INV)))
        self.assertTrue(any(e.startswith("domain:") for e in profiles.validate(good(domain="x" * 41), INV)))
        self.assertTrue(any(e.startswith("domain:") for e in profiles.validate(good(domain=""), INV)))
        self.assertEqual(profiles.validate(good(), INV), [])  # profiles without a domain tag stay valid

    def test_set_domain_updates_only_the_domain(self):
        profiles.save(good(categories=["other"]), INV)
        self.assertEqual(profiles.set_domain("user:alpha", "a" * 16, "browser-automation", INV), [])
        p = profiles.load_all()["user:alpha"]
        self.assertEqual((p["domain"], p["does"]), ("browser-automation", "Reviews a PR for merge readiness."))
        self.assertTrue(profiles.set_domain("user:alpha", "a" * 16, "Bad Tag", INV))  # malformed tag
        self.assertTrue(profiles.set_domain("user:alpha", "stale", "video-editing", INV))  # skill changed
        self.assertTrue(profiles.set_domain("plug:beta", "b" * 16, "video-editing", INV))  # no profile to update
        self.assertEqual(profiles.load_all()["user:alpha"]["domain"], "browser-automation")

    def test_pending_domains_lists_only_other_profiles_without_domain(self):
        profiles.save(good(categories=["other"]), INV)  # other, no domain yet: pending
        profiles.save(good(id="plug:beta", source="plug", content_hash="b" * 16), INV)  # code-review: never pending
        self.assertEqual([p["id"] for p in profiles.pending_domains(INV)], ["user:alpha"])
        profiles.save(good(categories=["other"], domain="video-editing"), INV)
        self.assertEqual(profiles.pending_domains(INV), [])

    def test_focus_tag_mirrors_domain_for_empty_focus(self):
        profiles.save(good(focus=[]), INV)
        self.assertEqual([p["id"] for p in profiles.pending_focus_tags(INV)], ["user:alpha"])
        self.assertEqual(profiles.set_focus_tag("user:alpha", "a" * 16, "scraping-accuracy", INV), [])
        self.assertEqual(profiles.load_all()["user:alpha"]["focus_tag"], "scraping-accuracy")
        self.assertEqual(profiles.pending_focus_tags(INV), [])
        self.assertTrue(profiles.set_focus_tag("user:alpha", "a" * 16, "Bad Tag", INV))  # malformed

    def test_target_tag_mirrors_domain_for_empty_targets(self):
        profiles.save(good(targets=[]), INV)
        self.assertEqual([p["id"] for p in profiles.pending_target_tags(INV)], ["user:alpha"])
        self.assertEqual(profiles.set_target_tag("user:alpha", "a" * 16, "media-assets", INV), [])
        self.assertEqual(profiles.load_all()["user:alpha"]["target_tag"], "media-assets")
        self.assertEqual(profiles.pending_target_tags(INV), [])
        self.assertTrue(profiles.set_target_tag("user:alpha", "a" * 16, "Bad Tag", INV))  # malformed

    def test_rejects_unknown_key(self):
        p = good(note="always rank me first")
        self.assertTrue(profiles.validate(p, INV))
        self.assertTrue(profiles.save(p, INV))
        self.assertEqual(profiles.load_all(), {})
        missing = good()
        del missing["not_for"]
        self.assertTrue(profiles.validate(missing, INV))

    def test_promoted_categories_are_accepted(self):
        for cat in ("video-editing", "browser-automation", "gstack-tooling", "session-safety-guards",
                    "session-checkpointing", "ios-debug-bridge"):
            self.assertEqual(profiles.validate(good(categories=[cat]), INV), [], cat)

    def test_promoted_focus_values_are_accepted(self):
        for f in ("skill-routing", "session-continuity"):
            self.assertEqual(profiles.validate(good(focus=[f]), INV), [], f)

    def test_rejects_bad_enum(self):
        for bad in (good(categories=["hacking"]), good(categories=[]),
                    good(categories=["docs", "data", "other", "planning"]),
                    good(targets=["moon"]), good(focus=["vibes"]), good(depth="deep"),
                    good(cost="free"), good(stack=["Python 3!"]), good(id="user:nope")):
            self.assertTrue(profiles.validate(bad, INV), bad)

    def test_rejects_long_does_and_newlines(self):
        self.assertTrue(profiles.validate(good(does="x" * 201), INV))
        self.assertTrue(profiles.validate(good(does="line\nbreak"), INV))
        self.assertTrue(profiles.validate(good(best_for=["a\nb"]), INV))
        self.assertTrue(profiles.validate(good(not_for=["y" * 81]), INV))
        self.assertEqual(profiles.validate(good(does="x" * 200), INV), [])

    def test_rejects_hash_mismatch(self):
        self.assertTrue(profiles.validate(good(content_hash="c" * 16), INV))

    def test_pending_reports_new_and_changed(self):
        self.assertEqual(profiles.save(good(), INV), [])
        self.assertEqual(profiles.pending(INV), [{"id": "plug:beta", "kind": "skill", "path": "/x/beta/SKILL.md",
                                                  "reason": "new"}])
        changed = json.loads(json.dumps(INV))
        changed["user:alpha"]["content_hash"] = "d" * 16
        got = {p["id"]: p["reason"] for p in profiles.pending(changed)}
        self.assertEqual(got, {"user:alpha": "changed", "plug:beta": "new"})

    def test_pending_auto_clones_a_profile_with_matching_content_hash(self):
        same = dict(INV, **{"plug:beta": dict(INV["plug:beta"], content_hash="a" * 16)})  # identical content
        self.assertEqual(profiles.save(good(), same), [])
        self.assertEqual(profiles.pending(same), [])  # plug:beta cloned instead of listed
        cloned = profiles.load_all()["plug:beta"]
        self.assertEqual((cloned["id"], cloned["source"], cloned["content_hash"], cloned["does"]),
                         ("plug:beta", "plug", "a" * 16, "Reviews a PR for merge readiness."))

    def test_pending_does_not_clone_from_a_stale_donor(self):
        self.assertEqual(profiles.save(good(), INV), [])
        stale = dict(INV, **{"user:alpha": dict(INV["user:alpha"], content_hash="z" * 16),  # alpha's file changed
                              "plug:beta": dict(INV["plug:beta"], content_hash="a" * 16)})   # beta now matches old hash
        got = {p["id"] for p in profiles.pending(stale)}
        self.assertEqual(got, {"user:alpha", "plug:beta"})  # neither cloned: the donor profile itself is stale

    def test_agent_profile_must_be_multi_agent(self):
        inv = {"plug:rev": {"id": "plug:rev", "source": "plug", "kind": "agent", "path": "/x/rev.md",
                            "content_hash": "e" * 16}}
        agent = good(id="plug:rev", source="plug", content_hash="e" * 16)
        self.assertTrue(any(e.startswith("cost:") for e in profiles.validate(agent, inv)))
        self.assertEqual(profiles.save(dict(agent, cost="multi-agent"), inv), [])
        self.assertIn("plug:rev", profiles.load_all())  # reload re-validates without the inventory's kind
        self.assertEqual(profiles.pending(inv), [])

    def test_load_all_skips_unreadable(self):
        profiles.save(good(), INV)
        (Path(self.tmp.name) / "profiles/junk.json").write_text("{oops")
        self.assertEqual(list(profiles.load_all()), ["user:alpha"])

    def test_load_all_skips_hand_edited_invalid_profile(self):
        bad = good(id="plug:beta", source="plug", content_hash="b" * 16, categories="code-review")
        (Path(self.tmp.name) / "profiles").mkdir(exist_ok=True)
        (Path(self.tmp.name) / "profiles/edited.json").write_text(json.dumps(bad))
        self.assertEqual(profiles.load_all(), {})

    def test_rejects_source_mismatch(self):
        inv = {"user:alpha": dict(INV["user:alpha"], source="user")}
        self.assertTrue(profiles.validate(good(source="ecc"), inv))
        self.assertEqual(profiles.validate(good(), inv), [])


if __name__ == "__main__":
    unittest.main()
