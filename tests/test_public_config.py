import copy
import unittest

from ai.config import settings
from ai.public_config import validate_public_config


class PublicConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = settings()

    def test_public_defaults_and_gmail_starttls_are_valid(self):
        self.assertIs(validate_public_config(self.config), self.config)
        self.config["notifications"]["smtp"].update(
            host="smtp.gmail.com", port=587, security="starttls"
        )
        validate_public_config(self.config)

    def test_duplicate_stable_ids_and_invalid_names_fail(self):
        for field in ("researchers", "recipients"):
            config = copy.deepcopy(self.config)
            items = (
                config[field]
                if field == "researchers"
                else config["notifications"][field]
            )
            items.append(copy.deepcopy(items[0]))
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                validate_public_config(config)
        for update in (
            {"id": "../outside"},
            {"display_name": ""},
            {"enabled": "false"},
            {"aliases": "A. Name"},
            {"suspected_aliases": ["\n"]},
        ):
            config = copy.deepcopy(self.config)
            config["researchers"][0].update(update)
            with self.assertRaises(ValueError):
                validate_public_config(config)

    def test_mail_header_injection_and_url_credentials_fail(self):
        for address in (
            "",
            "Name <person@example.org>",
            "person@example.org\nBcc: other@example.org",
            "person@example.org,other@example.org",
        ):
            config = copy.deepcopy(self.config)
            config["notifications"]["recipients"][0]["email"] = address
            with self.assertRaises(ValueError):
                validate_public_config(config)
        for url in (
            "javascript:alert(1)",
            "https://user:secret@example.org/",
            "https://example.org/ bad",
            "relative/path",
            "https://example.org:invalid/",
        ):
            config = copy.deepcopy(self.config)
            config["notifications"]["site_url"] = url
            with self.assertRaises(ValueError):
                validate_public_config(config)

    def test_insecure_smtp_and_public_credentials_fail(self):
        for update in (
            {"security": "plain"},
            {"host": "smtp://mail.example.org"},
            {"port": 0},
            {"port": True},
            {"port": 65536},
            {"sender": "a@example.org\nBcc:b@example.org"},
            {"password": "fictional-value"},
            {"username_env": "literal user"},
            {"password_env": "SMTP_USERNAME"},
            {"max_attempts": 0},
            {"timeout": 0},
        ):
            config = copy.deepcopy(self.config)
            config["notifications"]["smtp"].update(update)
            with self.assertRaises(ValueError):
                validate_public_config(config)


if __name__ == "__main__":
    unittest.main()
