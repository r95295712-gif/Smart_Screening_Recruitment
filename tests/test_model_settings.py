from unittest.mock import MagicMock, patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.integrations.model import ModelGateway, get_effective_model_settings
from analysis.models import GlobalModelConfig


class ModelSettingsAndPingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="test_model_admin",
            password="password123",
            role=User.Role.ADMIN,
            must_change_password=False,
        )
        self.hr = User.objects.create_user(
            username="test_model_hr",
            password="password123",
            role=User.Role.HR,
            must_change_password=False,
        )
        self.admin_client = self._authenticated_client(self.admin)
        self.hr_client = self._authenticated_client(self.hr)

    def _authenticated_client(self, user):
        client = Client()
        client.force_login(user)
        session = client.session
        session["auth_session_version"] = user.session_version
        session["last_activity_at"] = timezone.now().timestamp()
        session["login_started_at"] = timezone.now().timestamp()
        session.save()
        return client

    def test_permissions(self):
        # HR should be redirected to dashboard
        resp = self.hr_client.get(reverse("analysis:model_settings"))
        self.assertRedirects(resp, reverse("dashboard"))

        ping_resp = self.hr_client.post(
            reverse("analysis:model_ping_api"),
            data="{}",
            content_type="application/json",
        )
        self.assertRedirects(ping_resp, reverse("dashboard"))

    def test_model_ping_partially_filled_fails(self):
        # Only base_url provided -> should fail
        resp = self.admin_client.post(
            reverse("analysis:model_ping_api"),
            data='{"base_url": "https://api.example.com/v1"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("请完善全部配置信息", data["message"])

    @patch("analysis.views_settings.OpenAI")
    def test_model_ping_all_empty_uses_default_env(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        resp = self.admin_client.post(
            reverse("analysis:model_ping_api"),
            data='{"base_url": "", "api_key": "", "model_name": ""}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["is_default"])
        self.assertIn("latency_ms", data)
        mock_client.chat.completions.create.assert_called_once()

    @patch("analysis.views_settings.OpenAI")
    def test_model_ping_custom_success(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        resp = self.admin_client.post(
            reverse("analysis:model_ping_api"),
            data='{"base_url": "https://custom.ai.com/v1", "api_key": "sk-custom-123", "model_name": "custom-gpt"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["is_default"])
        self.assertEqual(data["model_name"], "custom-gpt")

    def test_save_and_reset_custom_config(self):
        # 1. Initial state: env config
        eff = get_effective_model_settings()
        self.assertEqual(eff["source"], "env")

        # 2. Admin saves custom config
        save_resp = self.admin_client.post(
            reverse("analysis:model_settings"),
            data={
                "config_action": "save",
                "base_url": "https://new-api.com/v1",
                "api_key": "sk-new-key-12345",
                "model_name": "gpt-5.6-luna",
            },
        )
        self.assertEqual(save_resp.status_code, 302)

        # Verify DB and effective settings
        active_config = GlobalModelConfig.get_active()
        self.assertIsNotNone(active_config)
        self.assertEqual(active_config.model_name, "gpt-5.6-luna")
        self.assertEqual(active_config.base_url, "https://new-api.com/v1")
        self.assertEqual(active_config.api_key, "sk-new-key-12345")

        eff_after_save = get_effective_model_settings()
        self.assertEqual(eff_after_save["source"], "custom")
        self.assertEqual(eff_after_save["model_name"], "gpt-5.6-luna")
        self.assertEqual(eff_after_save["base_url"], "https://new-api.com/v1")
        self.assertEqual(eff_after_save["api_key"], "sk-new-key-12345")

        # 3. GET page shows custom config
        page_resp = self.admin_client.get(reverse("analysis:model_settings"))
        self.assertEqual(page_resp.status_code, 200)
        self.assertContains(page_resp, "管理员自定义覆盖")
        self.assertContains(page_resp, "gpt-5.6-luna")

        # 4. Admin resets to default (.env)
        reset_resp = self.admin_client.post(
            reverse("analysis:model_settings"),
            data={"action": "reset"},
        )
        self.assertEqual(reset_resp.status_code, 302)

        eff_after_reset = get_effective_model_settings()
        self.assertEqual(eff_after_reset["source"], "env")
        self.assertFalse(GlobalModelConfig.objects.filter(is_active=True).exists())
