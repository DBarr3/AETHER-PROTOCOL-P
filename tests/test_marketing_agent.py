"""
AetherCloud-L — Marketing Agent Tests
Tests for marketing/content skills added to AetherClaudeAgent.
All API calls are mocked — no real Claude calls.
"""

import json
import pytest
from unittest.mock import patch, MagicMock


def _make_mock_response(text: str) -> MagicMock:
    """Create a mock Claude API response."""
    mock_resp = MagicMock()
    mock_content = MagicMock()
    mock_content.text = text
    mock_resp.content = [mock_content]
    return mock_resp


# ═══════════════════════════════════════════════════
# COMPETITIVE CARD TESTS
# ═══════════════════════════════════════════════════

class TestCreateCompetitiveCard:
    @pytest.fixture
    def mock_anthropic(self):
        with patch("agent.claude_agent.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def agent(self, mock_anthropic):
        from agent.claude_agent import AetherClaudeAgent
        return AetherClaudeAgent(api_key="test-key-123")

    def test_returns_valid_structure(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "product": "AetherCloud-L",
                "competitors": ["Dropbox", "Box"],
                "differentiators": [
                    {"feature": "Quantum signing", "us": "Yes", "them": "No", "verdict": "WIN"}
                ],
                "summary": "AetherCloud-L leads in security",
                "confidence": 0.9,
            })
        )
        result = agent.create_competitive_card("AetherCloud-L", ["Dropbox", "Box"])
        assert result["product"] == "AetherCloud-L"
        assert len(result["differentiators"]) == 1
        assert result["confidence"] == 0.9

    def test_with_features_filter(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "product": "AetherCloud-L",
                "competitors": ["Box"],
                "differentiators": [],
                "summary": "Focused analysis",
                "confidence": 0.85,
            })
        )
        result = agent.create_competitive_card(
            "AetherCloud-L", ["Box"], features=["encryption", "audit"]
        )
        assert result["confidence"] == 0.85

    def test_api_failure_returns_fallback(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("API error")
        result = agent.create_competitive_card("AetherCloud-L", ["Dropbox"])
        assert result["confidence"] == 0.0
        assert "unavailable" in result["summary"].lower() or "error" in result["summary"].lower()

    def test_empty_competitors_list(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "product": "AetherCloud-L",
                "competitors": [],
                "differentiators": [],
                "summary": "No competitors specified",
                "confidence": 0.5,
            })
        )
        result = agent.create_competitive_card("AetherCloud-L", [])
        assert result["competitors"] == []

    def test_markdown_fences_stripped(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            '```json\n{"product": "X", "competitors": [], "differentiators": [], '
            '"summary": "test", "confidence": 0.7}\n```'
        )
        result = agent.create_competitive_card("X", [])
        assert result["product"] == "X"

    def test_verdict_values(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "product": "AetherCloud-L",
                "competitors": ["Rival"],
                "differentiators": [
                    {"feature": "A", "us": "Yes", "them": "Yes", "verdict": "TIE"},
                    {"feature": "B", "us": "Yes", "them": "No", "verdict": "WIN"},
                    {"feature": "C", "us": "No", "them": "Yes", "verdict": "LOSE"},
                ],
                "summary": "Mixed results",
                "confidence": 0.8,
            })
        )
        result = agent.create_competitive_card("AetherCloud-L", ["Rival"])
        verdicts = [d["verdict"] for d in result["differentiators"]]
        assert set(verdicts) == {"TIE", "WIN", "LOSE"}


# ═══════════════════════════════════════════════════
# CONTENT DRAFT TESTS
# ═══════════════════════════════════════════════════

