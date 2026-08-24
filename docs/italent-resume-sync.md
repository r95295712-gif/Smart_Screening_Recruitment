# iTalent 简历同步流程

## 目标

同步指定租户中的候选人简历、实际投递岗位以及岗位分类信息。候选人的简历信息和投递信息分开保存，因为同一个候选人可能投递多个岗位。

## 认证

1. 在 iTalent 管理后台创建开放平台连接器。
2. 获取连接器的 `Key` 和 `Secret`。
3. 调用以下接口获取租户级访问令牌：

   ```text
   POST https://openapi.italent.cn/token
   ```

   请求体：

   ```json
   {
     "grant_type": "client_credentials",
     "app_key": "{Key}",
     "app_secret": "{Secret}"
   }
   ```

4. 业务接口请求头使用：

   ```text
   Authorization: Bearer {access_token}
   ```

Token 默认有效期为 7200 秒，应缓存使用，并在失效或即将过期时重新获取。

## 同步顺序

### 1. 获取应聘者 ID

接口：

```text
POST https://openapi.italent.cn/RecruitV6/api/v1/Applicant/GetApplicantIdsByDate
```

请求体示例：

```json
{
  "startTime": "2020-01-01T00:00:00",
  "endTime": "2026-08-05T23:59:59",
  "timeType": 2,
  "batchId": ""
}
```

`timeType` 取值：

- `0`：个人信息更新时间。
- `1`：应聘者简历更新时间。
- `2`：应聘者创建时间。

首次请求的 `batchId` 为空；后续请求使用响应中的 `nextBatchId`，直到 `isLastBatch` 为 `true`。每批最多返回 1000 个 ID。全量同步应使用覆盖租户历史数据的时间范围；数据量较大时按月或按日切分，并对 ID 去重。

### 2. 获取个人信息

接口：

```text
POST https://openapi.italent.cn/RecruitV6/api/v1/Applicant/GetPersonProfileList
```

请求体：

```json
{
  "applicantIds": ["{applicantId-1}", "{applicantId-2}"]
}
```

一次最多查询 100 个应聘者。省略 `fieldNames` 时返回全部有值的个人字段。

### 3. 获取简历模块

接口：

```text
POST https://openapi.italent.cn/RecruitV6/api/v1/Applicant/GetResumeModuleList
```

请求体示例：

```json
{
  "applicantIds": ["{applicantId-1}", "{applicantId-2}"],
  "moduleCode": "ApplicantEducation"
}
```

每次最多查询 100 个应聘者。省略 `fieldNames` 时返回该模块全部有值字段。常用模块包括：

```text
ApplicantObjective, ApplicantEducation, ApplicantWorkExperience,
ApplicantProject, ApplicantInternship, Train, SchoolCadre,
SchoolPractice, ApplicantAdditionalInfo, Writings,
RelativesDeclaration, PayCardInfo, Skill, Awards, AddressInfo,
CredentialsInfo, Lang, Family, TeamManager, Certificate,
ResumeFile, Attachments, Question,
PresetSingleSection1-5, PresetMultiSection1-5
```

`ApplicantObjective` 表示候选人的求职意向，不等同于实际投递岗位。

### 4. 获取实际投递记录

接口：

```text
POST https://openapi.italent.cn/RecruitV6/api/v1/Apply/GetApplyListByApplicantId
```

请求体：

```json
{
  "applicantIds": ["{applicantId-1}", "{applicantId-2}"]
}
```

该接口一次最多查询 100 个应聘者，返回其实际申请记录。系统按 `applyId` 保存每条投递记录，不能用求职意向模块代替实际投递。

应重点保存以下信息（字段名称以接口返回为准）：

- `applyId`：投递/申请记录 ID，写入系统的 `applicationId`。
- `applicantId`：候选人 ID。
- `jobId`：职位 ID。
- `requisitionId`：招聘需求 ID。
- `applicationStatus`：投递状态。
- `appliedTime`：投递时间。
- `source` 或 `channel`：招聘渠道。

