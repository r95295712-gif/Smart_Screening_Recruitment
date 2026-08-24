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
const previewDir = path.join(path.dirname(workbookPath), "previews");
const preEditPreviewDir = path.join(rootDir, ".codex_tmp", "owner_email_pre_edit");

const pinyinByName = {
  黄国云: "huangguoyun",
  张玲: "zhangling",
  张倩: "zhangqian",
  黄发添: "huangfatian",
  林春金: "linchunjin",
  张丽丽: "zhanglili",
  雷妹英: "leimeiying",
  李晴晴: "liqingqing",
  陈韵以: "chenyunyi",
  杨敏: "yangmin",
  陈丽颖: "chenliying",
  吴俊勇: "wujunyong",
  陈敏云: "chenminyun",
  游梦兰: "youmenglan",
  魏秋云: "weiqiuyun",
  刘鑫: "liuxin",
  邵红霖: "shaohonglin",
  李艳霞: "liyanxia",
  詹凤娇: "zhanfengjiao",
  苏碧龙: "subilong",
  吴晨静: "wuchenjing",
  蔡圆圆: "caiyuanyuan",
  朱琳珊: "zhulinshan",
  黄丽清: "huangliqing",
  龚红琼: "gonghongqiong",
  寿咪霞: "shoumixia",
  陈建雄: "chenjianxiong",
  张雪梅: "zhangxuemei",
  王璐: "wanglu",
  陈晓彦: "chenxiaoyan",
};

function emailsForOwners(ownerText) {
  const normalized = String(ownerText || "").trim();
  if (!normalized || normalized === "待确认" || normalized === "无") {
    return "待确认负责人后补充";
  }
  const owners = normalized
    .split(/[、,，；;]/)
    .map((owner) => owner.trim())
    .filter(Boolean);
  const unknownOwners = owners.filter((owner) => !pinyinByName[owner]);
  if (unknownOwners.length) {
    throw new Error(`缺少拼音映射：${unknownOwners.join("、")}`);
  }
  return owners
    .map((owner) => `${pinyinByName[owner]}@nuptio.net`)
    .join("；");
}

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

await fs.mkdir(preEditPreviewDir, { recursive: true });
const preEditPreview = await workbook.render({
  sheetName: "岗位负责人汇总",
  range: "A1:C39",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(preEditPreviewDir, "岗位负责人汇总.png"),
  new Uint8Array(await preEditPreview.arrayBuffer()),
);

const ownerSheet = workbook.worksheets.getItem("岗位负责人汇总");
const ownerValues = ownerSheet.getRange("A8:A39").values;
const ownerEmailValues = ownerValues.map(([owner]) => [emailsForOwners(owner)]);
ownerSheet.getRange("C8:C39").values = ownerEmailValues;
ownerSheet.getRange("A2:C2").values = [[
  "来源：docs/招聘信息汇总.docx。负责人邮箱按照“姓名拼音@nuptio.net”规则生成；多人负责人邮箱按姓名顺序以分号分隔。",
]];
ownerSheet.getRange("C1:C39").format.columnWidth = 56;
ownerSheet.getRange("C8:C39").format.font = {
  name: "Microsoft YaHei",
  size: 9,
  color: "#172033",
};
ownerSheet.getRange("A8:C12").format.rowHeight = 170;

const matchSheet = workbook.worksheets.getItem("北森匹配结果");
const matchedOwnerValues = matchSheet.getRange("H8:H17").values;
const matchedEmailValues = matchedOwnerValues.map(([owner]) => [
  emailsForOwners(owner),
]);
matchSheet.getRange("I8:I17").values = matchedEmailValues;
matchSheet.getRange("I1:I17").format.columnWidth = 48;
matchSheet.getRange("I8:I17").format.font = {
  name: "Microsoft YaHei",
  size: 8,
  color: "#172033",
};
matchSheet.getRange("A8:O8").format.rowHeight = 150;
matchSheet.getRange("A16:O16").format.rowHeight = 150;

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
  await fs.writeFile(
    path.join(previewDir, `${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const ownerCheck = await workbook.inspect({
  kind: "table",
  range: "岗位负责人汇总!A4:C39",
  include: "values,formulas",
  tableMaxRows: 40,
  tableMaxCols: 3,
});
console.log(ownerCheck.ndjson);
const matchCheck = await workbook.inspect({
  kind: "table",
  range: "北森匹配结果!H7:K17",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 4,
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
await output.save(workbookPath);
console.log(`OUTPUT=${workbookPath}`);
