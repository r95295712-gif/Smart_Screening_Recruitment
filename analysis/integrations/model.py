import json
import logging

from django.conf import settings
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)


logger = logging.getLogger(__name__)


class ModelConfigurationError(RuntimeError):
    pass


class ModelServiceError(RuntimeError):
    pass


class ModelGateway:
    def __init__(self, client=None):
        self.client = client

    def ensure_configured(self):
        if not settings.MODEL_API_KEY or not settings.MODEL_NAME:
            raise ModelConfigurationError("尚未配置 MODEL_API_KEY 和 MODEL_NAME。")

    def analyze(self, system_prompt, user_prompt):
        self.ensure_configured()
        client = self.client or OpenAI(
            api_key=settings.MODEL_API_KEY,
            base_url=settings.MODEL_BASE_URL or None,
            timeout=settings.MODEL_REQUEST_TIMEOUT,
            max_retries=0,
        )
        try:
            response = client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            usage = getattr(response, "usage", None)
            return {
                "payload": json.loads(content),
                "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            }
        except AuthenticationError as exc:
            logger.exception("Model service authentication failed.")
            raise ModelServiceError(
                "智能分析服务认证失败，请联系管理员检查模型配置。"
            ) from exc
        except RateLimitError as exc:
            logger.exception("Model service rate limit reached.")
            raise ModelServiceError(
                "智能分析服务当前请求较多，请稍后重试。"
            ) from exc
        except APITimeoutError as exc:
            logger.exception("Model service request timed out.")
            raise ModelServiceError(
                "智能分析服务响应超时，请稍后重试。"
            ) from exc
        except APIConnectionError as exc:
            logger.exception("Model service connection failed.")
            raise ModelServiceError(
                "暂时无法连接智能分析服务，请稍后重试；"
                "如果持续出现，请联系管理员检查本地服务的网络权限。"
            ) from exc
        except APIStatusError as exc:
            logger.exception("Model service returned an error response.")
            raise ModelServiceError(
                "智能分析服务暂时不可用，请稍后重试。"
            ) from exc
        except (json.JSONDecodeError, AttributeError, IndexError, TypeError) as exc:
            logger.exception("Model service returned an invalid response.")
            raise ModelServiceError(
                "智能分析服务返回内容暂时无法使用，请稍后重试。"
            ) from exc
        except OpenAIError as exc:
            logger.exception("Unexpected model service error.")
            raise ModelServiceError(
                "智能分析服务暂时不可用，请稍后重试。"
            ) from exc
