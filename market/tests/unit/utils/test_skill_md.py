# -*- coding: utf-8 -*-
"""SKILL.md frontmatter 工具单元测试."""

from __future__ import annotations

from market.utils.skill_md import (
    extract_cn_name_from_title,
    extract_metadata,
    extract_skill_id,
    extract_version,
    parse_frontmatter,
)

SAMPLE_MD = """---
name: 测试技能
description: 一个测试用的技能
version: "1.2.3"
chinese_name: 测试
---

# 测试技能

正文内容。
"""

SAMPLE_MD_NO_VERSION = """---
name: no_version_skill
description: ""
---

正文。
"""

SAMPLE_MD_V_PREFIX = """---
name: prefix_skill
version: v2.0.0
---

正文。
"""


class TestParseFrontmatter:
    def test_basic(self):
        fm = parse_frontmatter(SAMPLE_MD)
        assert fm["name"] == "测试技能"
        assert fm["description"] == "一个测试用的技能"
        assert fm["version"] == "1.2.3"
        assert fm["chinese_name"] == "测试"

    def test_no_frontmatter(self):
        fm = parse_frontmatter("# Just a heading\n\nNo fm.")
        assert fm == {}

    def test_empty_input(self):
        assert parse_frontmatter("") == {}


class TestExtractVersion:
    def test_quoted(self):
        assert extract_version(SAMPLE_MD) == "1.2.3"

    def test_no_version(self):
        assert extract_version(SAMPLE_MD_NO_VERSION) == ""

    def test_v_prefix(self):
        assert extract_version(SAMPLE_MD_V_PREFIX) == "2.0.0"

    def test_no_frontmatter(self):
        assert extract_version("plain text") == ""

    def test_empty_input(self):
        assert extract_version("") == ""


class TestExtractMetadata:
    def test_returns_known_keys(self):
        meta = extract_metadata(SAMPLE_MD)
        assert meta["name"] == "测试技能"
        assert meta["description"] == "一个测试用的技能"
        assert meta["version"] == "1.2.3"
        assert meta["chinese_name"] == "测试"

    def test_missing_keys_return_empty_string(self):
        meta = extract_metadata(SAMPLE_MD_NO_VERSION)
        assert meta["name"] == "no_version_skill"
        assert meta["description"] == ""
        assert meta["version"] == ""
        assert meta["chinese_name"] == ""


# skill_id 相关测试数据
SAMPLE_MD_WITH_SKILL_ID = """---
name: xlsx
description: "Excel processing skill"
metadata:
  skill_id: "xlsx_001"
  cn_name: "Excel表格处理"
---
# Excel表格处理

Skill content here.
"""

SAMPLE_MD_NO_SKILL_ID = """---
name: my_skill
description: "My custom skill"
---
# My Skill

Skill content.
"""


class TestExtractSkillId:
    """测试 skill_id 提取逻辑."""

    def test_extract_from_frontmatter_metadata(self):
        """从 frontmatter metadata 中提取 skill_id."""
        skill_id = extract_skill_id(SAMPLE_MD_WITH_SKILL_ID, "builtin", "xlsx")
        assert skill_id == "xlsx_001"

    def test_auto_generate_customized_with_creator(self):
        """用户自建技能：包含 creator_id 区分同租户不同用户."""
        skill_id = extract_skill_id(
            SAMPLE_MD_NO_SKILL_ID,
            "customized",
            "my_skill",
            creator_id="alice",
        )
        assert skill_id == "customized_alice_my_skill"

    def test_auto_generate_customized_without_creator(self):
        """用户自建技能：无 creator_id 时使用简化格式."""
        skill_id = extract_skill_id(
            SAMPLE_MD_NO_SKILL_ID,
            "customized",
            "my_skill",
        )
        assert skill_id == "customized_my_skill"

    def test_builtin_source_prefix(self):
        """内置技能的 skill_id 前缀."""
        md_content = "---\nname: pdf\n---\n# PDF处理"
        skill_id = extract_skill_id(md_content, "builtin", "pdf")
        assert skill_id == "builtin_pdf"

    def test_marketplace_source_uses_item_id(self):
        """市场分发技能：直接使用 item_id 作为 skill_id."""
        md_content = "---\nname: report\n---\n# 报表生成"
        skill_id = extract_skill_id(
            md_content,
            "marketplace:item_12345",
            "report",
        )
        assert skill_id == "item_12345"

    def test_empty_content_auto_generate(self):
        """空内容时自动生成 skill_id."""
        skill_id = extract_skill_id(
            "",
            "customized",
            "test_skill",
            creator_id="bob",
        )
        assert skill_id == "customized_bob_test_skill"

    def test_different_skill_names_different_ids(self):
        """不同技能名生成不同 skill_id."""
        md_content = "---\nname: skill\n---"
        skill_id_1 = extract_skill_id(
            md_content,
            "customized",
            "skill_a",
            creator_id="alice",
        )
        skill_id_2 = extract_skill_id(
            md_content,
            "customized",
            "skill_b",
            creator_id="alice",
        )
        assert skill_id_1 != skill_id_2
        assert skill_id_1 == "customized_alice_skill_a"
        assert skill_id_2 == "customized_alice_skill_b"

    def test_same_skill_name_different_creators(self):
        """同一技能名不同创建者生成不同 skill_id."""
        md_content = "---\nname: skill\n---"
        skill_id_alice = extract_skill_id(
            md_content,
            "customized",
            "data_analysis",
            creator_id="alice",
        )
        skill_id_bob = extract_skill_id(
            md_content,
            "customized",
            "data_analysis",
            creator_id="bob",
        )
        assert skill_id_alice != skill_id_bob
        assert skill_id_alice == "customized_alice_data_analysis"
        assert skill_id_bob == "customized_bob_data_analysis"

    def test_marketplace_distribution_consistent(self):
        """市场分发技能：所有接收者的 skill_id 一致."""
        md_content = "---\nname: report\n---"
        skill_id_1 = extract_skill_id(
            md_content,
            "marketplace:item_12345",
            "report",
        )
        skill_id_2 = extract_skill_id(
            md_content,
            "marketplace:item_12345",
            "report",
        )
        assert skill_id_1 == skill_id_2
        assert skill_id_1 == "item_12345"


