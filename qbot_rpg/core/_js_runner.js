// 公式安全求值 Node 宿主（M1 · qbot_rpg/core/formula_engine.py 的后端执行器）
// ---------------------------------------------------------------------------
// 依据：《效果表达式变量体系定稿》§1.2 ——
//   - vm.runInNewContext 隔离全局（不暴露宿主全局对象）
//   - 代码强制 'use strict'（防 this 指向全局）
//   - 单次求值超时 vm timeout 10ms（CPU 死循环/ReDoS 可中断）
//   - 结果类型白名单 number（NaN/Infinity/其他类型 = 失败兜底）
//   - Math.random 确定性种子（rng_state → mulberry32；同一结算内复用 → 预览/结算一致）
// 协议：stdin 一行 JSON {code, sandbox, timeout_ms}；stdout JSON {ok, value, error, type}。
// 零 NoneBot，纯函数（每求值一次进程；Python 侧负责黑名单/占位符/长度）。
// ---------------------------------------------------------------------------
'use strict';

const vm = require('node:vm');

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  let out;
  try {
    const req = JSON.parse(input);
    out = run(
      typeof req.code === 'string' ? req.code : '',
      req.sandbox || {},
      typeof req.timeout_ms === 'number' ? req.timeout_ms : 10
    );
  } catch (e) {
    out = { ok: false, error: 'runner_fatal', type: typeof e, value: String((e && e.message) || e) };
  }
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
});

// 确定性 PRNG：mulberry32（seed 为 32 位无符号数）
function mulberry32(seed) {
  let a = (seed >>> 0);
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 构造沙箱 Math：克隆宿主 Math 静态成员（min/max/floor/...），random 换成（可选种子）PRNG
function buildMath(random) {
  const m = Object.create(null);
  for (const k of Object.getOwnPropertyNames(Math)) {
    const v = Math[k];
    if (typeof v === 'function') { m[k] = v.bind(Math); }
    else if (k === 'PI' || k === 'E' || k === 'LN2' || k === 'LN10' || k === 'LOG2E' ||
             k === 'LOG10E' || k === 'SQRT2' || k === 'SQRT1_2') {
      m[k] = v;
    }
  }
  m.random = random;
  return m;
}

function run(code, sandbox, timeoutMs) {
  let random = Math.random.bind(Math);
  const rawSeed = sandbox.__rng_seed;
  if (typeof rawSeed === 'number' && Number.isFinite(rawSeed) && Number.isInteger(rawSeed)) {
    random = mulberry32(rawSeed);
  }
  delete sandbox.__rng_seed; // 种子不暴露给公式代码
  sandbox.Math = buildMath(random);

  // 注意：必须用 runInNewContext 的 {timeout}，而非 new vm.Script(code,{timeout})——
  // 实证（Node v22）Script 构造期 timeout 对 `while(true){}` 类紧循环不生效（挂死），
  // runInNewContext 的 timeout 生效（抛 ERR_SCRIPT_EXECUTION_TIMEOUT）。定稿 §1.2「vm timeout 10ms」。
  const result = vm.runInNewContext('"use strict";\n' + code, sandbox, {
    timeout: timeoutMs,
    filename: 'qbot_formula.js',
  });

  // 结果类型白名单（定稿 §1.2 L38：number / boolean / string≤1KB）——boolean/string 数值化交给
  // Python 侧（evaluate_detail）；超长字符串与 NaN/Infinity/对象 → 失败兜底
  const type = typeof result;
  if (type === 'number' && Number.isFinite(result)) {
    return { ok: true, value: result, type: 'number' };
  }
  if (type === 'boolean') {
    return { ok: true, value: result ? 1 : 0, type: 'boolean' };
  }
  if (type === 'string' && result.length <= 1024) {
    return { ok: true, value: result, type: 'string' };
  }
  return { ok: false, error: 'result_type', type: type, value: null };
}
