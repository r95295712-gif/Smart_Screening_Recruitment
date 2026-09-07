import json
import logging
import time

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from accounts.decorators import system_admin_required
from analysis.integrations.model import get_effective_model_settings
from analysis.models import GlobalModelConfig
from recruitment.services.common import record_audit

logger = logging.getLogger(__name__)


def _mask_key(key):
    if not key:
        return ""
    if len(key) <= 8:
        return "******"
    return f"{key[:4]}****{key[-4:]}"


@system_admin_required
def model_settings_view(request):
    if request.method == "POST":
        action = request.POST.get("config_action") or request.POST.get("action")
        if action == "reset":
            GlobalModelConfig.objects.filter(is_active=True).update(is_active=False)
            record_audit(request.user, "model_config.reset_to_env", None)
            messages.success(request, "已恢复使用系统默认 (.env) 模型配置。")
            return redirect("analysis:model_settings")

        # Save custom config
        base_url = request.POST.get("base_url", "").strip()
        api_key = request.POST.get("api_key", "").strip()
        model_name = request.POST.get("model_name", "").strip()

        if not base_url or not api_key or not model_name:
            messages.error(request, "请完善全部配置信息（接口地址、API Key 和模型名称均不能为空）。")
            return redirect("analysis:model_settings")

        GlobalModelConfig.objects.filter(is_active=True).update(is_active=False)
        new_config = GlobalModelConfig.objects.create(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            is_active=True,
            updated_by=request.user,
        )
        record_audit(
            request.user,
            "model_config.update",
            new_config,
            {"model_name": model_name, "base_url": base_url},
        )
        messages.success(
            request, f"模型配置已成功保存并应用！当前全局生效模型为：{model_name}"
        )
        return redirect("analysis:model_settings")

    effective = get_effective_model_settings()
    custom_active = GlobalModelConfig.get_active()

    env_config = {
        "base_url": settings.MODEL_BASE_URL or "",
        "api_key": settings.MODEL_API_KEY or "",
        "api_key_masked": _mask_key(settings.MODEL_API_KEY),
        "model_name": settings.MODEL_NAME or "",
    }

    return render(
        request,
        "analysis/model_settings.html",
        {
            "effective": effective,
            "effective_masked_key": _mask_key(effective["api_key"]),
            "custom_active": custom_active,
            "custom_masked_key": _mask_key(custom_active.api_key) if custom_active else "",
            "env_config": env_config,
        },
    )


@system_admin_required
def model_ping_api(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        data = {}

    base_url = data.get("base_url", "").strip()
    api_key = data.get("api_key", "").strip()
    model_name = data.get("model_name", "").strip()

    is_all_empty = (not base_url and not api_key and not model_name)
    is_partially_filled = not is_all_empty and (not base_url or not api_key or not model_name)

    if is_partially_filled:
        return JsonResponse(
            {
                "ok": False,
                "code": "incomplete_fields",
                "message": "请完善全部配置信息（接口地址、API Key 和模型名称均不能为空）。",
            },
            status=400,
        )

    if is_all_empty:
        is_default = True
        base_url = settings.MODEL_BASE_URL or ""
        api_key = settings.MODEL_API_KEY or ""
        model_name = settings.MODEL_NAME or ""
        if not api_key or not model_name:
            return JsonResponse(
                {
                    "ok": False,
                    "message": "系统默认 (.env) 配置尚未完整配置 MODEL_API_KEY 或 MODEL_NAME。",
                },
                status=400,
            )
    else:
        is_default = False

    t0 = time.perf_counter()
    client = OpenAI(
        api_key=api_key,
        base_url=base_url or None,
        timeout=15.0,
        max_retries=0,
    )

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "1+1=?"}],
            max_tokens=5,
        )
        latency_ms = max(1, round((time.perf_counter() - t0) * 1000))
        return JsonResponse(
            {
                "ok": True,
                "latency_ms": latency_ms,
                "is_default": is_default,
                "model_name": model_name,
                "base_url": base_url,
                "message": f"连接成功！往返耗时: {latency_ms} ms",
            }
        )
    except APITimeoutError:
        latency_ms = round((time.perf_counter() - t0) * 1000)
        return JsonResponse(
            {
                "ok": False,
                "latency_ms": latency_ms,
                "is_default": is_default,
                "model_name": model_name,
                "message": f"连接超时（超过 15 秒无响应），上游通道可能不可用或网络异常。",
            }
        )
    except AuthenticationError:
        return JsonResponse(
            {
                "ok": False,
                "is_default": is_default,
                "model_name": model_name,
                "message": "认证失败（401），请检查 API Key 是否有效。",
            }
        )
    except NotFoundError:
        return JsonResponse(
            {
                "ok": False,
                "is_default": is_default,
                "model_name": model_name,
                "message": f"模型“{model_name}”不存在，或当前 API Key 无权访问该模型。",
            }
        )
    except APIStatusError as exc:
        return JsonResponse(
            {
                "ok": False,
                "is_default": is_default,
                "model_name": model_name,
                "message": f"服务返回错误（HTTP {exc.status_code}）: {exc.message}",
            }
        )
    except APIConnectionError:
        return JsonResponse(
            {
                "ok": False,
                "is_default": is_default,
                "model_name": model_name,
                "message": f"无法连接目标地址（{base_url}），请检查网络连接或地址是否正确。",
            }
        )
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "is_default": is_default,
                "model_name": model_name,
                "message": f"测试失败: {str(exc)}",
            }
        )