class TestExtractCnNameFromTitle:
    """测试从一级标题提取 cn_name."""

    def test_extract_from_first_heading(self):
        """从一级标题提取中文名."""
        md_content = """---
name: xlsx
---
# Excel表格处理

这里是技能内容。
"""
        cn_name = extract_cn_name_from_title(md_content)
        assert cn_name == "Excel表格处理"

    def test_skip_secondary_heading(self):
        """二级标题不被识别为 cn_name."""
        md_content = """---
name: skill
---
## 这是二级标题
# 这是一级标题
"""
        cn_name = extract_cn_name_from_title(md_content)
        assert cn_name == "这是一级标题"

    def test_no_heading_returns_empty(self):
        """无标题时返回空串."""
        md_content = "---\nname: skill\n---\nSome content without heading."
        cn_name = extract_cn_name_from_title(md_content)
        assert cn_name == ""

    def test_empty_content_returns_empty(self):
        """空内容返回空串."""
        cn_name = extract_cn_name_from_title("")
        assert cn_name == ""

    def test_heading_with_whitespace(self):
        """标题前后有多余空格."""
        md_content = "---\nname: skill\n---\n#   带空格的标题  "
        cn_name = extract_cn_name_from_title(md_content)
        assert cn_name == "带空格的标题"

    def test_heading_after_frontmatter(self):
        """标题在 frontmatter 之后."""
        md_content = """---
name: skill
version: "1.0"
---
# 技能名称
"""
        cn_name = extract_cn_name_from_title(md_content)
        assert cn_name == "技能名称"


class TestSkillIdCrossTenantSharing:
    """测试 skill_id 跨租户共享特性."""

    def test_marketplace_distribution_consistent(self):
        """市场分发技能：不同租户接收者共享同一 skill_id（item_id）."""
        md_content = "---\nname: report\n---\n# 报表生成"
        # 不同租户的分发技能使用相同 skill_id（基于 item_id）
        skill_id_1 = extract_skill_id(
            md_content,
            "marketplace:item_12345",
            "report",
        )
        skill_id_2 = extract_skill_id(
            md_content,
            "marketplace:item_12345",
            "report",
        )
        assert skill_id_1 == skill_id_2 == "item_12345"

    def test_metadata_skill_id_tenant_independent(self):
        """metadata 中指定的 skill_id 与租户无关."""
        skill_id_1 = extract_skill_id(
            SAMPLE_MD_WITH_SKILL_ID,
            "builtin",
            "xlsx",
        )
        skill_id_2 = extract_skill_id(
            SAMPLE_MD_WITH_SKILL_ID,
            "marketplace:item_12345",
            "xlsx",
        )
        # 即使 source 不同，metadata 中的 skill_id 优先
        assert skill_id_1 == "xlsx_001"
        assert skill_id_2 == "xlsx_001"

    def test_customized_skills_per_user_unique(self):
        """用户自建技能：同租户不同用户的同名技能 skill_id 不同."""
        md_content = "---\nname: analysis\n---\n# 数据分析"
        skill_id_alice = extract_skill_id(
            md_content,
            "customized",
            "data_analysis",
            creator_id="alice",
        )
        skill_id_bob = extract_skill_id(
            md_content,
            "customized",
            "data_analysis",
            creator_id="bob",
        )
        # 同租户不同用户上传同名技能，skill_id 不同
        assert skill_id_alice != skill_id_bob
        assert skill_id_alice == "customized_alice_data_analysis"
        assert skill_id_bob == "customized_bob_data_analysis"
