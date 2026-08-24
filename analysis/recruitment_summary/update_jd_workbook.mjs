import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(scriptDir, "../..");
const workbookPath = path.join(
  rootDir,
  "outputs",
  "01a00e3e-98b7-76d2-99a3-66ae41444da9",
  "招聘岗位负责人及北森匹配.xlsx",
);
const outputPath = process.env.WORKBOOK_OUTPUT_PATH || workbookPath;
const decisionsPath = path.join(scriptDir, "jd_decisions.json");
const previewDir = path.join(path.dirname(workbookPath), "previews");
const preEditPreviewDir = path.join(rootDir, ".codex_tmp", "jd_decision_pre_edit");

const decisions = JSON.parse(await fs.readFile(decisionsPath, "utf8"));
const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

await fs.mkdir(preEditPreviewDir, { recursive: true });
const preEditPreview = await workbook.render({
  sheetName: "待决策冲突",
  range: "A1:I14",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(preEditPreviewDir, "待决策冲突.png"),
  new Uint8Array(await preEditPreview.arrayBuffer()),
);

const colors = {
  navy: "#17324D",
  teal: "#0E7490",
  lightBlue: "#E8F1F8",
  lightGreen: "#DCFCE7",
  green: "#15803D",
  lightGray: "#F2F4F7",
  gray: "#667085",
  border: "#D0D5DD",
  white: "#FFFFFF",
  text: "#172033",
};

function rowByValue(sheet, range, value) {
  const values = sheet.getRange(range).values;
  const startRow = Number(range.match(/\d+/)[0]);
  const index = values.findIndex(([cellValue]) => cellValue === value);
  if (index < 0) {
    throw new Error(`未在 ${sheet.name}!${range} 找到 ${value}`);
  }
  return startRow + index;
}

function withoutOwnerConflict(value) {
  const parts = String(value || "")
    .split("；")
    .map((part) => part.trim())
    .filter((part) => part && part !== "负责人差异");
  return parts.length ? parts.join("；") : "无JD冲突";
}

const matchSheet = workbook.worksheets.getItem("北森匹配结果");
matchSheet.getRange("D7").values = [["对应文档岗位（负责人关联）"]];
for (let row = 8; row <= 17; row += 1) {
  const currentConflict = matchSheet.getRange(`L${row}`).values[0][0];
  matchSheet.getRange(`L${row}`).values = [[withoutOwnerConflict(currentConflict)]];
}
for (const [positionName, decision] of Object.entries(decisions)) {
  const row = rowByValue(matchSheet, "A8:A17", positionName);
  matchSheet.getRange(`N${row}`).values = [[decision.decision]];
  matchSheet.getRange(`O${row}`).values = [[decision.note]];
  matchSheet.getRange(`M${row}`).values = [[
    positionName === "采购开发工程师"
      ? "已合并北森JD与招聘汇总JD，系统评估JD采用合并版本"
      : "已确认系统评估JD采用北森当前版本",
  ]];
}
matchSheet.getRange("N8:N17").dataValidation = {
  rule: {
    type: "list",
    values: [
      "待决定",
      "采用汇总",
      "采用北森",
      "合并JD",
      "建立别名映射",
      "不关联",
    ],
  },
};
matchSheet.getRange("N8:N17").conditionalFormats.add("containsText", {
  text: "采用北森",
  format: { fill: colors.lightGreen, font: { color: colors.green, bold: true } },
});
matchSheet.getRange("N8:N17").conditionalFormats.add("containsText", {
  text: "合并JD",
  format: { fill: colors.lightGreen, font: { color: colors.green, bold: true } },
});

const conflictSheet = workbook.worksheets.getItem("待决策冲突");
for (let row = 5; row <= 14; row += 1) {
  const currentConflict = conflictSheet.getRange(`D${row}`).values[0][0];
  conflictSheet.getRange(`D${row}`).values = [[withoutOwnerConflict(currentConflict)]];
}
for (const [positionName, decision] of Object.entries(decisions)) {
  const row = rowByValue(conflictSheet, "B5:B14", positionName);
  conflictSheet.getRange(`G${row}`).values = [[decision.decision]];
  conflictSheet.getRange(`H${row}`).values = [[decision.note]];
  conflictSheet.getRange(`F${row}`).values = [[
    positionName === "采购开发工程师"
      ? "已形成合并JD；经验要求按至少3年执行"
      : "已确认系统评估JD采用北森当前版本",
  ]];
}
conflictSheet.getRange("G5:G14").dataValidation = {
  rule: {
    type: "list",
    values: [
      "待决定",
      "采用汇总",
      "采用北森",
      "合并JD",
      "建立别名映射",
      "不关联",
    ],
  },
};
conflictSheet.getRange("G5:G14").conditionalFormats.add("containsText", {
  text: "采用北森",
  format: { fill: colors.lightGreen, font: { color: colors.green, bold: true } },
});
conflictSheet.getRange("G5:G14").conditionalFormats.add("containsText", {
  text: "合并JD",
  format: { fill: colors.lightGreen, font: { color: colors.green, bold: true } },
});

let decisionSheet = workbook.worksheets.items.find(
  (sheet) => sheet.name === "JD决策与合并",
);
if (!decisionSheet) {
  decisionSheet = workbook.worksheets.add("JD决策与合并");
}
decisionSheet.getRange("A1:E24").unmerge();
decisionSheet.getRange("A1:E24").clear({ applyTo: "all" });
decisionSheet.showGridLines = false;
decisionSheet.mergeCells("A1:E1");
decisionSheet.getRange("A1:E1").values = [["岗位名称与JD采用规则"]];
decisionSheet.getRange("A1:E1").format = {
  fill: colors.navy,
  font: {
    name: "Microsoft YaHei",
    size: 18,
    bold: true,
    color: colors.white,
  },
  verticalAlignment: "center",
};
decisionSheet.getRange("A1:E1").format.rowHeight = 34;
decisionSheet.mergeCells("A2:E2");
decisionSheet.getRange("A2:E2").values = [[
  "所有有效岗位的系统名称统一采用北森当前名称；除采购开发工程师采用合并JD外，其余有效岗位均采用北森当前JD。",
]];
decisionSheet.getRange("A2:E2").format = {
  fill: colors.lightGray,
  font: { name: "Microsoft YaHei", size: 9, color: colors.gray },
  wrapText: true,
  verticalAlignment: "center",
};
decisionSheet.getRange("A2:E2").format.rowHeight = 34;
const decisionOrder = [
  "Amazon亚马逊运营",
  "Temu运营",
  "Tiktok店铺运营",
  "ai算法工程师",
  "产品经理（跨境电商方向）",
  "产品设计师",
  "海外社媒运营",
  "跨境电商运营（应届生可投）",
  "采购开发工程师",
];
const decisionRows = decisionOrder.map((positionName) => {
  const decision = decisions[positionName];
  return [
    positionName,
    decision.document_title,
    "采用北森",
    decision.jd_source === "merged" ? "合并JD" : "北森当前JD",
    "已执行",
  ];
});
decisionSheet.getRange("A4:E13").values = [
  ["北森岗位名称", "对应文档岗位（负责人关联）", "岗位名称标准", "JD标准", "状态"],
  ...decisionRows,
];
decisionSheet.getRange("A4:E4").format = {
  fill: colors.teal,
  font: { name: "Microsoft YaHei", bold: true, color: colors.white },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: colors.border },
};
decisionSheet.getRange("A5:E13").format = {
  font: { name: "Microsoft YaHei", size: 10, color: colors.text },
  verticalAlignment: "center",
  wrapText: true,
  borders: {
    insideHorizontal: { style: "thin", color: colors.border },
    bottom: { style: "thin", color: colors.border },
  },
};
decisionSheet.getRange("A5:E13").format.rowHeight = 44;
decisionSheet.getRange("C5:D13").format = {
  fill: colors.lightGreen,
  font: { name: "Microsoft YaHei", bold: true, color: colors.green },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
decisionSheet.getRange("E5:E13").format = {
  fill: colors.lightGreen,
  font: { name: "Microsoft YaHei", bold: true, color: colors.green },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};

const [responsibilities, requirements] =
  decisions["采购开发工程师"].evaluation_jd.split("\n\n任职要求\n");
decisionSheet.mergeCells("A15:E15");
decisionSheet.getRange("A15:E15").values = [["采购开发工程师合并JD"]];
decisionSheet.getRange("A15:E15").format = {
  fill: colors.teal,
  font: { name: "Microsoft YaHei", size: 13, bold: true, color: colors.white },
  verticalAlignment: "center",
};
decisionSheet.mergeCells("B16:E16");
decisionSheet.getRange("A16").values = [["岗位职责"]];
decisionSheet.getRange("B16:E16").values = [[
  responsibilities.replace(/^岗位职责\n/, ""),
]];
decisionSheet.mergeCells("B17:E17");
decisionSheet.getRange("A17").values = [["任职要求"]];
decisionSheet.getRange("B17:E17").values = [[requirements]];
decisionSheet.getRange("A16:A17").format = {
  fill: colors.lightBlue,
  font: { name: "Microsoft YaHei", bold: true, color: colors.navy },
  horizontalAlignment: "center",
  verticalAlignment: "top",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: colors.border },
};
decisionSheet.getRange("B16:E17").format = {
  font: { name: "Microsoft YaHei", size: 10, color: colors.text },
  verticalAlignment: "top",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: colors.border },
};
decisionSheet.getRange("A16:E16").format.rowHeight = 300;
decisionSheet.getRange("A17:E17").format.rowHeight = 170;
decisionSheet.mergeCells("A19:E19");
decisionSheet.getRange("A19:E19").values = [[
  "本次合并未发现其他互斥要求。若后续需要确定职级、薪酬或是否必须具备英文能力，再单独确认。",
]];
decisionSheet.getRange("A19:E19").format = {
  fill: colors.lightGray,
  font: { name: "Microsoft YaHei", size: 9, color: colors.gray },
  wrapText: true,
  verticalAlignment: "center",
};
decisionSheet.getRange("A19:E19").format.rowHeight = 34;
decisionSheet.getRange("A1:A19").format.columnWidth = 28;
decisionSheet.getRange("B1:B19").format.columnWidth = 58;
decisionSheet.getRange("C1:C19").format.columnWidth = 18;
decisionSheet.getRange("D1:D19").format.columnWidth = 22;
decisionSheet.getRange("E1:E19").format.columnWidth = 14;
decisionSheet.freezePanes.freezeRows(4);

await fs.mkdir(previewDir, { recursive: true });
const previewSpecs = [
  ["岗位负责人汇总", "A1:C39"],
  ["北森匹配结果", "A1:O17"],
  ["待决策冲突", "A1:I14"],
  ["匹配规则说明", "A1:B15"],
  ["JD决策与合并", "A1:E19"],
];
for (const [sheetName, range] of previewSpecs) {
  const preview = await workbook.render({
    sheetName,
    range,
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const decisionCheck = await workbook.inspect({
  kind: "table",
  range: "JD决策与合并!A4:E19",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 5,
});
console.log(decisionCheck.ndjson);
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

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
