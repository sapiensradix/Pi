#!/usr/bin/env python3

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "src" / "pi_wallet.py"
SPEC = importlib.util.spec_from_file_location("pi_wallet", SOURCE)
pi_wallet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_wallet)


def onion_endpoint(seed):
    public_key = bytes([seed]) * 32
    version = b"\x03"
    checksum = hashlib.sha3_256(
        b".onion checksum" + public_key + version
    ).digest()[:2]
    hostname = base64.b32encode(public_key + checksum + version).decode().lower()
    return f"{hostname}.onion:31415"


def tor_only_config(endpoints):
    lines = [
        "server=1",
        "listen=1",
        "bind=127.0.0.1:31415",
        "port=31415",
        "discover=0",
        "dnsseed=0",
        "fixedseeds=0",
        "listenonion=0",
        "onlynet=onion",
        "proxy=127.0.0.1:9050",
        "onion=127.0.0.1:9050",
        "rpcbind=127.0.0.1",
        "rpcallowip=127.0.0.1",
    ]
    lines.extend(f"addnode={endpoint}" for endpoint in endpoints)
    return "\n".join(lines) + "\n"


class TorOnlyConfigTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.config = self.root / "Pi" / "pi.conf"
        self.template = self.root / "pi.conf.release"
        self.endpoints = [onion_endpoint(seed) for seed in (1, 2, 3)]

    def tearDown(self):
        self.tempdir.cleanup()

    def write_template(self, text=None):
        self.template.write_text(
            tor_only_config(self.endpoints) if text is None else text,
            encoding="utf-8",
        )

    def test_validates_onion_v3_address_and_checksum(self):
        endpoint = self.endpoints[0]
        self.assertTrue(pi_wallet._valid_onion_v3_endpoint(endpoint))
        replacement = "a" if endpoint[10] != "a" else "b"
        corrupted = endpoint[:10] + replacement + endpoint[11:]
        self.assertFalse(pi_wallet._valid_onion_v3_endpoint(corrupted))
        self.assertFalse(pi_wallet._valid_onion_v3_endpoint("127.0.0.1:31415"))

    def test_installs_valid_release_config_with_private_permissions(self):
        self.write_template()
        result = pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertEqual(result, "created")
        self.assertEqual(self.config.read_bytes(), self.template.read_bytes())
        if os.name != "nt":
            self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            pi_wallet.validate_tor_only_config(self.config, minimum_bootstraps=3),
            self.endpoints,
        )

    def test_preserves_existing_valid_config(self):
        self.config.parent.mkdir()
        existing = tor_only_config([self.endpoints[0]]) + "maxconnections=32\n"
        self.config.write_text(existing, encoding="utf-8")
        result = pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertEqual(result, "existing")
        self.assertEqual(self.config.read_text(encoding="utf-8"), existing)

    def test_missing_release_template_does_not_create_config(self):
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "release configuration"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertFalse(self.config.exists())

    def test_rejects_release_template_with_fewer_than_three_bootstraps(self):
        self.write_template(tor_only_config(self.endpoints[:2]))
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "at least 3"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertFalse(self.config.exists())

    def test_rejects_duplicate_bootstraps(self):
        duplicate = [self.endpoints[0], self.endpoints[0], self.endpoints[1]]
        self.write_template(tor_only_config(duplicate))
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "duplicate"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertFalse(self.config.exists())

    def test_rejects_clearnet_bootstrap(self):
        self.write_template(
            tor_only_config(self.endpoints) + "addnode=clearnet.invalid:31415\n"
        )
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "Tor v3"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertFalse(self.config.exists())

    def test_rejects_clearnet_network_setting(self):
        self.write_template(
            tor_only_config(self.endpoints).replace(
                "onlynet=onion", "onlynet=onion\nonlynet=ipv4"
            )
        )
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "onlynet=onion"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)

    def test_rejects_includeconf_and_clearnet_externalip(self):
        self.write_template(
            tor_only_config(self.endpoints) + "includeconf=extra.conf\n"
        )
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "not allowed"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)

        self.write_template(
            tor_only_config(self.endpoints) + "externalip=clearnet.invalid\n"
        )
        with self.assertRaisesRegex(pi_wallet.PiRPCError, "Tor v3"):
            pi_wallet.ensure_tor_only_config(self.config, self.template)

    def test_allows_onion_externalip_and_default_p2p_port(self):
        text = tor_only_config(self.endpoints).replace("port=31415\n", "")
        text += f"externalip={self.endpoints[0].rsplit(':', 1)[0]}\n"
        self.write_template(text)
        result = pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertEqual(result, "created")

    def test_non_main_sections_do_not_weaken_mainnet_policy(self):
        text = tor_only_config(self.endpoints) + "[regtest]\nonlynet=ipv4\n"
        self.write_template(text)
        result = pi_wallet.ensure_tor_only_config(self.config, self.template)
        self.assertEqual(result, "created")


if __name__ == "__main__":
    unittest.main()
