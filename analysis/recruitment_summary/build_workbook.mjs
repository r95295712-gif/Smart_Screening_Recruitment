import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "../..");
const dataPath = path.join(rootDir, "analysis", "recruitment_summary", "data.json");
const outputDir = path.join(rootDir, "outputs", "01a00e3e-98b7-76d2-99a3-66ae41444da9");
const previewDir = path.join(outputDir, "previews");
const outputPath = path.join(outputDir, "招聘岗位负责人及北森匹配.xlsx");

const sourceData = JSON.parse(await fs.readFile(dataPath, "utf8"));
const workbook = Workbook.create();

const colors = {
  navy: "#17324D",
  teal: "#0E7490",
  blue: "#2563EB",
  lightBlue: "#E8F1F8",
  lighterBlue: "#F4F8FB",
  green: "#15803D",
  lightGreen: "#DCFCE7",
  amber: "#B45309",
  lightAmber: "#FEF3C7",
  red: "#B91C1C",
  lightRed: "#FEE2E2",
  gray: "#667085",
  lightGray: "#F2F4F7",
  border: "#D0D5DD",
  white: "#FFFFFF",
  text: "#172033",
};

const knownEmails = {};
for (const job of sourceData.beisen_jobs) {
  if (job.hr_owner && job.hr_email) {
    knownEmails[job.hr_owner] = job.hr_email;
  }
}

const mappingRules = {
  "Amazon亚马逊运营": {
    documentTitle: "亚马逊Amazon运营（中级）",
    method: "JD相似 + 人工复核",
    conflict: "岗位一对多；名称差异；负责人差异；JD版本差异",
    suggestion: "映射到“中级”；汇总中的初级、高级、助理保留为独立标准岗位",
    priority: "高",
  },
  "Temu运营": {
    documentTitle: "Temu运营",
    method: "标准化名称精确",
    conflict: "负责人差异；JD存在差异",
    suggestion: "同名直接映射；负责人字段先确认口径，JD建议保留版本",
    priority: "中",
  },
  "Tiktok店铺运营": {
    documentTitle: "TK运营/Tiktok运营",
    method: "别名 + JD精确",
    conflict: "名称差异；负责人差异",
    suggestion: "建立别名映射到“TK运营/Tiktok运营”",
    priority: "低",
  },
  "ai算法工程师": {
    documentTitle: "AI工程师",
    method: "别名 + JD高相似",
    conflict: "名称差异；负责人差异；JD存在差异",
    suggestion: "建立别名映射到“AI工程师”，主展示名称由业务确认",
    priority: "中",
  },
  "产品经理（跨境电商方向）": {
    documentTitle: "产品经理（出海赛道/双休）/产品开发经理（出海赛道/双休）",
    method: "别名 + JD相似",
    conflict: "名称差异；负责人差异；JD版本差异",
    suggestion: "建立别名映射；主名称和JD有效版本需人工确认",
    priority: "高",
  },
  "产品设计师": {
    documentTitle: "产品设计师",
    method: "名称精确 + JD高相似",
    conflict: "负责人差异",
    suggestion: "岗位直接映射；负责人字段先确认口径",
    priority: "低",
  },
  "测试": {
    documentTitle: "",
    method: "未匹配",
    conflict: "汇总无对应岗位；北森为历史岗位",
    suggestion: "建议不关联并保留为北森历史记录",
    priority: "高",
  },
  "海外社媒运营": {
    documentTitle: "海外社交媒体运营/新媒体运营（面向海外）/海外社媒运营/社交媒体推广专员",
    method: "别名精确 + JD精确",
    conflict: "负责人差异",
    suggestion: "建立别名映射；负责人字段先确认口径",
    priority: "低",
  },
  "跨境电商运营（应届生可投）": {
    documentTitle: "跨境电商运营（应届生可投）",
    method: "名称精确 + JD高相似",
    conflict: "负责人差异",
    suggestion: "岗位直接映射；负责人字段先确认口径",
    priority: "低",
  },
  "采购开发工程师": {
    documentTitle: "采购开发工程师",
    method: "名称精确（JD冲突）",
    conflict: "负责人差异；JD内容显著冲突",
    suggestion: "岗位直接映射；JD不要互相覆盖，人工选择有效版本并保留历史",
    priority: "高",
  },
};

