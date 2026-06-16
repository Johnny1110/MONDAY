"""config.reload() re-reads .env into settings in place without leaking secrets (B4).
Needs pydantic-settings; skipped on a bare interpreter."""

import os
import tempfile
import unittest

try:
    import pydantic_settings  # noqa: F401
    HAVE = True
except Exception:
    HAVE = False


@unittest.skipUnless(HAVE, "needs pydantic-settings")
class TestConfigReload(unittest.TestCase):
    def test_reload_updates_in_place_names_only(self):
        from monday import config
        d = tempfile.mkdtemp()
        envp = os.path.join(d, ".env")
        saved_cfg = dict(config.Settings.model_config)
        saved_tok, saved_uni = config.settings.finmind_token, config.settings.universe_size
        config.Settings.model_config["env_file"] = envp
        try:
            with open(envp, "w") as f:
                f.write("FINMIND_TOKEN=\nUNIVERSE_SIZE=500\n")
            config.reload()
            self.assertEqual(config.settings.finmind_token, "")
            self.assertEqual(config.settings.universe_size, 500)

            with open(envp, "w") as f:
                f.write("FINMIND_TOKEN=secret123\nUNIVERSE_SIZE=42\n")
            changed = config.reload()
            self.assertEqual(config.settings.finmind_token, "secret123")
            self.assertEqual(config.settings.universe_size, 42)
            self.assertIn("finmind_token", changed)
            self.assertIn("universe_size", changed)
            self.assertNotIn("secret123", changed)          # field NAMES only, never values
        finally:
            config.Settings.model_config.clear()
            config.Settings.model_config.update(saved_cfg)
            config.settings.finmind_token, config.settings.universe_size = saved_tok, saved_uni


if __name__ == "__main__":
    unittest.main()
