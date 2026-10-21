import hashlib
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_site import ROOT, build


class AuthBuildTests(unittest.TestCase):
    def test_auth_versions_and_repository_sessions_are_consistent(self):
        source = (ROOT / "js/auth-config.js").read_bytes()
        password = "  Fictional 密码🔬 café  "
        configurations = []
        for repository in ("Owner/chinese", "Owner/english"):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "site"
                with patch.dict(os.environ, {"ACCESS_PASSWORD": password}):
                    build(output, repository)
                auth = (output / "js/auth-config.js").read_text()
                self.assertIn(
                    hashlib.sha256(password.encode("utf-8")).hexdigest(), auth
                )
                self.assertNotIn(password, auth)
                self.assertIn("arxiv_auth:" + repository.lower() + ":token", auth)
                configurations.append(auth)
                versions = set()
                for page in output.glob("*.html"):
                    references = re.findall(
                        r'src="(js/[^"?]+\.js)\?v=([a-f0-9]+)"', page.read_text()
                    )
                    self.assertTrue(references)
                    self.assertEqual(
                        len(re.findall(r'src="js/[^\"]+"', page.read_text())),
                        len(references),
                    )
                    scripts = dict(references)
                    self.assertIn("js/auth-config.js", scripts)
                    self.assertIn("js/auth.js", scripts)
                    versions.add(scripts["js/auth-config.js"])
                    for name, version in references:
                        self.assertEqual(
                            hashlib.sha256((output / name).read_bytes()).hexdigest()[
                                :16
                            ],
                            version,
                        )
                self.assertEqual(len(versions), 1)
        self.assertNotEqual(configurations[0], configurations[1])
        self.assertEqual((ROOT / "js/auth-config.js").read_bytes(), source)

    def test_password_change_invalidates_configuration_url(self):
        versions = []
        with tempfile.TemporaryDirectory() as directory:
            for index, password in enumerate(("fictional first", "fictional second")):
                output = Path(directory) / str(index)
                with patch.dict(os.environ, {"ACCESS_PASSWORD": password}):
                    build(output, "Owner/project")
                versions.append(
                    re.search(
                        r"js/auth-config.js\?v=([a-f0-9]+)",
                        (output / "login.html").read_text(),
                    )[1]
                )
        self.assertNotEqual(*versions)


if __name__ == "__main__":
    unittest.main()