function findDocumentJob(title) {
  return sourceData.document_jobs.find((job) => job.title === title);
}

function ownerEmailText(owners) {
  if (!owners.length) {
    return "待确认负责人后补充";
  }
  const resolved = owners
    .map((owner) => knownEmails[owner])
    .filter(Boolean);
  if (resolved.length === owners.length) {
    return resolved.join("；");
  }
  if (resolved.length) {
    return `${resolved.join("；")}；其余待补充`;
  }
  return "待补充";
}

function applyBaseSheetStyle(sheet) {
  sheet.showGridLines = false;
}

function styleTitle(sheet, range, title) {
  sheet.mergeCells(range);
  const titleRange = sheet.getRange(range);
  titleRange.values = [[title]];
  titleRange.format = {
    fill: colors.navy,
    font: {
      name: "Microsoft YaHei",
      size: 18,
      bold: true,
      color: colors.white,
    },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  titleRange.format.rowHeight = 34;
}

function styleNote(sheet, range, text) {
  sheet.mergeCells(range);
  const noteRange = sheet.getRange(range);
  noteRange.values = [[text]];
  noteRange.format = {
    fill: colors.lighterBlue,
    font: {
      name: "Microsoft YaHei",
      size: 9,
      color: colors.gray,
    },
    wrapText: true,
    verticalAlignment: "center",
  };
  noteRange.format.rowHeight = 38;
}

function styleHeader(range) {
  range.format = {
    fill: colors.teal,
    font: {
      name: "Microsoft YaHei",
      bold: true,
      color: colors.white,
    },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: colors.border },
  };
  range.format.rowHeight = 28;
}

function styleDataRange(range) {
  range.format = {
    font: {
      name: "Microsoft YaHei",
      size: 10,
      color: colors.text,
    },
    verticalAlignment: "center",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "thin", color: colors.border },
      bottom: { style: "thin", color: colors.border },
    },
  };
}

const ownerSheet = workbook.worksheets.add("岗位负责人汇总");
styleTitle(ownerSheet, "A1:C1", "招聘岗位负责人汇总");
styleNote(
  ownerSheet,
  "A2:C2",
  "来源：docs/招聘信息汇总.docx。邮箱仅填入当前本地数据中可确认的地址；其余标记为“待补充”，未按邮箱命名规则推测。",
);
ownerSheet.getRange("A4:C4").values = [["岗位总数", "已确认邮箱岗位数", "待补充邮箱岗位数"]];
styleHeader(ownerSheet.getRange("A4:C4"));
ownerSheet.getRange("A5").formulas = [["=COUNTA(B8:B39)"]];
ownerSheet.getRange("B5").formulas = [
  ['=COUNTIF(C8:C39,"<>待补充")-COUNTIF(C8:C39,"待确认负责人后补充")'],
];
ownerSheet.getRange("C5").formulas = [["=A5-B5"]];
ownerSheet.getRange("A5:C5").format = {
  fill: colors.lightBlue,
  font: { name: "Microsoft YaHei", size: 14, bold: true, color: colors.navy },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: colors.border },
};
ownerSheet.getRange("A5:C5").format.rowHeight = 30;

const ownerRows = sourceData.document_jobs.map((job) => {
  const displayTitle =
    job.status === "暂停招聘" ? `${job.title}（暂停招聘）` : job.title;
  return [
    job.owners.length ? job.owners.join("、") : "待确认",
    displayTitle,
    ownerEmailText(job.owners),
  ];
});
ownerSheet.getRange("A7:C39").values = [
  ["负责人", "岗位", "负责人邮箱"],
  ...ownerRows,
];
styleHeader(ownerSheet.getRange("A7:C7"));
styleDataRange(ownerSheet.getRange("A8:C39"));
ownerSheet.getRange("A8:C39").format.rowHeight = 36;
ownerSheet.getRange("A8:A12").format.rowHeight = 62;
ownerSheet.getRange("A8:A39").format.horizontalAlignment = "left";
ownerSheet.getRange("B8:B39").format.horizontalAlignment = "left";
ownerSheet.getRange("C8:C39").format.horizontalAlignment = "left";
ownerSheet.getRange("A1:A39").format.columnWidth = 48;
ownerSheet.getRange("B1:B39").format.columnWidth = 48;
ownerSheet.getRange("C1:C39").format.columnWidth = 34;
ownerSheet.tables.add("A7:C39", true, "OwnerSummaryTable").style = "TableStyleMedium2";
ownerSheet.freezePanes.freezeRows(7);
ownerSheet.getRange("C8:C39").conditionalFormats.add("containsText", {
  text: "待补充",
  format: { fill: colors.lightAmber, font: { color: colors.amber } },
});
ownerSheet.getRange("B8:B39").conditionalFormats.add("containsText", {
  text: "暂停招聘",
  format: { fill: colors.lightGray, font: { color: colors.gray, italic: true } },
});

