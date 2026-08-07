"""Test Chinese Disclosure Validator."""
import pytest
from patent_agent.document.chinese_validator import (
    ChineseDisclosureValidator,
    validate_chinese_disclosure,
)


class TestChineseDisclosureValidator:
    def test_valid_chinese_sections_pass(self):
        sections = [
            {"title": "发明名称", "paragraphs": [{"text": "一种基于深度学习的技术方案。"}]},
            {"title": "技术领域", "paragraphs": [{"text": "本发明涉及人工智能技术领域。"}]},
            {"title": "背景技术", "paragraphs": [{"text": "现有技术中存在诸多问题。"}]},
            {"title": "技术方案", "paragraphs": [{"text": "本技术方案提供一种方法，包括以下步骤：S1：获取数据；S2：处理数据。"}]},
            {"title": "有益效果", "paragraphs": [{"text": "本方案能够有效提升系统性能。"}]},
            {"title": "具体实施方式", "paragraphs": [{"text": "在一实施方式中，使用神经网络进行训练。"}]},
        ]
        result = ChineseDisclosureValidator().validate_text(sections)
        assert result.overall in ("PASS", "NEEDS_REVIEW"), f"Expected PASS or NEEDS_REVIEW, got {result.overall}: {result.issues}"
        assert result.chinese_title_check == "PASS", f"Title check failed: {result.issues}"

    def test_english_section_title_detected(self):
        sections = [
            {"title": "Technical Field", "paragraphs": [{"text": "本发明涉及..."}]},
            {"title": "Background", "paragraphs": [{"text": "现有技术..."}]},
        ]
        result = ChineseDisclosureValidator().validate_text(sections)
        assert result.chinese_title_check == "FAIL", f"Expected FAIL for English titles, got {result.chinese_title_check}"
        assert any("英文章节标题残留" in i for i in result.issues), f"Expected English title issue: {result.issues}"

    def test_academic_tone_detected(self):
        sections = [
            {"title": "发明名称", "paragraphs": [
                {"text": "本文提出了一种新的方法。我们设计了创新的架构。本研究表明该方法有效。"}
            ]},
        ]
        result = ChineseDisclosureValidator().validate_text(sections)
        assert len(result.academic_tone_issues) > 0, f"Expected academic tone issues: {result.issues}"

    def test_chinese_ratio_high_for_fully_chinese(self):
        text = "本发明提供一种基于潜在扩散模型的电机拓扑图像生成方法，包括以下步骤：首先获取数据，然后进行处理，最后输出结果。其中λ表示插值系数。"
        ratio = ChineseDisclosureValidator()._chinese_ratio(text)
        assert ratio > 0.8, f"Expected high Chinese ratio, got {ratio}"

    def test_chinese_ratio_low_for_english(self):
        text = "This invention provides a method for generating motor topology images based on latent diffusion models. The method includes the following steps."
        ratio = ChineseDisclosureValidator()._chinese_ratio(text)
        assert ratio < 0.3, f"Expected low Chinese ratio for English text, got {ratio}"

    def test_english_blocks_detected(self):
        text = "本发明涉及一种技术方案。\n\n" + "The proposed method leverages a novel architecture based on deep neural networks which significantly improves the performance metrics across all evaluated benchmarks.\n\n" + "以上为本发明的技术方案。"
        blocks = ChineseDisclosureValidator()._find_english_blocks(text)
        assert len(blocks) >= 1, f"Expected English blocks detected, got {len(blocks)}"

    def test_acceptable_abbreviations_not_flagged(self):
        text = "本方案使用GAN和VAE进行图像生成，并通过U-Net网络进行特征提取。模型使用Adam优化器和ReLU激活函数。"
        blocks = ChineseDisclosureValidator()._find_english_blocks(text)
        assert len(blocks) == 0, f"Acceptable abbreviations should not be flagged: {blocks}"

    def test_patent_style_clean(self):
        sections = [
            {"title": "发明名称", "paragraphs": [{"text": "本技术方案提出一种方法，在一实施方式中，实验结果表明该方案有效。"}]},
        ]
        result = ChineseDisclosureValidator().validate_text(sections)
        # "实验结果表明" is flagged as academic tone but is acceptable in implementation section
        # The overall should not be FAIL for a single issue
        assert result.overall != "FAIL", f"Expected not FAIL: {result.overall}"

    def test_convenience_function(self):
        sections = [{"title": "测试", "paragraphs": [{"text": "中文内容。"}]}]
        result = validate_chinese_disclosure(sections)
        assert "overall" in result
        assert "chinese_title_check" in result
        assert "chinese_body_ratio" in result
        assert "issues" in result


class TestDisclosureOnlyConfig:
    """Test that APP_MODE=disclosure_only config is respected."""

    def test_app_mode_reads_disclosure_only(self):
        from patent_agent.core.config import Settings
        import os
        settings = Settings.load()
        assert settings.app_mode in ("disclosure_only", "full_patent"), \
            f"Expected disclosure_only or full_patent, got {settings.app_mode}"
