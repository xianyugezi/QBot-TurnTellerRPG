#!/usr/bin/env node
/* 批33 · 草稿级撤销/重做（框架 §6.12-01）DOM/交互级证据（真 Chromium + 真编辑器宿主）。
 *
 * 设计：
 *   · 只驱动真实页面（真 input / change / click / keyboard 事件），断言读真实 DOM 值与
 *     window 上的草稿对象（框架顶栏编辑器脚本的顶层 var 即 window 属性）；
 *   · 内容包/模块/条目/字段**全部运行时发现**（不写死任何业务包名、模块名、字段名）：
 *     逐模块/条目真实点开，取「页面上可见可编」的文本/数值字段、列表行表、键值表格各一个
 *     （可来自不同条目——有的字段被分组/子页隐藏，本脚本只认可见者）；
 *   · 除「保存后清栈」一例外不点保存；请在**临时内容根**的宿主上跑（脚本不自建包）。
 *
 * 用法：
 *   node scripts/editor_batch33_undo_e2e.js --base http://127.0.0.1:8099 \
 *        --shots /root/deliverables/batch33_shots [--pack <id>] [--headful]
 * 退出码 0 = 全部断言通过；报告见 stdout 与 <shots>/report.json。
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("/usr/local/lib/hermes-agent/node_modules/playwright");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : def;
}
const BASE = arg("base", "http://127.0.0.1:8090");
const SHOTS = arg("shots", "/tmp/batch33_shots");
const PACK = arg("pack", "");
const HEADFUL = process.argv.includes("--headful");

const report = { ok: false, base: BASE, pack: null, targets: {}, checks: [], shots: [] };
let failures = 0;

function check(name, cond, detail) {
  report.checks.push({ name, ok: !!cond, detail: detail === undefined ? null : detail });
  if (!cond) { failures += 1; }
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}${detail === undefined ? "" : " :: " + JSON.stringify(detail)}`);
}
async function shot(page, name) {
  const p = path.join(SHOTS, name);
  await page.screenshot({ path: p, fullPage: false });
  report.shots.push(p);
  return p;
}

async function fetchJSON(page, url) {
  return page.evaluate(async (u) => {
    const r = await fetch(u);
    if (!r.ok) { throw new Error(u + " -> " + r.status); }
    return r.json();
  }, url);
}

async function selectEntry(page, module, entry) {
  await page.locator(`#mods .mod[data-module="${module}"]`).first().click();
  await page.waitForSelector(`#rows .item[data-id="${entry}"]`, { timeout: 20000 });
  await page.locator(`#rows .item[data-id="${entry}"]`).first().click();
  await page.waitForFunction((id) => window.state && window.state.entry === id, entry, { timeout: 20000 });
  await page.waitForTimeout(150);
}

// 打开字段所在的分组/折叠块（二级子页绑定的缺失是既有问题——本脚本只取已可见控件）。
async function revealField(page, key) {
  await page.evaluate((k) => {
    const el = document.querySelector(
      `#p-body .row[data-field="${k}"], #p-body .lwrap[data-lwrap="${k}"], #p-body .kvwrap[data-kvwrap="${k}"]`);
    if (!el) { return; }
    const sub = el.closest(".subblk");
    if (sub) {
      const body = sub.querySelector(".sbbody");
      if (body && body.hidden) { const h = sub.querySelector(".sbhead"); if (h) { h.click(); } }
    }
    const pane = el.closest(".gpane");
    if (pane) {
      const g = pane.getAttribute("data-g");
      const tab = document.querySelector(`#p-body .gtab[data-g="${g}"]`);
      if (tab && !tab.classList.contains("on")) { tab.click(); }
    }
  }, key);
  await page.waitForTimeout(100);
}

const VISIBLE_JS = () => {
  const vis = (e) => !!(e && (e.offsetWidth || e.offsetHeight) && !e.closest("[hidden]"));
  const text = [];
  document.querySelectorAll("#p-body .row[data-field]").forEach((row) => {
    const inp = row.querySelector('input[data-key][type="text"], input[data-key][type="number"]');
    if (inp && vis(inp)) { text.push({ key: row.dataset.field, kind: inp.type, value: inp.value }); }
  });
  const list = Array.from(document.querySelectorAll("#p-body .lwrap[data-lwrap]"))
    .filter((w) => vis(w.querySelector("[data-ladd]"))).map((w) => w.dataset.lwrap);
  const kv = Array.from(document.querySelectorAll("#p-body .kvwrap[data-kvwrap]"))
    .filter((w) => vis(w.querySelector("[data-kvkey]"))).map((w) => w.dataset.kvwrap);
  return { text, list, kv };
};

// 运行时发现：逐模块/条目真实点开，取页面上可见可编的三类控件各一个。
async function scanTargets(page, packWanted) {
  const packsData = await fetchJSON(page, "/api/packs");
  const packs = (packsData.packs || []).map((p) => p.id);
  const pack = packWanted && packs.includes(packWanted) ? packWanted : packs[0];
  const enc = encodeURIComponent;
  const md = await fetchJSON(page, `/api/pack/${enc(pack)}/modules`);
  const mods = [];
  (function walk(list) {
    (list || []).forEach((n) => { if (n.module) { mods.push(n.module); } if (n.children) { walk(n.children); } });
  })(md.modules || []);
  const uniq = Array.from(new Set(mods));
  const out = { pack, text: null, list: null, kv: null, scanned: 0 };
  for (const m of uniq) {
    if (out.text && out.list && out.kv) { break; }
    await page.locator(`#mods .mod[data-module="${m}"]`).first().click().catch(() => {});
    await page.waitForTimeout(150);
    // 用真实列表里的条目 id（`@table` 等合成条目只在 DOM 上，不在 API entries 里）
    const ids = await page.$$eval("#rows .item[data-id]", (its) => its.map((i) => i.dataset.id));
    for (const id of ids) {
      if (out.text && out.list && out.kv) { break; }
      if (++out.scanned > 400) { break; }
      const item = page.locator(`#rows .item[data-id="${id}"]`).first();
      if (await item.count() === 0) { continue; }
      await item.click().catch(() => {});
      await page.waitForFunction((x) => window.state && window.state.entry === x,
                                 id, { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(180);
      const v = await page.evaluate(VISIBLE_JS);
      if (!out.text) {
        const cand = v.text.filter((x) => x.kind === "text" && x.key !== "id" && x.key !== "name");
        if (cand.length >= 2) {
          out.text = { module: m, entry: id, key: cand[0].key, kind: cand[0].kind,
                       before: cand[0].value, key2: cand[1].key, before2: cand[1].value };
        }
      }
      if (!out.list && v.list.length) { out.list = { module: m, entry: id, key: v.list[0] }; }
      if (!out.kv && v.kv.length) { out.kv = { module: m, entry: id, key: v.kv[0] }; }
    }
  }
  return out;
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ headless: !HEADFUL });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
  page.setDefaultTimeout(60000);
  const dialogs = [];
  page.__acceptDialog = false;
  page.on("dialog", async (d) => {
    dialogs.push({ type: d.type(), message: d.message() });
    if (d.type() === "confirm" && page.__acceptDialog) { await d.accept(); } else { await d.dismiss(); }
  });
  try {
    await page.goto(BASE, { waitUntil: "networkidle" });
    await page.waitForSelector("#rows .item, #rows .empty", { timeout: 30000 });
    await page.evaluate(() => {
      window.__lastKey = null;
      document.addEventListener("keydown", (e) => {
        window.__lastKey = { key: e.key, ctrlKey: !!e.ctrlKey, prevented: e.defaultPrevented, tag: e.target && e.target.tagName };
      });
    });

    const T = await scanTargets(page, PACK);
    report.pack = T.pack; report.targets = T;
    check("运行时发现：可见文本/数值字段", !!T.text, T.text);
    check("运行时发现：可见 listtable", !!T.list, T.list);
    check("运行时发现：可见 kvtable", !!T.kv, T.kv);
    if (!T.text || !T.list || !T.kv) { throw new Error("未能发现三类可见控件，无法继续"); }

    check("初始撤销按钮禁用（空栈）", await page.isDisabled("#btn-undo"));
    check("初始重做按钮禁用（空栈）", await page.isDisabled("#btn-redo"));

    // ============ 用例1：字段编辑 → 撤销 → 重做（文本/数值目标） ============
    await selectEntry(page, T.text.module, T.text.entry);
    await revealField(page, T.text.key);
    const textSel = `#p-body .row[data-field="${T.text.key}"] [data-key="${T.text.key}"]`;
    const beforeVal = String(await page.inputValue(textSel));
    const textVal = beforeVal + "_u33";
    await page.fill(textSel, textVal);
    check("字段编辑后 DOM 值 = 新值", (await page.inputValue(textSel)) === textVal);
    check("字段编辑进入草稿", await page.evaluate((k) => Object.prototype.hasOwnProperty.call(window.draft.changes, k), T.text.key));
    check("字段编辑后撤销按钮可用", await page.isEnabled("#btn-undo"));
    await shot(page, "01_field_edited.png");
    await page.click("#btn-undo");
    check("撤销后控件值回退", (await page.inputValue(textSel)) === beforeVal,
          { now: await page.inputValue(textSel), expected: beforeVal });
    check("撤销后草稿不再含该字段", !(await page.evaluate((k) => Object.prototype.hasOwnProperty.call(window.draft.changes, k), T.text.key)));
    await shot(page, "02_field_undone.png");
    await page.click("#btn-redo");
    check("重做后控件值恢复", (await page.inputValue(textSel)) === textVal,
          { now: await page.inputValue(textSel), expected: textVal });
    check("重做后草稿再次含该字段", await page.evaluate((k) => Object.prototype.hasOwnProperty.call(window.draft.changes, k), T.text.key));
    await shot(page, "03_field_redone.png");
    await page.evaluate(() => { window.discardDraft(); });

    // ============ 用例2：列表 增行 → 撤销；删行 → 撤销 ============
    await selectEntry(page, T.list.module, T.list.entry);
    await revealField(page, T.list.key);
    const lwrap = `#p-body .lwrap[data-lwrap="${T.list.key}"]`;
    const rowCount = () => page.$$eval(`${lwrap} tbody tr`, (trs) => trs.length);
    const n0 = await rowCount();
    await page.locator(`${lwrap} [data-ladd="${T.list.key}"]`).click();
    const nAdd = await rowCount();
    check("列表增行后行数 +1", nAdd === n0 + 1, { before: n0, after: nAdd });
    await shot(page, "04_list_added.png");
    await page.click("#btn-undo");
    const nUndoAdd = await rowCount();
    check("增行后撤销 → 行数回退", nUndoAdd === n0, { before: n0, after: nUndoAdd });
    await shot(page, "05_list_add_undone.png");
    if (n0 > 0) {
      await page.locator(`${lwrap} [data-ldel="0"]`).click();
      const nDel = await rowCount();
      check("列表删行后行数 -1", nDel === n0 - 1, { before: n0, after: nDel });
      await page.click("#btn-undo");
      const nUndoDel = await rowCount();
      check("删行后撤销 → 行数恢复", nUndoDel === n0, { before: n0, after: nUndoDel });
      await shot(page, "06_list_del_undone.png");
    } else {
      check("列表删行用例（原表为空 → 跳过删行）", true, { n0 });
    }
    await page.evaluate(() => { window.discardDraft(); });

    // ============ 用例3：键值表格 改键 → 撤销 ============
    await selectEntry(page, T.kv.module, T.kv.entry);
    await revealField(page, T.kv.key);
    const kvSel = `#p-body .kvwrap[data-kvwrap="${T.kv.key}"] [data-kvkey="${T.kv.key}"][data-kvrow="0"]`;
    await page.waitForSelector(kvSel, { timeout: 10000, state: "visible" });
    const key0 = await page.inputValue(kvSel);
    const key1 = key0 + "_k33";
    await page.fill(kvSel, key1);
    check("键值表格改键后输入框 = 新键", (await page.inputValue(kvSel)) === key1);
    check("改键进入草稿", await page.evaluate((k) => Object.prototype.hasOwnProperty.call(window.draft.changes, k), T.kv.key));
    await shot(page, "07_kv_key_changed.png");
    await page.click("#btn-undo");
    check("改键后撤销 → 键名回退", (await page.inputValue(kvSel)) === key0,
          { now: await page.inputValue(kvSel), expected: key0 });
    await shot(page, "08_kv_key_undone.png");
    await page.evaluate(() => { window.discardDraft(); });

    // ============ 用例4：快捷键（输入框外生效 / 输入框内不抢键） ============
    await selectEntry(page, T.text.module, T.text.entry);
    await revealField(page, T.text.key);
    const shortcutBase = String(await page.inputValue(textSel));
    const shortcutVal = shortcutBase + "_sc33";
    // 4a · 输入框内：应用层不得接管（不 preventDefault），全局撤销栈不得变化
    await page.fill(textSel, shortcutVal);
    await page.focus(textSel);
    await page.evaluate(() => { window.__lastKey = null; });
    await page.keyboard.press("Control+z");
    const keyInInput = await page.evaluate(() => window.__lastKey);
    const redoAfterInside = await page.evaluate(() => window.EditorHistory.redoDepth(window.hist));
    check("输入框内 Ctrl+Z 未被应用层接管（未 preventDefault）",
          keyInInput && keyInInput.prevented === false, keyInInput);
    check("输入框内 Ctrl+Z 未触发全局撤销（全局 redo 栈仍为空）",
          redoAfterInside === 0, { redoAfterInside });
    await shot(page, "09_shortcut_in_input.png");
    // 4b · 输入框外：应用层接管并真的撤销
    await page.evaluate(() => { if (document.activeElement) { document.activeElement.blur(); } });
    await page.fill(textSel, shortcutVal);
    await page.evaluate(() => { if (document.activeElement) { document.activeElement.blur(); } });
    await page.waitForFunction(() => document.activeElement && document.activeElement.tagName === "BODY",
                               null, { timeout: 5000 });
    const depthBeforeOutside = await page.evaluate(() => window.EditorHistory.depth(window.hist));
    await page.evaluate(() => { window.__lastKey = null; });
    await page.keyboard.press("Control+z");
    const keyOutside = await page.evaluate(() => window.__lastKey);
    const depthAfterOutside = await page.evaluate(() => window.EditorHistory.depth(window.hist));
    const redoAfterOutside = await page.evaluate(() => window.EditorHistory.redoDepth(window.hist));
    check("输入框外 Ctrl+Z 被应用层接管（preventDefault）",
          keyOutside && keyOutside.prevented === true, keyOutside);
    check("输入框外 Ctrl+Z 触发全局撤销（值回退 + 全局栈前进）",
          (await page.inputValue(textSel)) === shortcutBase
          && depthAfterOutside === depthBeforeOutside - 1 && redoAfterOutside === 1,
          { now: await page.inputValue(textSel), expected: shortcutBase,
            depthBeforeOutside, depthAfterOutside, redoAfterOutside });
    await shot(page, "10_shortcut_outside.png");
    await page.keyboard.press("Control+Shift+z");
    check("Ctrl+Shift+Z 重做（值恢复）", (await page.inputValue(textSel)) === shortcutVal,
          { now: await page.inputValue(textSel), expected: shortcutVal });
    await page.keyboard.press("Control+z");
    await page.keyboard.press("Control+y");
    check("Ctrl+Y 重做（值恢复）", (await page.inputValue(textSel)) === shortcutVal,
          { now: await page.inputValue(textSel), expected: shortcutVal });
    await page.evaluate(() => { window.discardDraft(); });

    // ============ 用例5：切换条目（口径二：切走提示未保存改动） ============
    let switchOther = null;
    for (const cand of [T.text.module, T.list.module, T.kv.module]) {
      await page.locator(`#mods .mod[data-module="${cand}"]`).first().click();
      await page.waitForTimeout(150);
      const ids = await page.$$eval("#rows .item[data-id]", (its) => its.map((i) => i.dataset.id));
      if (ids.length >= 2) { switchOther = ids.find((id) => id !== T.text.entry) || ids[1]; break; }
    }
    await selectEntry(page, T.text.module, T.text.entry);
    await revealField(page, T.text.key);
    if (switchOther) {
      await page.fill(textSel, textVal);
      const dirtyCount = await page.evaluate(() => window.draftCount());
      page.__acceptDialog = false;
      const beforeDialogs = dialogs.length;
      await page.click(`#rows .item[data-id="${switchOther}"]`);
      await page.waitForTimeout(300);
      const dlg = dialogs[dialogs.length - 1];
      check("切换条目弹出未保存改动确认", dialogs.length > beforeDialogs && dlg && dlg.type === "confirm", dlg);
      check("确认取消 → 仍停留原条目、草稿保留",
            (await page.evaluate(() => window.state.entry)) === T.text.entry
            && (await page.evaluate(() => window.draftCount())) === dirtyCount,
            { entry: await page.evaluate(() => window.state.entry) });
      await shot(page, "11_switch_guard_cancel.png");
      page.__acceptDialog = true;
      await page.click(`#rows .item[data-id="${switchOther}"]`);
      await page.waitForFunction((id) => window.state.entry === id, switchOther, { timeout: 20000 });
      check("确认离开 → 切到新条目", (await page.evaluate(() => window.state.entry)) === switchOther);
      check("切走后撤销按钮禁用（栈随草稿清空）", await page.isDisabled("#btn-undo"));
      await shot(page, "12_switch_guard_accept.png");
      page.__acceptDialog = false;
    } else {
      check("切换条目用例（同模块均仅一条 → 跳过）", true, {});
    }

    // ============ 用例6：保存后栈清空（撤销按钮置灰） ============
    await selectEntry(page, T.text.module, T.text.entry);
    await revealField(page, T.text.key);
    const saveBase = String(await page.inputValue(textSel));
    const saveVal = saveBase + "_save33";
    await page.fill(textSel, saveVal);
    check("保存前置：有未保存改动 + 撤销可用",
          (await page.isEnabled("#btn-undo")) && (await page.evaluate(() => window.draftCount() > 0)));
    await shot(page, "13_before_save.png");
    await page.click("#btn-save");
    await page.waitForFunction(() => document.getElementById("btn-undo").disabled
      && document.getElementById("dirty").textContent === "已保存", null, { timeout: 30000 });
    check("保存后撤销按钮置灰（栈已清）", await page.isDisabled("#btn-undo"));
    check("保存后重做按钮置灰", await page.isDisabled("#btn-redo"));
    check("保存后控件值 = 保存值（草稿已并入基准）",
          (await page.inputValue(textSel)) === saveVal,
          { now: await page.inputValue(textSel), expected: saveVal });
    await shot(page, "14_after_save_stack_cleared.png");

    report.ok = failures === 0;
  } catch (err) {
    report.error = String((err && err.stack) || err);
    console.error("[ERROR]", report.error);
  } finally {
    fs.writeFileSync(path.join(SHOTS, "report.json"), JSON.stringify(report, null, 2), "utf8");
    await browser.close();
  }
  const passed = report.checks.filter((c) => c.ok).length;
  console.log(`\n== 批33 DOM 证据：${passed}/${report.checks.length} PASS；截图 ${report.shots.length} 张；`
    + `report.json → ${SHOTS}/report.json ==`);
  process.exit(report.ok && !report.error ? 0 : 1);
})();