const matchRows = sourceData.beisen_jobs.map((beisenJob) => {
  const rule = mappingRules[beisenJob.title];
  const documentJob = rule.documentTitle ? findDocumentJob(rule.documentTitle) : null;
  const computedMatch = sourceData.matches.find(
    (item) => item.title === beisenJob.title,
  );
  const candidate = computedMatch?.candidates.find(
    (item) => item.document_title === rule.documentTitle,
  );
  const documentOwners = documentJob?.owners || [];
  return {
    beisenJob,
    rule,
    documentJob,
    titleScore: candidate?.title_score ?? 0,
    contentScore: candidate?.content_score ?? 0,
    documentOwners,
    documentEmails: ownerEmailText(documentOwners),
  };
});

const matchSheet = workbook.worksheets.add("北森匹配结果");
styleTitle(matchSheet, "A1:O1", "北森岗位与招聘汇总匹配结果");
styleNote(
  matchSheet,
  "A2:O2",
  "标题分用于名称/别名相似度，JD分用于岗位职责与任职要求的文本相似度。自动结果仅用于建议；负责人、岗位一对多、JD差异均需人工确认。",
);
matchSheet.getRange("A4:D4").values = [["北森岗位数", "已建议映射", "未匹配", "待人工决策"]];
styleHeader(matchSheet.getRange("A4:D4"));
matchSheet.getRange("A5").values = [[matchRows.length]];
matchSheet.getRange("B5").values = [[matchRows.filter((row) => row.documentJob).length]];
matchSheet.getRange("C5").values = [[matchRows.filter((row) => !row.documentJob).length]];
matchSheet.getRange("D5").formulas = [["=COUNTIF(N8:N17,\"待决定\")"]];
matchSheet.getRange("A5:D5").format = {
  fill: colors.lightBlue,
  font: { name: "Microsoft YaHei", size: 13, bold: true, color: colors.navy },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: colors.border },
};
matchSheet.getRange("A5:D5").format.rowHeight = 28;

