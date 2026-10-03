"""Offline validation for the deployment-config skill candidate."""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "deployment-config"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
REF = (SKILL_DIR / "references" / "bridges.md").read_text(encoding="utf-8")


class SkillShape(unittest.TestCase):
    def test_frontmatter(self):
        self.assertTrue(SKILL.startswith("---\n"))
        fm = SKILL.split("---\n", 2)[1]
        self.assertIn("name: deployment-config", fm)
        self.assertIn("description:", fm)
        self.assertNotIn("<", fm.split("description:")[1].split("\n")[0])

    def test_hard_boundaries_present(self):
        for phrase in ("不默认完全访问", "不是 OS 沙箱", "预览-确认-写入", "幂等", "不猜键"):
            self.assertIn(phrase, SKILL, phrase)

    def test_no_machine_absolute_paths_in_skill(self):
        for forbidden in ("C:\\Users", "%USERPROFILE%\\.local"):
            self.assertNotIn(forbidden, SKILL.replace("%USERPROFILE%", ""), forbidden)

    def test_reference_link(self):
        self.assertIn("[references/bridges.md](references/bridges.md)", SKILL)
        self.assertIn("# Cursor CLI", REF)
        self.assertIn("# agy", REF)


class ReferenceAccuracy(unittest.TestCase):
    def test_cursor_facts(self):
        self.assertIn("cli-config.json", REF)
        self.assertIn("deny 优先于 allow", REF)
        self.assertIn("数组整体替换不追加", REF)
        self.assertIn("只能配 permissions", REF)

    def test_agy_facts(self):
        self.assertIn("always-proceed", REF)
        self.assertIn("allowNonWorkspaceAccess", REF)
        self.assertIn("持久键", REF)
        self.assertIn("Bridge 不兼容", REF)
        self.assertIn("Windows 仍用旧权限系统", REF)

    def test_unverified_boundaries_explicit(self):
        self.assertIn("未验证", REF)
        self.assertIn("Windows 的实际合并/覆盖顺序", REF)

    def test_cursor_no_global_unrestricted_advice(self):
        self.assertIn("不需要也不应在全局另设", REF)
        self.assertIn("unrestricted", REF)

    def test_managed_block_format(self):
        self.assertIn("bridge-deploy-config:v1 BEGIN", REF)
        self.assertIn("bridge-deploy-config:v1 END", REF)


if __name__ == "__main__":
    unittest.main()
