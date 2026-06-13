"""Pagination envelope + sort (invariant 3) — pure stdlib, runs anywhere."""

import unittest

from monday import pagination


class TestPagination(unittest.TestCase):
    def test_envelope_keys_and_slice(self):
        env = pagination.paginate(list(range(10)), 1, 5)
        self.assertEqual(set(env), {"items", "page", "page_size", "total", "has_more"})
        self.assertEqual(env["items"], [0, 1, 2, 3, 4])
        self.assertEqual(env["total"], 10)
        self.assertTrue(env["has_more"])

    def test_last_page_no_more(self):
        env = pagination.paginate(list(range(10)), 2, 5)
        self.assertEqual(env["items"], [5, 6, 7, 8, 9])
        self.assertFalse(env["has_more"])

    def test_clamp(self):
        self.assertEqual(pagination.clamp_page(0, 0), (1, 50))   # falsy → defaults (page 1, size 50)
        self.assertEqual(pagination.clamp_page(3, 99999), (3, pagination.MAX_PAGE_SIZE))

    def test_sort_missing_sinks_to_end(self):
        out = pagination.sort_by([{"v": 3}, {"v": None}, {"v": 7}], "v", "desc")
        self.assertEqual([o["v"] for o in out], [7, 3, None])


if __name__ == "__main__":
    unittest.main()