const matchHeaders = [
  "北森岗位",
  "北森状态",
  "北森岗位ID",
  "建议汇总岗位",
  "匹配方式",
  "标题分",
  "JD分",
  "汇总负责人",
  "汇总负责人邮箱",
  "北森HR负责人",
  "北森HR邮箱",
  "冲突类型",
  "建议处理",
  "人工决策",
  "决策备注",
];
const matchValues = matchRows.map((row) => [
  row.beisenJob.title,
  row.beisenJob.status === "active" ? "有效" : "历史",
  row.beisenJob.beisen_position_id,
  row.rule.documentTitle || "未找到对应岗位",
  row.rule.method,
  row.titleScore,
  row.contentScore,
  row.documentOwners.length ? row.documentOwners.join("、") : "无",
  row.documentEmails,
  row.beisenJob.hr_owner || "无",
  row.beisenJob.hr_email || "无",
  row.rule.conflict,
  row.rule.suggestion,
  "待决定",
  "",
]);
matchSheet.getRange("A7:O17").values = [matchHeaders, ...matchValues];
styleHeader(matchSheet.getRange("A7:O7"));
styleDataRange(matchSheet.getRange("A8:O17"));
matchSheet.getRange("F8:G17").format.numberFormat = "0%";
matchSheet.getRange("F8:G17").format.horizontalAlignment = "center";
matchSheet.getRange("B8:B17").format.horizontalAlignment = "center";
matchSheet.getRange("N8:N17").format.horizontalAlignment = "center";
matchSheet.getRange("A8:O17").format.rowHeight = 56;
const matchWidths = [24, 10, 38, 48, 24, 10, 10, 40, 28, 16, 28, 42, 54, 18, 28];
for (let index = 0; index < matchWidths.length; index += 1) {
  matchSheet
    .getRangeByIndexes(0, index, 17, 1)
    .format.columnWidth = matchWidths[index];
}
matchSheet.tables.add("A7:O17", true, "BeisenMatchTable").style = "TableStyleMedium2";
matchSheet.freezePanes.freezeRows(7);
matchSheet.freezePanes.freezeColumns(3);
matchSheet.getRange("N8:N17").dataValidation = {
  rule: {
    type: "list",
    values: ["待决定", "采用汇总", "采用北森", "建立别名映射", "不关联"],
  },
};
matchSheet.getRange("N8:N17").conditionalFormats.add("containsText", {
  text: "待决定",
  format: { fill: colors.lightAmber, font: { color: colors.amber, bold: true } },
});
matchSheet.getRange("L8:L17").conditionalFormats.add("containsText", {
  text: "显著冲突",
  format: { fill: colors.lightRed, font: { color: colors.red, bold: true } },
});
matchSheet.getRange("D8:D17").conditionalFormats.add("containsText", {
  text: "未找到",
  format: { fill: colors.lightRed, font: { color: colors.red, bold: true } },
});

const conflictSheet = workbook.worksheets.add("待决策冲突");
styleTitle(conflictSheet, "A1:I1", "需要人工决策的岗位冲突");
styleNote(
  conflictSheet,
  "A2:I2",
  "优先处理岗位一对多、未匹配和JD显著冲突。若确认“北森HR负责人”和文档“招聘负责人”不是同一业务字段，应分别保留，不互相覆盖。",
);
const priorityOrder = { 高: 0, 中: 1, 低: 2 };
const conflictRows = [...matchRows].sort(
  (left, right) => priorityOrder[left.rule.priority] - priorityOrder[right.rule.priority],
);
const conflictHeaders = [
  "优先级",
  "北森岗位",
  "汇总岗位",
  "冲突类型",
  "负责人对比",
  "建议处理",
  "人工决策",
  "决策备注",
  "北森岗位ID",
];
const conflictValues = conflictRows.map((row) => [
  row.rule.priority,
  row.beisenJob.title,
  row.rule.documentTitle || "未找到对应岗位",
  row.rule.conflict,
  `汇总：${row.documentOwners.length ? row.documentOwners.join("、") : "无"}\n北森HR：${row.beisenJob.hr_owner || "无"}`,
  row.rule.suggestion,
  "待决定",
  "",
  row.beisenJob.beisen_position_id,
]);
conflictSheet.getRange("A4:I14").values = [conflictHeaders, ...conflictValues];
styleHeader(conflictSheet.getRange("A4:I4"));
styleDataRange(conflictSheet.getRange("A5:I14"));
conflictSheet.getRange("A5:I14").format.rowHeight = 62;
const conflictWidths = [10, 24, 48, 44, 42, 54, 18, 30, 38];
for (let index = 0; index < conflictWidths.length; index += 1) {
  conflictSheet
    .getRangeByIndexes(0, index, 14, 1)
    .format.columnWidth = conflictWidths[index];
}
conflictSheet.tables.add("A4:I14", true, "ConflictDecisionTable").style = "TableStyleMedium2";
conflictSheet.freezePanes.freezeRows(4);
conflictSheet.getRange("G5:G14").dataValidation = {
  rule: {
    type: "list",
    values: ["待决定", "采用汇总", "采用北森", "建立别名映射", "不关联"],
  },
};
conflictSheet.getRange("A5:A14").conditionalFormats.add("containsText", {
  text: "高",
  format: { fill: colors.lightRed, font: { color: colors.red, bold: true } },
});
conflictSheet.getRange("A5:A14").conditionalFormats.add("containsText", {
  text: "中",
  format: { fill: colors.lightAmber, font: { color: colors.amber, bold: true } },
});
conflictSheet.getRange("A5:A14").conditionalFormats.add("containsText", {
  text: "低",
  format: { fill: colors.lightGreen, font: { color: colors.green, bold: true } },
});
conflictSheet.getRange("G5:G14").conditionalFormats.add("containsText", {
  text: "待决定",
  format: { fill: colors.lightAmber, font: { color: colors.amber, bold: true } },
});

