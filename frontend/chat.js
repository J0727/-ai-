/* 智汇研途 · 对话前端
 * 安全约束：零外部依赖；所有动态内容先转义再渲染；外链仅放行 https + 白名单域名；
 * 通过 Trusted Types 策略写入 innerHTML，配合服务端严格 CSP。 */
(function () {
  'use strict';

  // ---------- Trusted Types ----------
  var TT = (window.trustedTypes && window.trustedTypes.createPolicy)
    ? window.trustedTypes.createPolicy('zhihui-render', { createHTML: function (s) { return s; } })
    : null;
  function setHTML(el, html) {
    el.innerHTML = TT ? TT.createHTML(html) : html;
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  var URL_HOSTS = ['doi.org', 'dx.doi.org', 'www.termonline.cn', 'termonline.cn',
    'api.crossref.org', 'www.crossref.org', 'api.openalex.org', 'openalex.org',
    'www.ebi.ac.uk', 'europepmc.org', 'doaj.org', 'arxiv.org', 'export.arxiv.org',
    'zenodo.org', 'www.semanticscholar.org', 'dblp.org', 'pubmed.ncbi.nlm.nih.gov'];
  function safeUrl(u) {
    try {
      var p = new URL(u);
      if (p.protocol !== 'https:') return '';
      var h = p.hostname.toLowerCase();
      return URL_HOSTS.indexOf(h) >= 0 ? p.href : '';
    } catch (e) { return ''; }
  }

  // ---------- DOM ----------
  var $ = function (id) { return document.getElementById(id); };
  var app = $('app'), thread = $('thread'), input = $('input'), sendBtn = $('sendBtn');
  var evBody = $('evBody'), evPanel = $('evidencePanel');

  // ---------- 状态 ----------
  var S = {
    token: sessionStorage.getItem('zhihui.session') || '',
    sending: false,
    apiReady: false,
    convId: 'c' + Date.now(),
    convs: [],
    messages: [],
    tools: [],
    reports: [],
    citations: [],
    verification: null,
    tab: 'sources',
    security: null,
    doc: null,
    persist: localStorage.getItem('zhihui.persist') === '1'
  };
  $('persistToggle').checked = S.persist;
  $('persistHint').textContent = S.persist ? '仅存本机' : '默认不落盘';
  app.classList.add('no-evidence');
  if (window.innerWidth <= 820) app.classList.add('no-sidebar');

  var FALLBACK_TOOLS = [
    { key: 'literature', name: '全网文献检索', icon: 'search', rigor: true, examples: ['检索 transformer 在医学影像中的文献'] },
    { key: 'citation', name: '引用真伪核验', icon: 'quote', rigor: true, examples: ['核验这条引用：10.1038/nature12373'] },
    { key: 'term', name: '术语速查', icon: 'book', rigor: true, examples: ['「卷积神经网络」的标准英译是什么'] },
    { key: 'translate', name: '学术翻译核验', icon: 'language', rigor: true, examples: ['把这句话译成英语并核验：本研究提出一种新方法'] },
    { key: 'compare', name: '多篇对比阅读', icon: 'columns', rigor: true, examples: ['对比 BERT 和 GPT 的相关研究'] },
    { key: 'survey', name: '综述框架', icon: 'document', rigor: true, examples: ['写一个关于扩散模型的综述框架'] },
    { key: 'viewpoint', name: '观点梳理', icon: 'bulb', rigor: true, examples: ['梳理各家对大模型幻觉的观点'] },
    { key: 'analyze', name: '文献解析', icon: 'analyze', rigor: true, examples: ['解析这篇文献的问题、方法与局限'] },
    { key: 'polish', name: '学术润色', icon: 'wand', rigor: true, examples: ['帮我润色：这个实验的结果说明了这个方法很好'] },
    { key: 'plagiarism', name: '查重风险', icon: 'scan', rigor: false, examples: ['这段文字有没有查重风险'] },
    { key: 'interpret', name: '图表公式解读', icon: 'chart', rigor: false, examples: ['解释一下 softmax 公式'] },
    { key: 'visualize', name: '数据可视化', icon: 'chart', rigor: false, examples: ['帮我看看这段 CSV 适合画什么图'] },
    { key: 'latex', name: 'LaTeX 生成', icon: 'code', rigor: false, examples: ['把这段表格转成 LaTeX'] },
    { key: 'upload', name: '导入文献', icon: 'upload', rigor: false, examples: ['我刚上传的 PDF 里，作者的核心结论是什么'] },
    { key: 'reader', name: '文档阅读', icon: 'pdf', rigor: false, examples: ['根据我导入的文档，样本量是多少'] },
    { key: 'privacy', name: '隐私与安全', icon: 'shield', rigor: false, examples: ['现在的安全配置是什么'] },
    { key: 'help', name: '能力总览', icon: 'spark', rigor: false, examples: ['你能做什么'] }
  ];
  var EXAMPLES = [
    '检索 transformer 在医学影像中的文献',
    '「卷积神经网络」的标准英译是什么',
    '核验这条引用：10.1038/nature12373',
    '把这句话译成英语并核验：本研究提出一种新方法',
    '对比 BERT 和 GPT 的相关研究',
    '现在的安全配置是什么'
  ];

  // ---------- 工具函数 ----------
  function toast(msg, ms) {
    var t = $('toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.hidden = true; }, ms || 2600);
  }
  // 源码静态预览（无后端）时给出明确说明，避免看起来像「界面坏了」
  function showPreviewTip() {
    if (document.getElementById('previewTip')) return;
    var d = document.createElement('div');
    d.id = 'previewTip';
    d.setAttribute('role', 'status');
    d.setAttribute('style', 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:9999;'
      + 'max-width:min(640px,92vw);padding:10px 16px;border-radius:10px;background:#052F7B;color:#fff;'
      + 'font-size:13px;line-height:1.6;box-shadow:0 8px 24px rgba(5,47,123,.28);text-align:center');
    d.textContent = '当前是源码静态预览，样式已正常但交互需要后端。请打开 http://127.0.0.1:8011/ 使用完整对话功能。';
    document.body.appendChild(d);
  }
  function scrollBottom() { setTimeout(function () { thread.scrollTop = thread.scrollHeight; }, 0); }
  function nowTime() {
    var d = new Date();
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  var ICON = {
    search: '<circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/>',
    quote: '<path d="M7 7h4v5H7zM14 7h4v5h-4z"/><path d="M7 12c0 3-1 4-3 5M14 12c0 3-1 4-3 5"/>',
    book: '<path d="M4 5h7v14H4zM13 5h7v14h-7z"/><path d="M6 9h3M15 9h3"/>',
    language: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18"/>',
    columns: '<rect x="3" y="4" width="8" height="16" rx="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5"/>',
    document: '<path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 15h7"/>',
    bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.7.5 1 1.2 1 2.1h5c0-.9.3-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
    analyze: '<circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4M11 7v4M9 9h4"/>',
    wand: '<path d="m4 20 10-10M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 10l.7 1.3 1.3.7-1.3.7L19 14l-.7-1.3-1.3-.7 1.3-.7z"/>',
    scan: '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4M8 12h8"/>',
    chart: '<path d="M4 20h16M6 16v-5M11 16V7M16 16v-8"/>',
    code: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
    upload: '<path d="M12 16V4M8 8l4-4 4 4M4 16v3h16v-3"/>',
    pdf: '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h6M9 16h6"/>',
    shield: '<path d="M12 3 20 6v6c0 4.5-3.2 7.7-8 9-4.8-1.3-8-4.5-8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    spark: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'
  };
  function icon(name) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICON[name] || ICON.spark) + '</svg>';
  }

  // ---------- 受控 Markdown 渲染 ----------
  function inline(s) {
    var out = esc(s);
    // 引用角标
    out = out.replace(/\[(\d{1,2})\]/g, function (_, n) {
      return '<span class="cite-sup" data-cite="' + n + '" title="查看溯源">' + n + '</span>';
    });
    // 自动链接 <https://...>
    out = out.replace(/&lt;(https:\/\/[^&\s]+)&gt;/g, function (_, u) {
      var href = safeUrl(u.replace(/&amp;/g, '&'));
      return href ? '<a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + esc(u) + '</a>' : esc(u);
    });
    // 行内代码
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
    // 粗体（内容已被转义，不会再引入标签）
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    return out;
  }
  function renderMarkdown(src, streaming) {
    var lines = String(src || '').split('\n');
    var html = [], i = 0, inList = false, inRejected = false, rejectedCount = 0;
    function closeList() { if (inList) { html.push('</ul>'); inList = false; } }
    for (; i < lines.length; i++) {
      var ln = lines[i];
      if (/^@@REJECTED_START@@(\d+)?/.test(ln)) {
        closeList(); inRejected = true;
        rejectedCount = (ln.match(/\d+/) || ['0'])[0];
        html.push('<details class="rejected-box"><summary>未通过核验 ' + rejectedCount + ' 条（不纳入结论）</summary><ul>');
        continue;
      }
      if (ln.indexOf('@@REJECTED_END@@') === 0) {
        if (inList) { html.push('</ul>'); inList = false; }
        html.push('</ul></details>'); inRejected = false; continue;
      }
      if (!ln.trim()) { closeList(); html.push('<div style="height:6px"></div>'); continue; }
      var bullet = ln.match(/^\s*[-•]\s+(.*)$/);
      var ordered = ln.match(/^\s*\d+\.\s+(.*)$/);
      if (bullet || ordered) {
        if (!inList) { html.push('<ul>'); inList = true; }
        html.push('<li>' + inline((bullet || ordered)[1]) + '</li>'); continue;
      }
      closeList();
      var h = ln.match(/^#{2,4}\s+(.*)$/);
      if (h) { html.push('<h3>' + inline(h[1]) + '</h3>'); continue; }
      if (/^&gt;\s?|^>\s?/.test(ln)) { html.push('<blockquote>' + inline(ln.replace(/^&gt;\s?|^>\s?/, '')) + '</blockquote>'); continue; }
      html.push('<p>' + inline(ln) + '</p>');
    }
    closeList();
    if (inRejected) html.push('</ul></details>');
    if (streaming) html.push('<span class="stream-cursor"></span>');
    return html.join('');
  }

  // ---------- 会话管理 ----------
  function loadConvs() {
    if (!S.persist) return;
    try {
      var d = JSON.parse(localStorage.getItem('zhihui.chat.v2') || '{}');
      S.convs = d.convs || [];
    } catch (e) { S.convs = []; }
  }
  function saveConvs() {
    if (!S.persist) { localStorage.removeItem('zhihui.chat.v2'); return; }
    try {
      localStorage.setItem('zhihui.chat.v2', JSON.stringify({ convs: S.convs.slice(0, 20) }));
    } catch (e) { }
  }
  function renderConvs() {
    var host = $('convList');
    if (!S.convs.length) {
      setHTML(host, '<div style="font-size:11.5px;color:#9aa9bc;padding:6px 9px">暂无记录' + (S.persist ? '' : '（未开启本机保存）') + '</div>');
    } else {
      setHTML(host, S.convs.map(function (c) {
        return '<div class="conv-item' + (c.id === S.convId ? ' active' : '') + '" data-id="' + esc(c.id) + '">' +
          '<span>' + esc(c.title) + '</span>' +
          '<button class="del" data-del="' + esc(c.id) + '" title="删除">' + icon('shield') + '</button></div>';
      }).join(''));
    }
    $('convCount').textContent = S.convs.length;
  }
  function remember(title, text) {
    var c = S.convs.filter(function (x) { return x.id === S.convId; })[0];
    if (!c) { c = { id: S.convId, title: title.slice(0, 22) }; S.convs.unshift(c); }
    (c.messages = c.messages || []).push(text);
    saveConvs(); renderConvs();
  }
  function newChat() {
    if (S.sending) return;
    S.convId = 'c' + Date.now();
    S.messages = []; S.citations = []; S.reports = []; S.verification = null;
    setHTML(thread, '');
    // 重新插入欢迎区
    var w = document.createElement('section');
    w.className = 'welcome'; w.id = 'welcome';
    setHTML(w, welcomeHTML());
    thread.appendChild(w);
    $('topTitle').textContent = '新的对话';
    renderEvidence(); renderConvs();
    input.focus();
  }

  function welcomeHTML() {
    return '<div class="welcome-logo">' + icon('spark') + '</div>' +
      '<h1>你好，我是智汇研途</h1>' +
      '<p class="welcome-sub">原来分散在 13 个页面里的科研工具，现在都在这一个对话框里。<br>你只管说需求，我来找证据、做复核、给结论。</p>' +
      '<div class="principles">' +
      '<div class="principle"><div class="p-ico blue">' + icon('document') + '</div><b>逐条溯源</b><span>文献带 DOI 与原文链接，译名带国标标准号</span></div>' +
      '<div class="principle"><div class="p-ico teal">' + icon('shield') + '</div><b>独立复核</b><span>换通道重新确认「是否真的存在」，不轻信单次结果</span></div>' +
      '<div class="principle"><div class="p-ico violet">' + icon('analyze') + '</div><b>一致才显示</b><span>两次答案一致才进结论；不一致的一律公示剔除</span></div>' +
      '</div><div class="try-label">试试这样问</div><div class="examples" id="examples">' +
      EXAMPLES.slice(0, 6).map(function (t, i) {
        return '<button class="example" data-q="' + esc(t) + '" type="button"><span class="ex-n">' + (i + 1) + '</span><span>' + esc(t) + '</span></button>';
      }).join('') + '</div>';
  }

  function renderTools() {
    var list = S.tools.length ? S.tools : FALLBACK_TOOLS;
    $('toolCount').textContent = list.length;
    setHTML($('toolList'), list.map(function (t) {
      return '<button class="tool-item' + (t.rigor ? ' rigor' : '') + '" data-tool="' + esc(t.key) + '" title="' + esc(t.desc || '') + '" type="button">' +
        '<span class="ti">' + icon(t.icon || 'spark') + '</span><em>' + esc(t.name) + '</em></button>';
    }).join(''));
    var quick = list.filter(function (t) { return ['literature', 'term', 'translate', 'citation', 'compare', 'survey', 'polish', 'analyze'].indexOf(t.key) >= 0; }).slice(0, 8);
    setHTML($('capbar'), quick.map(function (t) {
      return '<button class="cap-chip" data-tool="' + esc(t.key) + '" type="button">' + icon(t.icon || 'spark') + esc(t.name) + '</button>';
    }).join(''));
    setHTML($('examples'), EXAMPLES.slice(0, 6).map(function (t, i) {
      return '<button class="example" data-q="' + esc(t) + '" type="button"><span class="ex-n">' + (i + 1) + '</span><span>' + esc(t) + '</span></button>';
    }).join(''));
  }

  // ---------- 消息 ----------
  function addUser(text) {
    var row = document.createElement('div');
    row.className = 'msg-row me';
    setHTML(row, '<div class="msg-avatar me">我</div><div class="msg-main"><div class="msg-bubble">' + esc(text) + '</div></div>');
    thread.appendChild(row); scrollBottom();
  }
  function addAI() {
    var w = $('welcome'); if (w) w.remove();
    var row = document.createElement('div');
    row.className = 'msg-row';
    setHTML(row, '<div class="msg-avatar ai">' + icon('spark') + '</div>' +
      '<div class="msg-main"><div class="msg-name">智汇研途 · 严谨模式</div>' +
      '<div class="steps"></div><div class="msg-bubble"></div></div>');
    thread.appendChild(row); scrollBottom();
    return { row: row, bubble: row.querySelector('.msg-bubble'), steps: row.querySelector('.steps') };
  }
  function addStep(host, label, status) {
    var d = document.createElement('div');
    d.className = 'step' + (status === 'done' ? ' done' : '');
    setHTML(d, '<span class="s-dot"></span><span>' + esc(label) + '</span>');
    host.appendChild(d); scrollBottom();
  }
  function finishAI(view, verification) {
    var bar = document.createElement('div');
    bar.className = 'verify-bar';
    var v = verification || {};
    var chips = [
      '<span class="v-chip brand">门控：' + esc(v.gate || 'STRICT') + '</span>',
      '<span class="v-chip ok">✓ 已核验 ' + (v.verified_claims || 0) + ' 条</span>',
      '<span class="v-chip warn">未通过 ' + (v.rejected_claims || 0) + ' 条</span>',
      '<span class="v-chip">溯源 ' + (v.citations || 0) + ' 条</span>'
    ];
    setHTML(bar, chips.join('') + '<button type="button" class="v-chip" data-open-ev="1">查看复核详情 →</button>');
    view.row.querySelector('.msg-main').appendChild(bar);
    var acts = document.createElement('div');
    acts.className = 'msg-actions';
    setHTML(acts, '<button type="button" data-copy="1">复制回答</button><button type="button" data-open-ev="1">溯源面板</button>');
    view.row.querySelector('.msg-main').appendChild(acts);
  }

  // ---------- 证据面板 ----------
  function renderEvidence() {
    $('tabSrcCount').textContent = S.citations.length;
    $('evSub').textContent = S.citations.length ? ('本轮 ' + S.citations.length + ' 条可点击溯源') : '本轮暂无证据';
    if (S.tab === 'sources') renderSources();
    else if (S.tab === 'checks') renderChecks();
    else renderSecurity();
  }
  function switchTab(t) {
    S.tab = t;
    Array.prototype.forEach.call(document.querySelectorAll('.ev-tab'), function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === t);
    });
    renderEvidence();
  }
  function renderSources() {
    if (!S.citations.length) {
      setHTML(evBody, '<div class="ev-empty">' + icon('shield') +
        '<div>本轮还没有可展示的证据。<br>发起「文献检索 / 术语 / 翻译 / 引用核验」后，<br>每条结论的溯源与复核记录会出现在这里。</div></div>');
      return;
    }
    var h = ['<div class="ev-summary"><h4>本轮一致性门控</h4><div class="ev-grid">' +
      '<div><b>' + S.citations.length + '</b><span>已展示证据</span></div>' +
      '<div><b>' + (S.verification ? S.verification.verified_claims : S.citations.length) + '</b><span>复核一致</span></div>' +
      '<div><b>' + (S.verification ? S.verification.rejected_claims : 0) + '</b><span>剔除</span></div>' +
      '</div><div class="ev-note">只有被独立通道复核且答案一致的条目才会进入回答正文；冲突或无法复核的条目已移入「未通过核验」区。</div></div>'];
    S.citations.forEach(function (c, idx) {
      var n = c.n || idx + 1;
      var links = [];
      var u = safeUrl(c.url || '');
      if (u) links.push('<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + icon('spark') + '打开原文</a>');
      if (c.doi) {
        var du = safeUrl('https://doi.org/' + c.doi);
        if (du) links.push('<a href="' + esc(du) + '" target="_blank" rel="noopener noreferrer">DOI: ' + esc(c.doi) + '</a>');
      }
      (c.sources || []).slice(0, 3).forEach(function (s) {
        var su = safeUrl(s.url || '');
        if (su) links.push('<a href="' + esc(su) + '" target="_blank" rel="noopener noreferrer">' + esc((s.name || '来源').slice(0, 18)) + '</a>');
      });
      var meta = [];
      if (c.doi) meta.push('<b>DOI</b> ' + esc(c.doi));
      if (c.standard) meta.push('<b>标准号</b> ' + esc(c.standard));
      if (c.authors) meta.push('<b>作者</b> ' + esc(c.authors));
      if (c.year) meta.push('<b>年份</b> ' + esc(c.year));
      if (c.translation) meta.push('<b>审定译名</b> ' + esc(c.translation));
      if (c.text) meta.push('<b>原文片段</b> ' + esc(String(c.text).slice(0, 160)));
      if ((c.discovery || []).length) meta.push('<b>发现源</b> ' + esc(c.discovery.join('、')));
      if ((c.sources || []).length) meta.push('<b>溯源</b> ' + esc((c.sources[0].name || '').slice(0, 40)));
      var conf = Math.round((c.confidence || 0) * 100);
      var checks = c.checks || [];
      h.push('<div class="src-card" data-card="' + n + '">' +
        '<div class="src-top"><span class="src-n">' + n + '</span>' +
        '<span class="src-title">' + esc(c.title || c.kind || '证据') + '</span>' +
        '<span class="src-badge' + (c.verdict === 'verified' ? '' : ' quote') + '">' +
        (c.verdict === 'verified' ? '✓ ' + esc(c.agreement || '一致') : esc(c.verdict || '原文')) + '</span></div>' +
        (meta.length ? '<div class="src-meta">' + meta.join('<br>') + '</div>' : '') +
        (conf ? '<div class="conf-row"><span>置信度</span><span class="conf-bar"><span class="conf-fill" style="width:' + conf + '%"></span></span><b>' + conf + '%</b></div>' : '') +
        (links.length ? '<div class="src-links">' + links.join('') + '</div>' : '') +
        (checks.length ? '<button class="checks-toggle" data-checks="' + n + '" type="button">▸ 查看 ' + checks.length + ' 条独立复核记录</button>' +
          '<div class="check-list" data-checklist="' + n + '" hidden></div>' : '') +
        '</div>');
    });
    setHTML(evBody, h.join(''));
  }
  function renderChecks() {
    var items = [];
    S.reports.forEach(function (r, i) {
      var rep = r.report || {};
      var all = (rep.verified || []).concat(rep.rejected || []);
      all.forEach(function (e) {
        (e.checks || []).forEach(function (c) {
          items.push({ tool: r.kind || '核验', claim: e.claim || '', c: c });
        });
      });
    });
    if (!items.length) {
      setHTML(evBody, '<div class="ev-empty">' + icon('analyze') + '<div>本轮没有复核记录。<br>发起带溯源的检索后，每条通道的现场判定会逐条留痕。</div></div>');
      return;
    }
    setHTML(evBody, '<div class="ev-note" style="margin-bottom:12px">共 ' + items.length + ' 条通道判定。agree = 与候选一致，conflict = 明确冲突（直接剔除），unavailable = 通道不可用（不计数）。</div>' +
      items.slice(0, 80).map(function (x) {
        return '<div class="log-item"><div class="lt">' + esc(x.c.channel || '通道') + ' · <span style="color:' +
          (x.c.verdict === 'agree' ? '#0f9d6e' : x.c.verdict === 'conflict' ? '#dc2626' : '#8b9bb1') + '">' +
          esc(x.c.verdict || '') + '</span></div>' +
          '<div class="lm">' + esc(x.c.detail || '') + (x.c.title_similarity ? ' · 相似度 ' + esc(x.c.title_similarity) : '') + '</div>' +
          '<div class="lm">' + esc((x.claim || '').slice(0, 60)) + ' · ' + esc(x.c.checked_at || '') + '</div></div>';
      }).join(''));
  }
  function renderSecurity() {
    var s = S.security || {};
    if (!s.csp_chat) {
      setHTML(evBody, '<div class="ev-empty">安全配置未加载</div>'); return;
    }
    var hosts = (s.upstream_allowlist || []).map(function (h) { return '<em>' + esc(h) + '</em>'; }).join('');
    var rows = [
      ['内容安全策略', '对话页不加载任何外部脚本/样式；Trusted Types 强制；frame-ancestors none'],
      ['CSP 原文', '<code>' + esc(s.csp_chat) + '</code>'],
      ['SSRF 防护', esc(s.ssrf_guard || '') + '，环境代理 ' + esc(s.proxy_env || '')],
      ['会话令牌', esc(s.session || '')],
      ['提示注入', esc(s.prompt_injection || '')],
      ['审计日志', esc(s.audit || '')],
      ['请求体上限', (s.max_body_bytes || 0) + ' B · 上游超时 ' + (s.upstream_timeout_sec || 0) + ' s'],
      ['限流', '对话 ' + ((s.rate_limits || {}).chat || {}).limit + ' 次/分，核验 ' + ((s.rate_limits || {}).verify || {}).limit + ' 次/分'],
      ['可信来源', esc((s.trusted_origins || []).join('、'))],
      ['HSTS', esc(s.https_hsts || '')]
    ];
    setHTML(evBody, '<div class="ev-summary"><h4>默认即最严格</h4><div class="ev-note">失败即关闭：任何上游不可达、独立通道不足或答案冲突，都不会产出「已核验」结论。</div></div>' +
      rows.map(function (r) { return '<div class="sec-item"><b>' + esc(r[0]) + '</b><span>' + r[1] + '</span></div>'; }).join('') +
      '<div class="sec-item"><b>上游域名白名单（' + (s.upstream_allowlist || []).length + '）</b><div class="host-tags">' + hosts + '</div></div>');
  }

  // ---------- 规则说明 ----------
  function buildPolicy() {
    var p = (S.tools.length && window.__POLICY) ? window.__POLICY : null;
    var n = p ? p.checks_required : 2;
    var th = p ? p.title_similarity_threshold : 0.88;
    setHTML($('policyBody'),
      '<h3>严谨性：三道关卡</h3>' +
      '<div class="rule-flow"><span>① 发现</span><i>→</i><span>② 独立复核 ×' + n + '</span><i>→</i><span>③ 一致性门控</span><i>→</i><span>④ 才显示</span></div>' +
      '<ol>' +
      '<li><b>溯源</b>：每条文献带来源库、DOI、原文链接与抓取时间；每条译名带国标标准号、术语编码与术语在线详情页。</li>' +
      '<li><b>复核</b>：检索结果不直接采信。系统会换一条独立通道重新确认「是否真的存在这篇文献 / 这个译法」——例如用 DOI 直查 Crossref 注册记录、再用 OpenAlex 按 DOI 反查；译名则用所得英文反查回原中文。</li>' +
      '<li><b>门控</b>：标题归一化相似度需 ≥ ' + th + '，年份、作者、DOI 逐项比对；' + n + ' 条独立通道全部一致才标记 verified。任一冲突（含撤稿关系）立即剔除。</li>' +
      '<li><b>翻译</b>：两次彼此独立、无共享上下文的低温翻译逐句比对，再加回译复核；只有完全一致的句子才显示，不一致的两个版本并列供人工判断。</li>' +
      '<li><b>拒答</b>：上游不可达、通道数不足或未配置模型凭据时，明确说「无法给出可核验结论」，绝不编造。</li>' +
      '</ol>' +
      '<h3>安全性：默认最严格</h3><ul>' +
      '<li>严格 CSP：对话页零外部脚本/样式，Trusted Types 强制，禁止被嵌套。</li>' +
      '<li>SSRF 防护：上游仅 HTTPS + 域名白名单，DNS 解析后拒绝私网/保留地址，逐跳重定向重新校验，禁用环境代理。</li>' +
      '<li>会话令牌 HMAC-SHA256 签名 + 过期 + 随机数，恒定时间校验；审计日志只记输入哈希与长度，不记正文与密钥。</li>' +
      '<li>滑动窗口限流、请求体上限、上游响应体上限与全链路超时。</li>' +
      '<li>提示注入防护：用户输入与工具返回一律包成随机分隔的「数据」块，剥离伪造的角色标记。</li>' +
      '<li>导入的文档只驻留本机内存并按 TTL 清除；会话记录默认不落盘，可在本机自行开启。</li>' +
      '</ul>' +
      '<h3>与原工具的关系</h3><p>原来的 13 个工具页依然完整保留（左下角「经典工具页」）。对话版把它们变成可自动调用的能力：文献检索、引用核验、术语速查、学术翻译、多篇对比、综述框架、观点梳理、文献解析、学术润色、查重提示、图表解读、数据可视化、LaTeX、PDF 导入与阅读、隐私安全。</p>'
    );
  }

  // ---------- SSE 对话 ----------
  async function ensureSession() {
    if (S.token) return S.token;
    try {
      var r = await fetch('/api/v2/session', { method: 'POST' });
      var d = await r.json();
      S.token = d.token || '';
      sessionStorage.setItem('zhihui.session', S.token);
    } catch (e) { S.token = ''; }
    return S.token;
  }

  async function send(text) {
    text = (text || '').trim();
    if (!text || S.sending) return;
    if (!S.apiReady) {
      toast('当前是源码静态预览，交互请打开 http://127.0.0.1:8011/', 4200);
      return;
    }
    S.sending = true; sendBtn.disabled = true;
    addUser(text);
    var view = addAI();
    var raw = '', done = false;
    S.citations = []; S.reports = []; S.verification = null;
    renderEvidence();
    addStep(view.steps, '解析意图 · 匹配能力', 'done');

    try {
      var token = await ensureSession();
      var resp = await fetch('/api/v2/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Zhihui-Session': token },
        body: JSON.stringify({ message: text, session: token })
      });
      if (!resp.ok) {
        var err = await resp.json().catch(function () { return {}; });
        throw new Error(err.detail || ('HTTP ' + resp.status));
      }
      var reader = resp.body.getReader(), dec = new TextDecoder('utf-8'), buf = '';
      while (true) {
        var rd = await reader.read();
        if (rd.done) break;
        buf += dec.decode(rd.value, { stream: true });
        var parts = buf.split('\n\n');
        buf = parts.pop();
        for (var i = 0; i < parts.length; i++) {
          var block = parts[i];
          if (!block.trim()) continue;
          var ev = 'message', dataStr = '';
          block.split('\n').forEach(function (line) {
            if (line.indexOf('event:') === 0) ev = line.slice(6).trim();
            else if (line.indexOf('data:') === 0) dataStr += line.slice(5).trim();
          });
          var data = {};
          try { data = dataStr ? JSON.parse(dataStr) : {}; } catch (e) { data = { text: dataStr }; }
          handleEvent(ev, data, view, function (s) { raw = s; });
          if (ev === 'done') done = true;
        }
      }
    } catch (e) {
      raw += '\n\n**请求失败**：' + escClean(e.message || '网络错误') + '。请确认后端服务已启动。';
    } finally {
      setHTML(view.bubble, renderMarkdown(raw, false));
      view.steps.style.display = 'none';
      finishAI(view, S.verification);
      S.sending = false; sendBtn.disabled = false;
      S.messages.push({ role: 'assistant', text: raw });
      remember(text, raw);
      $('topTitle').textContent = text.slice(0, 20);
      scrollBottom(); input.focus();
    }
  }
  function escClean(s) { return String(s || '').replace(/[<>{}]/g, ''); }

  function handleEvent(ev, data, view, setRaw) {
    // setRaw 由闭包维护 current 文本
    if (ev === 'session') {
      if (data.token) { S.token = data.token; sessionStorage.setItem('zhihui.session', S.token); }
      return;
    }
    if (ev === 'meta') {
      window.__POLICY = data.policy || null;
      var names = (data.tools || []).map(function (t) { return t.name; });
      if (names.length) addStep(view.steps, '调用：' + names.join('、'), 'done');
      if ((data.injection_flags || []).length) addStep(view.steps, '疑似提示注入已按「数据」隔离', 'done');
      return;
    }
    if (ev === 'step') { addStep(view.steps, data.label || '', data.status); return; }
    if (ev === 'evidence') {
      S.reports.push({ kind: data.kind, report: data.report || {} });
      return;
    }
    if (ev === 'citations') {
      S.citations = data.items || [];
      renderEvidence();
      return;
    }
    if (ev === 'delta') {
      var cur = view.bubble.__raw || '';
      cur += (data.text || '');
      view.bubble.__raw = cur;
      setRaw(cur);
      setHTML(view.bubble, renderMarkdown(cur, true));
      scrollBottom();
      return;
    }
    if (ev === 'done') {
      S.verification = data.verification || null;
      renderEvidence();
      return;
    }
    if (ev === 'error') {
      var errText = (view.bubble.__raw || '') + '\n\n**处理失败**：' + (data.detail || '未知错误');
      view.bubble.__raw = errText;
      setRaw(errText);
      return;
    }
  }

  // ---------- 上传 ----------
  async function uploadFile(file) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) { toast('文件超过 20 MiB 上限'); return; }
    var token = await ensureSession();
    var fd = new FormData(); fd.append('file', file);
    toast('正在解析文档…');
    try {
      var r = await fetch('/api/v2/upload', { method: 'POST', headers: { 'X-Zhihui-Session': token }, body: fd });
      var d = await r.json();
      if (!r.ok) throw new Error(d.detail || '导入失败');
      S.doc = d.filename;
      $('docChip').textContent = '已导入：' + d.filename;
      $('docChip').hidden = false;
      toast('已导入 ' + d.filename + '，可直接就原文提问');
    } catch (e) { toast('导入失败：' + (e.message || '未知错误')); }
    $('fileInput').value = '';
  }

  // ---------- 事件绑定 ----------
  $('sendBtn').addEventListener('click', function () { send(input.value); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); }
  });
  input.addEventListener('input', function () {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 150) + 'px';
  });
  $('attachBtn').addEventListener('click', function () { $('fileInput').click(); });
  $('fileInput').addEventListener('change', function (e) { uploadFile(e.target.files[0]); });
  $('newChat').addEventListener('click', newChat);

  document.addEventListener('click', function (e) {
    var q = e.target.closest('[data-q]');
    if (q) { input.value = q.getAttribute('data-q'); input.focus(); input.dispatchEvent(new Event('input')); return; }
    var t = e.target.closest('[data-tool]');
    if (t) {
      var key = t.getAttribute('data-tool');
      var tool = (S.tools.length ? S.tools : FALLBACK_TOOLS).filter(function (x) { return x.key === key; })[0];
      var ex = tool && tool.examples && tool.examples[0];
      if (ex) { input.value = ex; input.focus(); input.dispatchEvent(new Event('input')); }
      else toast(key + '：直接把需求写进输入框即可');
      if (window.innerWidth <= 820) app.classList.add('no-sidebar');
      return;
    }
    if (e.target.closest('[data-open-ev]')) { app.classList.remove('no-evidence'); switchTab('sources'); return; }
    if (e.target.closest('[data-copy]')) {
      var b = e.target.closest('.msg-row').querySelector('.msg-bubble');
      navigator.clipboard && navigator.clipboard.writeText(b.innerText).then(function () { toast('已复制'); });
      return;
    }
    var cs = e.target.closest('[data-checks]');
    if (cs) {
      var n = cs.getAttribute('data-checks');
      var host = evBody.querySelector('[data-checklist="' + n + '"]');
      if (!host) return;
      if (!host.hidden) { host.hidden = true; cs.textContent = cs.textContent.replace('▾', '▸'); return; }
      var item = S.citations.filter(function (c) { return String(c.n) === n; })[0];
      if (item) {
        setHTML(host, (item.checks || []).map(function (c) {
          return '<div class="check ' + esc(c.verdict || 'unavailable') + '"><span class="c-dot"></span><div>' +
            '<b>' + esc(c.channel || '通道') + ' · ' + esc(c.verdict || '') + '</b><span>' + esc(c.detail || '') + '</span></div></div>';
        }).join(''));
      }
      host.hidden = false; cs.textContent = cs.textContent.replace('▸', '▾');
      return;
    }
    var sup = e.target.closest('.cite-sup');
    if (sup) {
      app.classList.remove('no-evidence'); switchTab('sources');
      var card = evBody.querySelector('[data-card="' + sup.getAttribute('data-cite') + '"]');
      if (card) { card.classList.add('highlight'); card.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(function () { card.classList.remove('highlight'); }, 1800); }
      return;
    }
    var conv = e.target.closest('[data-id]');
    if (conv && !e.target.closest('[data-del]')) {
      var c = S.convs.filter(function (x) { return x.id === conv.getAttribute('data-id'); })[0];
      if (c && c.messages && c.messages.length) {
        S.convId = c.id; $('topTitle').textContent = c.title;
        setHTML(thread, '');
        var row = document.createElement('div'); row.className = 'msg-row me';
        setHTML(row, '<div class="msg-avatar me">我</div><div class="msg-main"><div class="msg-bubble">' + esc(c.title) + '</div></div>');
        thread.appendChild(row);
        var ai = addAI(); setHTML(ai.bubble, renderMarkdown(c.messages[c.messages.length - 1] || '', false));
        renderConvs();
      }
      return;
    }
    var del = e.target.closest('[data-del]');
    if (del) {
      var id = del.getAttribute('data-del');
      S.convs = S.convs.filter(function (x) { return x.id !== id; });
      saveConvs(); renderConvs(); return;
    }
  });

  $('evidenceToggle').addEventListener('click', function () { app.classList.toggle('no-evidence'); renderEvidence(); });
  $('evClose').addEventListener('click', function () { app.classList.add('no-evidence'); });
  $('menuBtn').addEventListener('click', function () { app.classList.toggle('no-sidebar'); });
  $('secMiniBtn').addEventListener('click', function () { app.classList.remove('no-evidence'); switchTab('security'); });
  Array.prototype.forEach.call(document.querySelectorAll('.ev-tab'), function (b) {
    b.addEventListener('click', function () { switchTab(b.getAttribute('data-tab')); });
  });
  $('persistToggle').addEventListener('change', function () {
    S.persist = this.checked;
    localStorage.setItem('zhihui.persist', S.persist ? '1' : '0');
    $('persistHint').textContent = S.persist ? '仅存本机' : '默认不落盘';
    if (!S.persist) { S.convs = []; saveConvs(); }
    loadConvs(); renderConvs();
    toast(S.persist ? '已开启本机会话保存（不上传）' : '已关闭本地保存，历史记录已清除');
  });
  $('policyBtn').addEventListener('click', function () { buildPolicy(); $('policyModal').hidden = false; });
  $('policyModal').addEventListener('click', function (e) {
    if (e.target.getAttribute('data-close')) $('policyModal').hidden = true;
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') $('policyModal').hidden = true; });

  // ---------- 初始化 ----------
  async function init() {
    loadConvs(); renderConvs(); renderTools(); renderEvidence();
    try {
      var r = await fetch('/api/v2/tools');
      if (r.ok) {
        var d = await r.json();
        S.apiReady = true;
        S.tools = d.tools || [];
        window.__POLICY = d.policy || null;
        $('llmState').textContent = d.llm_configured ? '正在检测模型通道…' : '证据直出模式';
        $('llmState').title = d.llm_configured ? '配置存在不等于可用，正在独立探测' : '未配置大模型凭据：不生成任何未经核验的事实性内容';
        renderTools(); buildPolicy();
        if (d.security) { S.security = d.security; renderEvidence(); }
      } else {
        showPreviewTip();
        $('llmState').textContent = '后端未连接 · 静态预览';
      }
    } catch (e) {
      showPreviewTip();
      $('llmState').textContent = '后端未连接 · 静态预览';
    }
    try {
      var s = await fetch('/api/v2/security');
      if (s.ok) { S.security = await s.json(); renderEvidence(); }
    } catch (e) { }
    // 异步探测，不阻塞首屏
    try {
      var lr = await fetch('/api/v2/llm-status');
      if (lr.ok) {
        var llm = await lr.json();
        if (llm.available) {
          $('llmState').textContent = '模型通道可用';
          $('llmState').title = '仅用于语言组织与独立复核，事实一律来自已核验证据';
        } else {
          $('llmState').textContent = '模型不可用 · 证据直出';
          $('llmState').title = (llm.reason || '通道不可用') + '：不生成任何未经核验的译文或润色结果';
        }
      }
    } catch (e) { if (S.apiReady) { $('llmState').textContent = '模型状态未知 · 证据直出'; } }
    ensureSession();
  }
  init();
})();