class TestDraftContent:
    @pytest.fixture
    def mock_anthropic(self):
        with patch("agent.claude_agent.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def agent(self, mock_anthropic):
        from agent.claude_agent import AetherClaudeAgent
        return AetherClaudeAgent(api_key="test-key-123")

    def test_blog_draft(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "content_type": "blog",
                "title": "Why Quantum Security Matters",
                "body": "Full blog text...",
                "cta": "Try AetherCloud-L free",
                "seo_keywords": ["quantum", "security"],
                "tone": "professional",
                "word_count": 800,
                "confidence": 0.88,
            })
        )
        result = agent.draft_content("blog", "Quantum Security")
        assert result["content_type"] == "blog"
        assert result["word_count"] == 800

    def test_linkedin_post(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "content_type": "linkedin",
                "title": "Post title",
                "body": "Hook + insight + CTA",
                "cta": "Link in comments",
                "seo_keywords": [],
                "tone": "conversational",
                "word_count": 150,
                "confidence": 0.9,
            })
        )
        result = agent.draft_content("linkedin", "Product launch", audience="CTOs")
        assert result["content_type"] == "linkedin"

    def test_with_tone_parameter(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "content_type": "press_release",
                "title": "PR",
                "body": "Text",
                "cta": "",
                "seo_keywords": [],
                "tone": "formal",
                "word_count": 400,
                "confidence": 0.85,
            })
        )
        result = agent.draft_content("press_release", "Launch", tone="formal")
        assert result["tone"] == "formal"

    def test_api_failure_returns_fallback(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("Timeout")
        result = agent.draft_content("blog", "Test Topic")
        assert result["confidence"] == 0.0
        assert result["word_count"] == 0

    def test_seo_keywords_present(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "content_type": "blog",
                "title": "Test",
                "body": "Body",
                "cta": "CTA",
                "seo_keywords": ["quantum", "security", "AI"],
                "tone": "technical",
                "word_count": 600,
                "confidence": 0.87,
            })
        )
        result = agent.draft_content("blog", "Security")
        assert len(result["seo_keywords"]) == 3


# ═══════════════════════════════════════════════════
# EMAIL SEQUENCE TESTS
# ═══════════════════════════════════════════════════

class TestDraftEmailSequence:
    @pytest.fixture
    def mock_anthropic(self):
        with patch("agent.claude_agent.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def agent(self, mock_anthropic):
        from agent.claude_agent import AetherClaudeAgent
        return AetherClaudeAgent(api_key="test-key-123")

    def test_welcome_sequence(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "sequence_name": "welcome",
                "emails": [
                    {"day": 0, "subject": "Welcome!", "preview_text": "Get started",
                     "body": "Welcome email body", "cta": "Open dashboard"},
                    {"day": 2, "subject": "Feature spotlight", "preview_text": "Did you know",
                     "body": "Feature body", "cta": "Try it now"},
                ],
                "total_emails": 2,
                "confidence": 0.85,
            })
        )
        result = agent.draft_email_sequence("welcome", "AetherCloud-L", num_emails=2)
        assert result["total_emails"] == 2
        assert len(result["emails"]) == 2
        assert result["emails"][0]["day"] == 0

    def test_custom_email_count(self, agent, mock_anthropic):
        emails = [{"day": i, "subject": f"Email {i}", "preview_text": "",
                    "body": "", "cta": ""} for i in range(3)]
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "sequence_name": "launch",
                "emails": emails,
                "total_emails": 3,
                "confidence": 0.82,
            })
        )
        result = agent.draft_email_sequence("launch", "Product", num_emails=3)
        assert result["total_emails"] == 3

    def test_api_failure_returns_empty(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("Error")
        result = agent.draft_email_sequence("welcome", "Product")
        assert result["emails"] == []
        assert result["total_emails"] == 0
        assert result["confidence"] == 0.0

    def test_with_audience(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "sequence_name": "enterprise",
                "emails": [{"day": 0, "subject": "For CISOs", "preview_text": "",
                             "body": "", "cta": ""}],
                "total_emails": 1,
                "confidence": 0.9,
            })
        )
        result = agent.draft_email_sequence(
            "enterprise", "AetherCloud-L", audience="CISOs"
        )
        assert result["sequence_name"] == "enterprise"

    def test_email_has_required_fields(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "sequence_name": "test",
                "emails": [{"day": 1, "subject": "Sub", "preview_text": "Pre",
                             "body": "Body", "cta": "Click"}],
                "total_emails": 1,
                "confidence": 0.88,
            })
        )
        result = agent.draft_email_sequence("test", "Product")
        email = result["emails"][0]
        assert "day" in email
        assert "subject" in email
        assert "preview_text" in email
        assert "body" in email
        assert "cta" in email


# ═══════════════════════════════════════════════════
# CONTENT REVIEW TESTS
# ═══════════════════════════════════════════════════