开放平台另有 `Applicant/GetSubmissionBasicList`，其说明偏向网申端展示应聘者投递记录；本项目需要稳定取得 `applyId`、`applicantId` 和 `jobId` 的业务关系，因此主同步流程采用 `Apply/GetApplyListByApplicantId`。

### 5. 获取职位详情和岗位分类

接口：

```text
POST https://openapi.italent.cn/RecruitV6/api/v1/Job/GetJobListByIds
```

请求体：

```json
{
  "jobIds": ["{jobId-1}", "{jobId-2}"]
}
```

一次最多查询 100 个职位。同步程序先从投递记录收集 `jobId`，再批量查询职位名称、状态、JD、岗位分类和其他职位字段。岗位分类可能是企业自定义字段，系统同时保留接口原始响应。

### 6. 获取标准简历 JSON（可选）

接口：

```text
GET https://openapi.italent.cn/RecruitV6/api/v1/Applicant/GetResumeByApplyId?applyId={applyId}
```

该接口按投递记录返回标准简历，适合针对某次岗位投递展示或导出。批量同步仍以个人信息和简历模块接口为主。

### 7. 获取简历文件（按需）

标准简历 PDF：

```text
GET https://openapi.italent.cn/RecruitV6/api/v1/Applicant/GetStandardResumeFileUrl?applicantId={applicantId}
```

原始简历文件：

```text
GET https://openapi.italent.cn/RecruitV6/api/v1/Applicant/GetOriginResumeFileUrl?applicantId={applicantId}
```

接口返回 `downloadUrl` 和 `dfsPath`。下载地址是有时效的，应在获取后及时下载，不建议只保存临时 URL。

## 数据关系

```text
candidate(applicantId)
  ├── profile
  ├── resume_modules
  └── applications(applicationId)
        ├── positionId / requisitionId
        ├── positionName
        ├── positionType
        ├── status
        └── source
```

推荐将 `applicationId` 作为投递记录主键，将 `applicantId` 作为候选人和投递记录之间的关联键，避免候选人多岗位投递时互相覆盖。

## 全量与增量

### 首次全量

1. 使用 `timeType=2`，按时间窗口获取全部 `applicantId`。
2. 批量获取个人信息。
3. 对每个简历模块批量获取模块数据。
4. 批量获取候选人的实际投递记录，按 `applyId` 保存。
5. 从投递记录收集 `jobId`，批量获取职位详情和岗位分类。
6. 按需下载标准简历 PDF 或原始简历文件。

### 后续增量

1. 使用 `timeType=1` 获取简历发生更新的候选人。
2. 重新拉取这些候选人的个人信息、简历模块和投递信息。
3. 对投递记录按 `applyId` 更新或新增，并更新涉及的职位。
4. 记录本次同步的时间窗口，避免重复或遗漏。

## 项目环境变量

```text
ITALENT_APP_KEY=连接器 Key
ITALENT_APP_SECRET=连接器 Secret
ITALENT_BASE_URL=https://openapi.italent.cn
ITALENT_APPLICATIONS_ENDPOINT=/RecruitV6/api/v1/Apply/GetApplyListByApplicantId
ITALENT_POSITIONS_ENDPOINT=/RecruitV6/api/v1/Job/GetJobListByIds
```

创建连接器需要“开放平台管理员（含租户管理员）”权限。路径为：管理者后台 → 创建连接器 → 填写名称和描述；进入连接器详情页可取得 `Key` 并查看 `Secret`。

## 限流与错误处理

招聘接口限制为每企业约 20 次/秒、1000 次/分钟。所有接口调用应使用统一限流器，并对 `400`、`417`、`500` 响应记录请求参数和返回的 `message`。批次查询不能只依据 `total` 判断完成，必须依据 `isLastBatch`。
