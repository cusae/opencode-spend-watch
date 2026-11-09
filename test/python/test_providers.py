import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import providers


def config(**extra):
    values = {
        "providers": ("opencode",),
        "openrouter_key": "",
        "openrouter_budget": 0.0,
        "openai_key": "",
        "openai_budget": 0.0,
        "openai_org": "",
    }
    values.update(extra)
    return SimpleNamespace(**values)


class OpenRouterTests(unittest.TestCase):
    def test_reads_credits_and_usage(self):
        body = {"data": {"total_credits": 20.0, "total_usage": 5.25}}
        with mock.patch.object(providers, "_get_json", return_value=body):
            snapshot = providers.openrouter("key")
        self.assertEqual(snapshot.spend, 5.25)
        self.assertEqual(snapshot.budget, 20.0)
        self.assertEqual(snapshot.remaining, 14.75)
        self.assertEqual(snapshot.period_key, "lifetime")

    def test_explicit_budget_wins(self):
        body = {"data": {"total_credits": 20.0, "total_usage": 5.0}}
        with mock.patch.object(providers, "_get_json", return_value=body):
            snapshot = providers.openrouter("key", budget=10.0)
        self.assertEqual(snapshot.budget, 10.0)
        self.assertEqual(snapshot.remaining, 5.0)

    def test_malformed_payload_raises(self):
        with (
            mock.patch.object(providers, "_get_json", return_value={"data": {}}),
            self.assertRaises(providers.ProviderError),
        ):
            providers.openrouter("key")


class OpenAITests(unittest.TestCase):
    def test_sums_buckets_across_pages(self):
        pages = [
            {
                "data": [
                    {"results": [{"amount": {"value": "1.25"}}]},
                    {"results": [{"amount": {"value": 2.5}}]},
                ],
                "has_more": True,
                "next_page": "p2",
            },
            {
                "data": [{"results": [{"amount": {"value": "0.25"}}]}],
                "has_more": False,
            },
        ]
        with mock.patch.object(providers, "_get_json", side_effect=pages) as get:
            snapshot = providers.openai("key", budget=20.0, org="org-1")
        self.assertEqual(snapshot.spend, 4.0)
        self.assertEqual(snapshot.budget, 20.0)
        self.assertEqual(snapshot.remaining, 16.0)
        self.assertEqual(snapshot.period_key, datetime.now(timezone.utc).strftime("%Y-%m"))
        self.assertIn("OpenAI-Organization", get.call_args_list[0].args[1])

    def test_without_budget_has_no_remaining(self):
        page = {"data": [], "has_more": False}
        with mock.patch.object(providers, "_get_json", return_value=page):
            snapshot = providers.openai("key")
        self.assertIsNone(snapshot.budget)
        self.assertIsNone(snapshot.remaining)


class CollectTests(unittest.TestCase):
    def test_skips_opencode(self):
        snapshots, errors = providers.collect(config())
        self.assertEqual(snapshots, [])
        self.assertEqual(errors, [])

    def test_missing_key_is_an_error(self):
        snapshots, errors = providers.collect(config(providers=("openrouter",)))
        self.assertEqual(snapshots, [])
        self.assertIn("OPENROUTER_API_KEY", errors[0])

    def test_unknown_provider_is_an_error(self):
        snapshots, errors = providers.collect(config(providers=("mystery",)))
        self.assertEqual(snapshots, [])
        self.assertIn("unknown provider", errors[0])

    def test_collects_enabled_providers(self):
        body = {"data": {"total_credits": 10.0, "total_usage": 1.0}}
        cfg = config(providers=("openrouter", "openai"), openrouter_key="or")
        page = {"data": [], "has_more": False}
        with mock.patch.object(providers, "_get_json", side_effect=[body, page]):
            snapshots, errors = providers.collect(cfg)
        self.assertEqual(errors, ["openai: OPENAI_ADMIN_KEY is not set"])
        self.assertEqual([snapshot.name for snapshot in snapshots], ["openrouter"])


if __name__ == "__main__":
    unittest.main()