class TestReviewContent:
    @pytest.fixture
    def mock_anthropic(self):
        with patch("agent.claude_agent.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def agent(self, mock_anthropic):
        from agent.claude_agent import AetherClaudeAgent
        return AetherClaudeAgent(api_key="test-key-123")

    def test_review_returns_grade(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "readability_score": 72.5,
                "accuracy_issues": [],
                "unsupported_claims": [],
                "cta_suggestions": ["Add specific demo link"],
                "revised_content": "Improved text here",
                "overall_grade": "B",
                "confidence": 0.88,
            })
        )
        result = agent.review_content("Some marketing text here")
        assert result["overall_grade"] == "B"
        assert result["readability_score"] == 72.5

    def test_review_flags_unsupported_claims(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "readability_score": 65.0,
                "accuracy_issues": ["Claim about 100% uptime is unverified"],
                "unsupported_claims": ["best in the world"],
                "cta_suggestions": [],
                "revised_content": "Revised text",
                "overall_grade": "C",
                "confidence": 0.82,
            })
        )
        result = agent.review_content("We are the best in the world with 100% uptime")
        assert len(result["unsupported_claims"]) > 0
        assert result["overall_grade"] == "C"

    def test_review_with_audience(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "readability_score": 80.0,
                "accuracy_issues": [],
                "unsupported_claims": [],
                "cta_suggestions": [],
                "revised_content": "text",
                "overall_grade": "A",
                "confidence": 0.9,
            })
        )
        result = agent.review_content("Tech copy", audience="developers")
        assert result["overall_grade"] == "A"

    def test_review_api_failure(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("API down")
        result = agent.review_content("Some text")
        assert result["overall_grade"] == "F"
        assert result["confidence"] == 0.0

    def test_review_preserves_original_on_failure(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("Error")
        original = "Original marketing text"
        result = agent.review_content(original)
        assert result["revised_content"] == original


# ═══════════════════════════════════════════════════
# POSITIONING TESTS
# ═══════════════════════════════════════════════════

class TestDevelopPositioning:
    @pytest.fixture
    def mock_anthropic(self):
        with patch("agent.claude_agent.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def agent(self, mock_anthropic):
        from agent.claude_agent import AetherClaudeAgent
        return AetherClaudeAgent(api_key="test-key-123")

    def test_positioning_returns_framework(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "category": "Quantum-Secured File Intelligence",
                "value_proposition": "Dispute-proof chain of custody",
                "icp": {"title": "CISO", "company_size": "100-1000",
                         "pain_points": ["compliance", "audit trails"]},
                "messaging_hierarchy": {
                    "primary": "Every file decision is cryptographically proven",
                    "supporting": ["Zero file leakage", "Patent-pending Protocol-L"],
                },
                "competitive_moat": ["Quantum entropy", "Protocol-L patents"],
                "confidence": 0.92,
            })
        )
        result = agent.develop_positioning("AetherCloud-L", "enterprise security")
        assert "value_proposition" in result
        assert result["confidence"] == 0.92
        assert len(result["competitive_moat"]) == 2

    def test_with_competitors(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "category": "File Security",
                "value_proposition": "Test",
                "icp": {"title": "", "company_size": "", "pain_points": []},
                "messaging_hierarchy": {"primary": "", "supporting": []},
                "competitive_moat": ["Patent"],
                "confidence": 0.85,
            })
        )
        result = agent.develop_positioning(
            "AetherCloud-L", "security", competitors=["Box", "Dropbox"]
        )
        assert result["confidence"] == 0.85

    def test_api_failure_returns_fallback(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("Error")
        result = agent.develop_positioning("AetherCloud-L", "security")
        assert result["confidence"] == 0.0
        assert result["category"] == "security"

    def test_icp_structure(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "category": "SaaS",
                "value_proposition": "VP",
                "icp": {"title": "VP Engineering", "company_size": "50-500",
                         "pain_points": ["slow audits", "compliance gaps"]},
                "messaging_hierarchy": {"primary": "Main", "supporting": ["A"]},
                "competitive_moat": [],
                "confidence": 0.87,
            })
        )
        result = agent.develop_positioning("Product", "SaaS security")
        icp = result["icp"]
        assert "title" in icp
        assert "company_size" in icp
        assert "pain_points" in icp
        assert len(icp["pain_points"]) == 2

    def test_messaging_hierarchy(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "category": "Security",
                "value_proposition": "VP",
                "icp": {"title": "", "company_size": "", "pain_points": []},
                "messaging_hierarchy": {
                    "primary": "Main message",
                    "supporting": ["Support 1", "Support 2", "Support 3"],
                },
                "competitive_moat": [],
                "confidence": 0.88,
            })
        )
        result = agent.develop_positioning("Product", "Security")
        hierarchy = result["messaging_hierarchy"]
        assert "primary" in hierarchy
        assert "supporting" in hierarchy
        assert len(hierarchy["supporting"]) == 3


