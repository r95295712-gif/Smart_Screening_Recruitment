import json
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from django.conf import settings


class ITalentConfigurationError(RuntimeError):
    pass


class ITalentAPIError(RuntimeError):
    def __init__(self, message, *, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass
class AccessToken:
    value: str
    expires_at: float


class RateLimiter:
    def __init__(self, requests_per_second=18):
        self.minimum_interval = 1 / requests_per_second
        self.lock = threading.Lock()
        self.last_request = 0.0

    def wait(self):
        with self.lock:
            elapsed = time.monotonic() - self.last_request
            if elapsed < self.minimum_interval:
                time.sleep(self.minimum_interval - elapsed)
            self.last_request = time.monotonic()


class ITalentClient:
    token_endpoint = "/token"
    applicant_ids_endpoint = "/RecruitV6/api/v1/Applicant/GetApplicantIdsByDate"
    profile_endpoint = "/RecruitV6/api/v1/Applicant/GetPersonProfileList"
    resume_module_endpoint = "/RecruitV6/api/v1/Applicant/GetResumeModuleList"
    standard_resume_endpoint = "/RecruitV6/api/v1/Applicant/GetResumeByApplyId"
    standard_file_endpoint = "/RecruitV6/api/v1/Applicant/GetStandardResumeFileUrl"
    origin_file_endpoint = "/RecruitV6/api/v1/Applicant/GetOriginResumeFileUrl"

    def __init__(self, *, client=None):
        self.base_url = settings.ITALENT_BASE_URL.rstrip("/")
        self.app_key = settings.ITALENT_APP_KEY
        self.app_secret = settings.ITALENT_APP_SECRET
        self.http = client or httpx.Client(base_url=self.base_url, timeout=30)
        self.rate_limiter = RateLimiter()
        self._token = None

    def ensure_configured(self):
        if not self.app_key or not self.app_secret:
            raise ITalentConfigurationError("尚未配置北森 ITALENT_APP_KEY/ITALENT_APP_SECRET。")

    def get_token(self):
        self.ensure_configured()
        if self._token and self._token.expires_at > time.time() + 60:
            return self._token.value
        response = self.http.post(
            self.token_endpoint,
            json={
                "grant_type": "client_credentials",
                "app_key": self.app_key,
                "app_secret": self.app_secret,
            },
        )
        payload = self._decode(response)
        token = payload.get("access_token") or payload.get("data", {}).get("access_token")
        if not token:
            raise ITalentAPIError("北森 Token 响应缺少 access_token。", payload=payload)
        expires_in = int(payload.get("expires_in") or 7200)
        self._token = AccessToken(token, time.time() + expires_in)
        return token

    def request(self, method, endpoint, *, json=None, params=None, retries=3):
        if not endpoint:
            raise ITalentConfigurationError("北森接口地址尚未配置。")
        last_error = None
        for attempt in range(retries):
            self.rate_limiter.wait()
            try:
                token = self.get_token()
                response = self.http.request(
                    method,
                    endpoint,
                    json=json,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code == 401 and attempt == 0:
                    self._token = None
                    continue
                if response.status_code >= 500 or response.status_code == 417:
                    raise ITalentAPIError(
                        f"北森接口返回 {response.status_code}",
                        status_code=response.status_code,
                        payload=self._decode(response, allow_error=True),
                    )
                return self._decode(response)
            except (httpx.HTTPError, ITalentAPIError) as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(2**attempt)
        raise last_error

    def _decode(self, response, allow_error=False):
        try:
            payload = response.json()
        except ValueError as exc:
            try:
                payload = json.loads(response.text, strict=False)
            except ValueError as fallback_exc:
                raise ITalentAPIError(
                    "北森接口返回无法解析的 JSON 内容。",
                    status_code=response.status_code,
                ) from fallback_exc
        if response.is_error and not allow_error:
            raise ITalentAPIError(
                payload.get("message") or f"北森接口返回 {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    def iter_applicant_ids(self, start_time, end_time, time_type=2):
        batch_id = ""
        while True:
            payload = self.request(
                "POST",
                self.applicant_ids_endpoint,
                json={
                    "startTime": start_time.isoformat(),
                    "endTime": end_time.isoformat(),
                    "timeType": time_type,
                    "batchId": batch_id,
                },
            )
            data = payload.get("data", payload)
            applicant_ids = (
                data.get("applicantIds")
                or data.get("ids")
                or data.get("items")
                or []
            )
            yield [str(item.get("applicantId") if isinstance(item, dict) else item) for item in applicant_ids]
            if data.get("isLastBatch") is True:
                break
            batch_id = data.get("nextBatchId")
            if not batch_id:
                raise ITalentAPIError("北森批次未结束但缺少 nextBatchId。", payload=payload)

    def get_profiles(self, applicant_ids):
        return self.request("POST", self.profile_endpoint, json={"applicantIds": applicant_ids})

    def get_resume_module(self, applicant_ids, module_code):
        return self.request(
            "POST",
            self.resume_module_endpoint,
            json={"applicantIds": applicant_ids, "moduleCode": module_code},
        )

    def get_applications(self, applicant_ids):
        return self.request(
            "POST",
            settings.ITALENT_APPLICATIONS_ENDPOINT,
            json={
                "applicantIds": applicant_ids,
                "fieldNames": settings.ITALENT_APPLICATION_FIELDS,
            },
        )

    def get_resume_file_info(self, applicant_id, *, origin=True):
        endpoint = self.origin_file_endpoint if origin else self.standard_file_endpoint
        return self.request("GET", endpoint, params={"applicantId": applicant_id})

    def download_file(self, url):
        if url.startswith("//"):
            url = f"https:{url}"
        elif url.startswith("/"):
            url = urljoin(f"{self.base_url}/", url.lstrip("/"))
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "")

    def get_positions(self, position_ids):
        if not settings.ITALENT_POSITIONS_ENDPOINT or not position_ids:
            return {}
        return self.request(
            "POST",
            settings.ITALENT_POSITIONS_ENDPOINT,
            json={"jobIds": position_ids},
        )
