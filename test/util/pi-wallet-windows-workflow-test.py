#!/usr/bin/env python3
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pi-wallet-windows-qa.yml"


class WindowsWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_manual_or_qa_branch_only_and_read_only(self):
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn(
            "push:\n    branches:\n      - audit/recovery-20260719",
            self.text,
        )
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("pull_request:", self.text)
        self.assertNotIn("      - main", self.text)

    def test_core_is_cross_built_without_qt_or_legacy_wallet(self):
        self.assertIn("runs-on: ubuntu-22.04", self.text)
        self.assertIn("HOST=x86_64-w64-mingw32 NO_QT=1 NO_BDB=1", self.text)
        self.assertIn("--without-gui", self.text)
        self.assertIn("--without-bdb", self.text)
        self.assertIn("make -j2 src/pid.exe", self.text)

    def test_packaging_runs_on_native_windows_x64(self):
        self.assertIn("runs-on: windows-2022", self.text)
        self.assertIn("python-version: '3.12'", self.text)
        self.assertIn("architecture: x64", self.text)
        self.assertIn("python contrib/windeploy/pi-wallet/build.py", self.text)

    def test_artifact_is_explicitly_unsigned_qa(self):
        self.assertIn("Pi-Wallet-windows-x86_64-qa-unsigned", self.text)
        self.assertNotIn("softprops/action-gh-release", self.text)
        self.assertNotIn("create-release", self.text.lower())

    def test_workflow_contains_no_production_endpoint_or_secret(self):
        lowered = self.text.lower()
        self.assertNotIn(".onion", lowered)
        self.assertNotIn("rpcpassword", lowered)
        self.assertNotIn("secrets.", lowered)

    def test_unsigned_qa_excludes_release_configuration(self):
        self.assertIn(
            "Unsigned QA package unexpectedly contains a production bootstrap configuration",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
