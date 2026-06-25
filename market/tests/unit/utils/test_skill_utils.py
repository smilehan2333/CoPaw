# -*- coding: utf-8 -*-
"""测试 skill_utils 公共工具函数."""

import pytest

from market.utils.skill_utils import clean_skill_name, strip_quotes


class TestStripQuotes:
    """测试引号去除函数."""

    def test_strip_double_quotes(self):
        """去除双引号."""
        assert strip_quotes('"技能A"') == "技能A"

    def test_strip_single_quotes(self):
        """去除单引号."""
        assert strip_quotes("'技能B'") == "技能B"

    def test_no_quotes(self):
        """无引号时保持原样."""
        assert strip_quotes("技能C") == "技能C"

    def test_empty_string(self):
        """空字符串返回空."""
        assert strip_quotes("") == ""

    def test_only_quotes(self):
        """仅有引号返回空."""
        assert strip_quotes('""') == ""
        assert strip_quotes("''") == ""
        # 不匹配的引号类型保持原样
        assert strip_quotes("\"'") == "\"'"

    def test_quotes_with_spaces(self):
        """引号内有空格."""
        assert strip_quotes('" 技能D "') == "技能D"

    def test_outer_spaces(self):
        """外层有空格."""
        assert strip_quotes('  "技能E"  ') == "技能E"


class TestCleanSkillName:
    """测试技能名称清理函数."""

    def test_clean_quoted_name(self):
        """清理带引号的技能名."""
        assert clean_skill_name('"技能A-带版本号"') == "技能A-带版本号"

    def test_clean_single_quoted_name(self):
        """清理带单引号的技能名."""
        assert clean_skill_name("'技能B'") == "技能B"

    def test_clean_normal_name(self):
        """清理正常技能名."""
        assert clean_skill_name("技能C") == "技能C"

    def test_clean_name_with_spaces(self):
        """清理带空格的技能名."""
        assert clean_skill_name('  "技能D"  ') == "技能D"