# ═══════════════════════════════════════════════════
# QOPC MARKETING OUTCOME TESTS
# ═══════════════════════════════════════════════════

class TestQOPCMarketingOutcomes:
    def test_published_outcome_score(self):
        from agent.qopc_feedback import OutcomeObserver
        assert OutcomeObserver.OUTCOME_SCORES["PUBLISHED"] == 1.0

    def test_revised_outcome_score(self):
        from agent.qopc_feedback import OutcomeObserver
        assert OutcomeObserver.OUTCOME_SCORES["REVISED"] == 0.6

    def test_discarded_outcome_score(self):
        from agent.qopc_feedback import OutcomeObserver
        assert OutcomeObserver.OUTCOME_SCORES["DISCARDED"] == 0.0

    def test_ab_tested_outcome_score(self):
        from agent.qopc_feedback import OutcomeObserver
        assert OutcomeObserver.OUTCOME_SCORES["A_B_TESTED"] == 0.8

    def test_all_outcomes_present(self):
        from agent.qopc_feedback import OutcomeObserver
        required = {"ACCEPTED", "REJECTED", "CORRECTED", "IGNORED",
                     "PUBLISHED", "REVISED", "DISCARDED", "A_B_TESTED"}
        assert required == set(OutcomeObserver.OUTCOME_SCORES.keys())


# ═══════════════════════════════════════════════════
# PROMPT OPTIMIZER MARKETING VARIANT TESTS
# ═══════════════════════════════════════════════════

class TestPromptOptimizerMarketingVariants:
    def test_competitive_variant_exists(self):
        from agent.qopc_feedback import PromptOptimizer
        opt = PromptOptimizer()
        assert "COMPETITIVE_CARD" in opt.variants
        assert len(opt.variants["COMPETITIVE_CARD"]) >= 1

    def test_content_variant_exists(self):
        from agent.qopc_feedback import PromptOptimizer
        opt = PromptOptimizer()
        assert "CONTENT_DRAFT" in opt.variants

    def test_email_variant_exists(self):
        from agent.qopc_feedback import PromptOptimizer
        opt = PromptOptimizer()
        assert "EMAIL_SEQUENCE" in opt.variants

    def test_review_variant_exists(self):
        from agent.qopc_feedback import PromptOptimizer
        opt = PromptOptimizer()
        assert "CONTENT_REVIEW" in opt.variants

    def test_positioning_variant_exists(self):
        from agent.qopc_feedback import PromptOptimizer
        opt = PromptOptimizer()
        assert "POSITIONING" in opt.variants

    def test_select_marketing_variant(self):
        from agent.qopc_feedback import PromptOptimizer
        opt = PromptOptimizer()
        variant = opt.select_variant("COMPETITIVE_CARD")
        assert variant.task_type == "COMPETITIVE_CARD"
        assert variant.accuracy_score == 0.8


# ═══════════════════════════════════════════════════
# TASK SUFFIX REGISTRY TESTS
# ═══════════════════════════════════════════════════

class TestTaskSuffixes:
    def test_competitive_suffix_registered(self):
        from config.agent_prompt import TASK_SUFFIXES
        assert "COMPETITIVE_CARD" in TASK_SUFFIXES

    def test_content_suffix_registered(self):
        from config.agent_prompt import TASK_SUFFIXES
        assert "CONTENT_DRAFT" in TASK_SUFFIXES

    def test_email_suffix_registered(self):
        from config.agent_prompt import TASK_SUFFIXES
        assert "EMAIL_SEQUENCE" in TASK_SUFFIXES

    def test_review_suffix_registered(self):
        from config.agent_prompt import TASK_SUFFIXES
        assert "CONTENT_REVIEW" in TASK_SUFFIXES

    def test_positioning_suffix_registered(self):
        from config.agent_prompt import TASK_SUFFIXES
        assert "POSITIONING" in TASK_SUFFIXES

    def test_all_suffixes_are_strings(self):
        from config.agent_prompt import TASK_SUFFIXES
        for key, val in TASK_SUFFIXES.items():
            assert isinstance(val, str), f"{key} suffix is not a string"

    def test_total_suffix_count(self):
        from config.agent_prompt import TASK_SUFFIXES
        # 4 original + 5 marketing = 9
        assert len(TASK_SUFFIXES) == 9