const ruleSheet = workbook.worksheets.add("匹配规则说明");
styleTitle(ruleSheet, "A1:B1", "北森岗位映射建议");
styleNote(
  ruleSheet,
  "A2:B2",
  "核心原则：不要用岗位名称作为唯一键；用北森岗位ID维护稳定映射，岗位名称、别名、JD和负责人作为可版本化属性。",
);
ruleSheet.getRange("A4:B4").values = [["主题", "建议"]];
styleHeader(ruleSheet.getRange("A4:B4"));
const ruleRows = [
  ["稳定键", "以北森 beisen_position_id 作为外部唯一键，避免岗位改名后生成重复岗位。"],
  ["标准岗位", "系统维护内部标准岗位；同一标准岗位可以关联多个北森名称或历史名称。"],
  ["映射表", "保存“北森岗位ID → 内部标准岗位ID”、匹配方式、人工决策、有效来源和备注。"],
  ["自动匹配第1步", "岗位名标准化：统一中英文平台名、大小写、全半角、空格和宣传性括号词。"],
  ["自动匹配第2步", "按斜杠别名进行精确匹配；命中唯一岗位时给出高置信建议。"],
  ["自动匹配第3步", "名称不一致时比较JD；JD高相似可建议别名映射，但不能直接覆盖人工结果。"],
  ["必须人工确认", "一对多、未匹配、负责人不同、同名但JD显著变化、暂停/历史状态不一致。"],
  ["负责人字段", "先确认北森HR负责人和文档招聘负责人是否同义；若不是，分别保存为招聘HR与业务负责人。"],
  ["JD策略", "保留北森原始JD和汇总JD两个版本，人工指定当前评估JD；同步不得覆盖已确认版本。"],
  ["同步保护", "一旦人工确认映射，后续同步优先按岗位ID更新，不再依赖模糊名称重新匹配。"],
  ["推荐决策值", "采用汇总、采用北森、建立别名映射、不关联；所有决策保留操作人和时间。"],
];
ruleSheet.getRange("A5:B15").values = ruleRows;
styleDataRange(ruleSheet.getRange("A5:B15"));
ruleSheet.getRange("A5:A15").format = {
  fill: colors.lightBlue,
  font: { name: "Microsoft YaHei", bold: true, color: colors.navy },
  verticalAlignment: "center",
  wrapText: true,
  borders: {
    insideHorizontal: { style: "thin", color: colors.border },
    bottom: { style: "thin", color: colors.border },
  },
};
ruleSheet.getRange("A5:B15").format.rowHeight = 38;
ruleSheet.getRange("A1:A15").format.columnWidth = 24;
ruleSheet.getRange("B1:B15").format.columnWidth = 90;
ruleSheet.tables.add("A4:B15", true, "MatchingRulesTable").style = "TableStyleMedium2";
ruleSheet.freezePanes.freezeRows(4);

for (const sheet of workbook.worksheets.items) {
  applyBaseSheetStyle(sheet);
}

await fs.mkdir(previewDir, { recursive: true });
const previewSpecs = [
  ["岗位负责人汇总", "A1:C39"],
  ["北森匹配结果", "A1:O17"],
  ["待决策冲突", "A1:I14"],
  ["匹配规则说明", "A1:B15"],
];
for (const [sheetName, range] of previewSpecs) {
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  const safeName = sheetName.replace(/[\\/:*?"<>|]/g, "_");
  await fs.writeFile(
    path.join(previewDir, `${safeName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const ownerCheck = await workbook.inspect({
  kind: "table",
  range: "岗位负责人汇总!A4:C12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 4,
});
console.log(ownerCheck.ndjson);
const matchCheck = await workbook.inspect({
  kind: "table",
  range: "北森匹配结果!A7:O17",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 15,
});
console.log(matchCheck.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
