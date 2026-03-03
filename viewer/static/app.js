"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  users: {},          // id → {id, name, display_name, real_name}
  channels: {},       // id → {id, name, type, ...}
  channelsByFolder: {},  // folder_name → channel

  activeChannelId: null,
  currentPage: 1,
  totalPages: 1,
  perPage: 50,
  isLoadingMessages: false,

  searchQuery: "",
  searchPage: 1,
  searchTotalPages: 1,
};

// ── Nav history ───────────────────────────────────────────────────────────────
const navHistory = [];  // [{ channelId, threadTs, scrollTs }, ...]
let navHistoryIdx = -1;  // navHistory 내 현재 위치

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const el = {
  searchInput:       $("search-input"),
  msgsList:          $("messages-list"),
  msgsPlaceholder:   $("messages-placeholder"),
  loadMoreBtn:       $("load-more-btn"),
  channelTitle:      $("channel-title"),
  channelMeta:       $("channel-meta"),
  threadPanel:       $("thread-panel"),
  threadMessages:    $("thread-messages"),
  threadCloseBtn:    $("thread-close-btn"),
  searchOverlay:     $("search-overlay"),
  searchResultsList: $("search-results-list"),
  searchResultsTitle:$("search-results-title"),
  searchCloseBtn:    $("search-close-btn"),
  searchPagination:  $("search-pagination"),
  navBackBtn:        $("nav-back-btn"),
  navFwdBtn:         $("nav-fwd-btn"),
};

// ── Bootstrap ─────────────────────────────────────────────────────────────────
async function init() {
  try {
    const statusRes = await fetch("/api/status");
    const status = await statusRes.json();
    if (!status.ready) {
      el.msgsPlaceholder.innerHTML =
        "<p>⚠️ 데이터베이스가 준비되지 않았습니다.<br><br>" +
        "<code>python init_db.py ../backup/slack_export.zip</code><br><br>를 먼저 실행하세요.</p>";
      return;
    }

    const [usersData, channelsData] = await Promise.all([
      fetch("/api/users").then((r) => r.json()),
      fetch("/api/channels").then((r) => r.json()),
    ]);

    state.users = usersData;
    renderSidebar(channelsData);

    // Restore navigation state from URL hash (bookmark / page reload)
    const navFromHash = parseNavHash();
    // 초기 상태를 navHistory에 등록
    navHistory.push(navFromHash);
    navHistoryIdx = 0;
    history.replaceState({ ...navFromHash, _nidx: 0 }, "", location.hash);

    if (navFromHash.searchQuery) {
      // URL 해시에 검색 쿼리가 있으면 검색 오버레이 복원
      el.searchInput.value = navFromHash.searchQuery;
      const parsed = parseSearchQuery(navFromHash.searchQuery);
      renderFilterChips(parsed);
      if (hasSearchCriteria(parsed)) doSearch(parsed, 1);
    } else if (navFromHash.channelId && state.channels[navFromHash.channelId]) {
      selectChannel(navFromHash.channelId, { pushHistory: false });
      if (navFromHash.threadTs) {
        openThread(navFromHash.threadTs, navFromHash.scrollTs || null, { pushHistory: false });
      }
    }
    updateNavButtons();
  } catch (e) {
    el.msgsPlaceholder.innerHTML = `<p>서버에 연결할 수 없습니다: ${e.message}</p>`;
  }
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function renderSidebar(grouped) {
  const typeInfo = {
    public:   { listId: "ch-public",   icon: "#" },
    private:  { listId: "ch-private",  icon: "🔒" },
    group_dm: { listId: "ch-group_dm", icon: "💬" },
    dm:       { listId: "ch-dm",       icon: "👤" },
  };

  for (const [type, { listId, icon }] of Object.entries(typeInfo)) {
    const ul = $(listId);
    if (!ul) continue;
    const items = grouped[type] || [];
    ul.innerHTML = "";
    for (const ch of items) {
      state.channels[ch.id] = ch;
      const li = document.createElement("li");
      li.className = "ch-item";
      li.dataset.channelId = ch.id;
      li.innerHTML = `<i class="ch-icon">${icon}</i><span class="ch-name">${escapeHtml(ch.name)}</span>`;
      li.addEventListener("click", () => selectChannel(ch.id));
      ul.appendChild(li);
    }
  }
}

function selectChannel(channelId, { pushHistory = true } = {}) {
  if (state.activeChannelId === channelId) return;

  // Update sidebar active state
  document.querySelectorAll(".ch-item").forEach((li) => li.classList.remove("active"));
  const activeLi = document.querySelector(`.ch-item[data-channel-id="${channelId}"]`);
  if (activeLi) activeLi.classList.add("active");

  state.activeChannelId = channelId;
  state.currentPage = 1;
  state.totalPages = 1;
  el.msgsList.innerHTML = "";
  el.msgsPlaceholder.classList.add("hidden");
  el.loadMoreBtn.classList.add("hidden");
  closeThread({ pushHistory: false });
  closeSearch();

  const ch = state.channels[channelId];
  const icon = typeIcon(ch?.type);
  el.channelTitle.textContent = `${icon} ${ch?.name || channelId}`;
  el.channelMeta.textContent = "";

  if (pushHistory) pushNavState(channelId);
  loadMessages(channelId, 1);
}

function typeIcon(type) {
  return { public: "#", private: "🔒", group_dm: "💬", dm: "👤" }[type] || "#";
}

// ── Messages ──────────────────────────────────────────────────────────────────
async function loadMessages(channelId, page) {
  if (state.isLoadingMessages) return;
  state.isLoadingMessages = true;

  try {
    const url = `/api/channels/${encodeURIComponent(channelId)}/messages?page=${page}&per_page=${state.perPage}`;
    const data = await fetch(url).then((r) => r.json());

    state.totalPages = data.total_pages;
    state.currentPage = page;
    el.channelMeta.textContent = `${data.total.toLocaleString()}개 메시지`;

    if (page === 1) {
      el.msgsList.innerHTML = "";
    }

    if (data.messages.length === 0 && page === 1) {
      el.msgsList.innerHTML = '<div class="loading">메시지가 없습니다.</div>';
    } else {
      prependMessages(data.messages);
    }

    // Show load-more when older pages exist (page 2, 3, ...)
    el.loadMoreBtn.classList.toggle("hidden", data.total_pages <= 1);

    // On first load, scroll to bottom
    if (page === 1) {
      const wrap = el.msgsList.parentElement;
      wrap.scrollTop = wrap.scrollHeight;
    }

  } catch (e) {
    console.error("loadMessages error:", e);
  } finally {
    state.isLoadingMessages = false;
  }
}

function prependMessages(messages) {
  const frag = document.createDocumentFragment();
  let lastDate = null;

  for (const msg of messages) {
    const dateStr = msg.timestamp_str ? msg.timestamp_str.slice(0, 10) : "";
    if (dateStr && dateStr !== lastDate) {
      frag.appendChild(makeDateDivider(dateStr));
      lastDate = dateStr;
    }
    frag.appendChild(makeMessageRow(msg));
  }

  el.msgsList.appendChild(frag);
}

function makeDateDivider(dateStr) {
  const div = document.createElement("div");
  div.className = "date-divider";
  div.innerHTML = `<span>${escapeHtml(dateStr)}</span>`;
  return div;
}

function makeMessageRow(msg, compact = false) {
  const row = document.createElement("div");
  row.className = "msg-row";
  if (compact) row.classList.add("thread-reply");

  const name = resolveUserName(msg.user_id, msg.user_name);
  const initial = name ? name[0].toUpperCase() : "?";
  const time = msg.timestamp_str ? msg.timestamp_str.slice(11) : "";

  // thread_broadcast: is_broadcast=1 (스레드 중간에서 채널로 게시된 메시지)
  const isBroadcast = !compact && !!msg.is_broadcast;
  const rootPreview = isBroadcast && msg.thread_root_preview;

  // 원본 스레드 첫 메시지 미리보기 바 (위) — 클릭 시 스레드 열기
  const rootPreviewHtml = rootPreview
    ? `<div class="broadcast-root-preview" data-thread-ts="${escapeAttr(msg.thread_ts)}">
         <span class="broadcast-root-icon">↩</span>
         <span class="broadcast-root-author">${escapeHtml(rootPreview.user_name)}</span>
         <span class="broadcast-root-sep">:</span>
         <span class="broadcast-root-text">${escapeHtml(rootPreview.text || "")}</span>
       </div>`
    : "";

  // 답글 뱃지
  // - 스레드 루트 메시지: "답글 N개 보기" → 스레드 열기 (처음부터)
  // - thread_broadcast: "최근 댓글 보기" → 스레드 열기 + 해당 메시지 위치로 스크롤
  const isRoot = !compact && !isBroadcast && msg.thread_ts && msg.ts === msg.thread_ts;
  const replyCount = isBroadcast
    ? (rootPreview?.reply_count ?? msg.reply_count)
    : (msg.reply_count || 0);
  const threadTs = msg.thread_ts || msg.ts;

  let threadBadge = "";
  if (!compact) {
    if (isBroadcast) {
      // 채널에 업데이트된 메시지 → 최근 댓글 보기 (자신의 위치부터 스크롤)
      threadBadge = `<div class="thread-badge broadcast-thread-badge"
          data-thread-ts="${escapeAttr(threadTs)}"
          data-scroll-to-ts="${escapeAttr(msg.ts)}">
          💬 최근 댓글 보기
        </div>`;
    } else if (replyCount > 0) {
      // 일반 스레드 루트 → 답글 N개 보기
      threadBadge = `<div class="thread-badge"
          data-thread-ts="${escapeAttr(threadTs)}">
          💬 답글 ${replyCount}개 보기
        </div>`;
    }
  }

  const reactionsHtml = renderReactions(msg.reactions);
  const filesHtml = renderFiles(msg.files);

  row.innerHTML = `
    <div class="msg-avatar">${escapeHtml(initial)}</div>
    <div class="msg-body">
      ${rootPreviewHtml}
      <div class="msg-meta">
        <span class="msg-author">${escapeHtml(name)}</span>
        <span class="msg-time">${escapeHtml(time)}</span>
        ${isBroadcast ? '<span class="broadcast-label">채널에 업데이트됨</span>' : ""}
      </div>
      <div class="msg-text">${renderSlackMarkup(msg.text || "")}</div>
      ${reactionsHtml}
      ${filesHtml}
      ${threadBadge}
    </div>
  `;

  // 원본 미리보기 클릭 → 스레드 열기 (처음부터)
  const preview = row.querySelector(".broadcast-root-preview");
  if (preview) {
    preview.addEventListener("click", (e) => {
      e.stopPropagation();
      openThread(preview.dataset.threadTs, null);
    });
  }

  // 답글/댓글 뱃지 클릭
  const badge = row.querySelector(".thread-badge");
  if (badge) {
    badge.addEventListener("click", (e) => {
      e.stopPropagation();
      const scrollTo = badge.dataset.scrollToTs || null;
      openThread(badge.dataset.threadTs, scrollTo);
    });
  }

  return row;
}

// ── Load more (older messages) ────────────────────────────────────────────────
el.loadMoreBtn.addEventListener("click", () => {
  if (!state.activeChannelId) return;
  const nextPage = state.currentPage + 1;  // page 1=newest, page 2=older, ...
  if (nextPage > state.totalPages) return;
  loadOlderMessages(state.activeChannelId, nextPage);
});

async function loadOlderMessages(channelId, page) {
  if (state.isLoadingMessages) return;
  state.isLoadingMessages = true;

  const wrap = el.msgsList.parentElement;
  const oldScrollHeight = wrap.scrollHeight;

  try {
    const url = `/api/channels/${encodeURIComponent(channelId)}/messages?page=${page}&per_page=${state.perPage}`;
    const data = await fetch(url).then((r) => r.json());
    state.currentPage = page;

    const frag = document.createDocumentFragment();
    let lastDate = null;
    for (const msg of data.messages) {
      const dateStr = msg.timestamp_str ? msg.timestamp_str.slice(0, 10) : "";
      if (dateStr && dateStr !== lastDate) {
        frag.appendChild(makeDateDivider(dateStr));
        lastDate = dateStr;
      }
      frag.appendChild(makeMessageRow(msg));
    }

    // Insert before existing messages
    el.msgsList.insertBefore(frag, el.msgsList.firstChild);

    // Restore scroll position
    wrap.scrollTop = wrap.scrollHeight - oldScrollHeight;

    if (page >= state.totalPages) el.loadMoreBtn.classList.add("hidden");

  } catch (e) {
    console.error("loadOlderMessages error:", e);
  } finally {
    state.isLoadingMessages = false;
  }
}

// ── Thread Panel ──────────────────────────────────────────────────────────────
// scrollToTs: 스레드 내에서 이 ts를 가진 메시지로 스크롤 (최근 댓글 보기 용도)
async function openThread(threadTs, scrollToTs = null, { pushHistory = true } = {}) {
  if (pushHistory) pushNavState(state.activeChannelId, threadTs, scrollToTs);
  el.threadPanel.classList.remove("hidden");
  el.threadMessages.innerHTML = '<div class="loading">로딩 중...</div>';

  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadTs)}`);
    const data = await res.json();
    el.threadMessages.innerHTML = "";

    if (!res.ok) {
      el.threadMessages.innerHTML = '<div class="loading">스레드를 찾을 수 없습니다.</div>';
      return;
    }

    if (!data.messages || data.messages.length === 0) {
      el.threadMessages.innerHTML = '<div class="loading">메시지가 없습니다.</div>';
      return;
    }

    // 채널 헤더
    const channelId = data.messages[0]?.channel_id;
    const ch = channelId ? state.channels[channelId] : null;
    if (ch) {
      const header = document.createElement("div");
      header.className = "thread-ch-header";
      header.innerHTML =
        `<span class="thread-ch-label">채널</span>` +
        `<button class="thread-ch-btn" data-channel-id="${escapeAttr(ch.id)}">` +
        `${typeIcon(ch.type)} ${escapeHtml(ch.name)}</button>`;
      el.threadMessages.appendChild(header);
    }

    const [root, ...replies] = data.messages;

    // 루트 메시지
    const rootRow = makeMessageRow(root, false);
    rootRow.classList.add("thread-root");
    rootRow.dataset.ts = root.ts;
    el.threadMessages.appendChild(rootRow);

    if (replies.length > 0) {
      const label = document.createElement("div");
      label.className = "thread-replies-label";
      label.textContent = `답글 ${replies.length}개`;
      el.threadMessages.appendChild(label);

      for (const msg of replies) {
        const msgRow = makeMessageRow(msg, true);
        msgRow.dataset.ts = msg.ts;

        // 스레드 내 broadcast 메시지 → 노란 배경 하이라이트
        if (msg.is_broadcast) {
          msgRow.classList.add("thread-broadcast-highlight");
        }

        el.threadMessages.appendChild(msgRow);
      }
    }

    // scrollToTs가 지정된 경우: 해당 메시지 다음 위치로 스크롤
    if (scrollToTs) {
      requestAnimationFrame(() => {
        const target = el.threadMessages.querySelector(`[data-ts="${scrollToTs}"]`);
        if (target) {
          // 해당 메시지 다음 형제(첫 번째 후속 댓글)가 있으면 거기로, 없으면 자신으로
          const nextEl = target.nextElementSibling;
          const scrollTarget = nextEl || target;
          scrollTarget.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    }
  } catch (e) {
    el.threadMessages.innerHTML = `<div class="loading">오류: ${e.message}</div>`;
  }
}

function closeThread({ pushHistory = true } = {}) {
  el.threadPanel.classList.add("hidden");
  el.threadMessages.innerHTML = "";
  if (pushHistory && state.activeChannelId) pushNavState(state.activeChannelId);
}

el.threadCloseBtn.addEventListener("click", () => closeThread());

// ── Search ────────────────────────────────────────────────────────────────────

// 현재 검색 파라미터 상태
const searchState = {
  parsed: null,   // parseSearchQuery 결과
  page: 1,
  totalPages: 1,
  sort: "newest", // "newest" | "oldest" | "relevant"
};

// 검색 쿼리 파싱: in:#ch, from:@user, after:YYYY-MM-DD, before:YYYY-MM-DD, during:YYYY[-MM[-DD]]
function parseSearchQuery(input) {
  const result = { text: [], channels: [], users: [], after: null, before: null };
  const tokens = (input.match(/(?:"[^"]*"|\S+)/g) || []);
  for (const tok of tokens) {
    let m;
    if ((m = tok.match(/^in:#?(.+)/i)))       result.channels.push(m[1]);
    else if ((m = tok.match(/^from:@?(.+)/i))) result.users.push(m[1]);
    else if ((m = tok.match(/^after:(\S+)/i))) result.after = m[1];
    else if ((m = tok.match(/^before:(\S+)/i))) result.before = m[1];
    else if ((m = tok.match(/^during:(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?/i))) {
      const [, y, mo, d] = m;
      if (d)       { result.after = `${y}-${mo}-${d}`;  result.before = `${y}-${mo}-${d}`; }
      else if (mo) {
        const last = new Date(+y, +mo, 0).getDate();
        result.after  = `${y}-${mo}-01`;
        result.before = `${y}-${mo}-${String(last).padStart(2,"0")}`;
      } else       { result.after = `${y}-01-01`; result.before = `${y}-12-31`; }
    }
    else result.text.push(tok);
  }
  return result;
}

function buildSearchURL(parsed, page) {
  const p = new URLSearchParams();
  if (parsed.text.length)     p.set("q", parsed.text.join(" "));
  if (parsed.channels.length) {
    // Resolve channel name → ID using already-loaded state.channels (avoids server-side lookup errors)
    const chNameLower = parsed.channels[0].toLowerCase();
    const chEntry = Object.values(state.channels).find(
      (ch) => ch.name.toLowerCase() === chNameLower
    );
    if (chEntry) {
      p.set("channel_id", chEntry.id);   // direct ID — no server-side name lookup needed
    } else {
      p.set("channel_name", parsed.channels[0]);  // fallback: name lookup on server
    }
  }
  if (parsed.users.length)    p.set("from_user", parsed.users[0]);
  if (parsed.after)           p.set("after", parsed.after);
  if (parsed.before)          p.set("before", parsed.before);
  p.set("sort", searchState.sort);
  p.set("page", page);
  p.set("per_page", "30");
  return `/api/search?${p}`;
}

function hasSearchCriteria(parsed) {
  return parsed.text.length > 0 || parsed.channels.length > 0 ||
         parsed.users.length > 0 || parsed.after || parsed.before;
}

// ── Autocomplete ──────────────────────────────────────────────────────────────
let acTimer = null;
const acDropdown = document.createElement("div");
acDropdown.id = "ac-dropdown";
acDropdown.className = "hidden";
el.searchInput.parentElement.appendChild(acDropdown);

function getLastToken(value) {
  return (value.match(/\S+$/) || [""])[0];
}

function closeAutocomplete() {
  acDropdown.classList.add("hidden");
  acDropdown.innerHTML = "";
}

async function updateAutocomplete(inputValue) {
  const lastTok = getLastToken(inputValue);
  let type = null, query = "";

  const mCh   = lastTok.match(/^in:#?(.*)$/i);
  const mUs   = lastTok.match(/^from:@?(.*)$/i);
  const mHash = !mCh && !mUs && lastTok.match(/^#(.+)$/);   // bare #xxx → channel
  const mAt   = !mCh && !mUs && !mHash && lastTok.match(/^@(.+)$/); // bare @xxx → user

  if (mCh)        { type = "channel"; query = mCh[1]; }
  else if (mUs)   { type = "user";    query = mUs[1]; }
  else if (mHash) { type = "channel"; query = mHash[1]; }
  else if (mAt)   { type = "user";    query = mAt[1]; }

  if (!type) { closeAutocomplete(); return; }

  const endpoint = type === "channel"
    ? `/api/suggest/channels?q=${encodeURIComponent(query)}`
    : `/api/suggest/users?q=${encodeURIComponent(query)}`;

  const items = await fetch(endpoint).then((r) => r.json()).catch(() => []);
  if (!items.length) { closeAutocomplete(); return; }

  acDropdown.innerHTML = "";
  acDropdown.classList.remove("hidden");

  for (const item of items) {
    const div = document.createElement("div");
    div.className = "ac-item";
    if (type === "channel") {
      div.innerHTML = `<span class="ac-icon">${typeIcon(item.type)}</span> <span class="ac-label">${escapeHtml(item.name)}</span>`;
      div.addEventListener("mousedown", (e) => {
        e.preventDefault();
        // 마지막 토큰을 완성된 modifier로 교체
        const base = el.searchInput.value.replace(/\S+$/, "");
        el.searchInput.value = `${base}in:#${item.name} `;
        closeAutocomplete();
        el.searchInput.focus();
        renderFilterChips(parseSearchQuery(el.searchInput.value));
        triggerSearch();
      });
    } else {
      const display = item.display_name || item.real_name || item.name;
      div.innerHTML = `<span class="ac-icon">👤</span> <span class="ac-label">${escapeHtml(display)}</span> <span class="ac-sub">${escapeHtml(item.name)}</span>`;
      div.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const base = el.searchInput.value.replace(/\S+$/, "");
        el.searchInput.value = `${base}from:@${item.name} `;
        closeAutocomplete();
        el.searchInput.focus();
        renderFilterChips(parseSearchQuery(el.searchInput.value));
        triggerSearch();
      });
    }
    acDropdown.appendChild(div);
  }
}

// ── Filter chips ──────────────────────────────────────────────────────────────
const filterChipsEl = document.createElement("div");
filterChipsEl.id = "filter-chips";
el.searchInput.parentElement.appendChild(filterChipsEl);

function renderFilterChips(parsed) {
  filterChipsEl.innerHTML = "";
  const chips = [];
  parsed.channels.forEach(c => chips.push({ label: `in:#${c}`, remove: () => removeToken(`in:#${c}`, `in:${c}`) }));
  parsed.users.forEach(u  => chips.push({ label: `from:@${u}`, remove: () => removeToken(`from:@${u}`, `from:${u}`) }));
  if (parsed.after)  chips.push({ label: `after:${parsed.after}`,   remove: () => removeToken(`after:${parsed.after}`) });
  if (parsed.before) chips.push({ label: `before:${parsed.before}`, remove: () => removeToken(`before:${parsed.before}`) });

  for (const chip of chips) {
    const span = document.createElement("span");
    span.className = "filter-chip";
    span.innerHTML = `${escapeHtml(chip.label)} <button class="chip-remove" title="제거">✕</button>`;
    span.querySelector(".chip-remove").addEventListener("click", () => {
      chip.remove();
      triggerSearch();
    });
    filterChipsEl.appendChild(span);
  }
}

function removeToken(...patterns) {
  let val = el.searchInput.value;
  for (const p of patterns) val = val.replace(new RegExp(`\\s*${p.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}\\S*`, "gi"), "");
  el.searchInput.value = val.trim();
  renderFilterChips(parseSearchQuery(el.searchInput.value));
}

// ── Search trigger ────────────────────────────────────────────────────────────
let searchTimer = null;

function triggerSearch() {
  clearTimeout(searchTimer);
  const val = el.searchInput.value;
  const parsed = parseSearchQuery(val);
  renderFilterChips(parsed);
  if (!hasSearchCriteria(parsed)) { closeSearch(); return; }
  searchTimer = setTimeout(() => doSearch(parsed, 1), 350);
}

el.searchInput.addEventListener("input", () => {
  clearTimeout(acTimer);
  acTimer = setTimeout(() => updateAutocomplete(el.searchInput.value), 150);
  triggerSearch();
});

el.searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!acDropdown.classList.contains("hidden")) { closeAutocomplete(); }
    else { closeSearch(); el.searchInput.blur(); }
  }
});

el.searchInput.addEventListener("blur", () => {
  setTimeout(closeAutocomplete, 150);
});

// ── doSearch ──────────────────────────────────────────────────────────────────
async function doSearch(parsed, page) {
  searchState.parsed = parsed;
  searchState.page = page;

  el.searchOverlay.classList.remove("hidden");
  el.searchResultsList.innerHTML = '<div class="loading">검색 중...</div>';
  el.searchResultsTitle.textContent = "검색 중...";
  el.searchPagination.innerHTML = "";

  try {
    const data = await fetch(buildSearchURL(parsed, page)).then((r) => r.json());
    searchState.totalPages = data.total_pages;

    // 제목 요약
    const parts = [];
    if (parsed.text.length) parts.push(`"${parsed.text.join(" ")}"`);
    if (parsed.channels.length) parts.push(`in:#${parsed.channels[0]}`);
    if (parsed.users.length) parts.push(`from:@${parsed.users[0]}`);
    if (parsed.after)  parts.push(`after:${parsed.after}`);
    if (parsed.before) parts.push(`before:${parsed.before}`);
    el.searchResultsTitle.textContent = `${parts.join("  ")} — ${data.total.toLocaleString()}개`;

    el.searchResultsList.innerHTML = "";
    if (!data.messages.length) {
      el.searchResultsList.innerHTML = '<div class="loading">결과가 없습니다.</div>';
      return;
    }

    for (const msg of data.messages) {
      el.searchResultsList.appendChild(makeSearchResultRow(msg));
    }
    renderSearchPagination(data);
  } catch (e) {
    el.searchResultsList.innerHTML = `<div class="loading">오류: ${e.message}</div>`;
  }
}

function makeSearchResultRow(msg) {
  const wrap = document.createElement("div");
  wrap.className = "search-result-row";

  const ch = state.channels[msg.channel_id] || { name: msg.channel_name || msg.channel_id, type: msg.channel_type || "public" };
  const chIcon = typeIcon(ch.type);
  const name = resolveUserName(msg.user_id, msg.user_name);
  const initial = name ? name[0].toUpperCase() : "?";
  const dateStr = msg.timestamp_str || "";

  wrap.innerHTML = `
    <div class="sr-channel-bar">
      <span class="sr-channel-chip">${chIcon} ${escapeHtml(ch.name)}</span>
      <span class="sr-date">${escapeHtml(dateStr)}</span>
    </div>
    <div class="sr-body">
      <div class="msg-avatar">${escapeHtml(initial)}</div>
      <div class="sr-content">
        <span class="msg-author">${escapeHtml(name)}</span>
        <div class="msg-text">${renderSlackMarkup(msg.text || "")}</div>
      </div>
    </div>
  `;
  wrap.addEventListener("click", () => {
    const savedQuery = el.searchInput.value;  // 닫기 전에 쿼리 저장

    // 검색 상태를 navHistory에 먼저 push → 뒤로 가기 시 검색 화면 복원
    if (savedQuery) pushNavState(state.activeChannelId, null, null, savedQuery);

    closeSearch();
    el.searchInput.value = "";
    filterChipsEl.innerHTML = "";
    const threadTs = msg.thread_ts || msg.ts;
    if (msg.channel_id && msg.channel_id !== state.activeChannelId) {
      selectChannel(msg.channel_id, { pushHistory: false });
    }
    openThread(threadTs, msg.ts);
  });
  return wrap;
}

function renderSearchPagination(data) {
  el.searchPagination.innerHTML = "";
  if (data.total_pages <= 1) return;

  const prev = document.createElement("button");
  prev.textContent = "← 이전";
  prev.disabled = data.page <= 1;
  prev.addEventListener("click", () => doSearch(searchState.parsed, data.page - 1));

  const info = document.createElement("span");
  info.className = "page-info";
  info.textContent = `${data.page} / ${data.total_pages}`;

  const next = document.createElement("button");
  next.textContent = "다음 →";
  next.disabled = data.page >= data.total_pages;
  next.addEventListener("click", () => doSearch(searchState.parsed, data.page + 1));

  el.searchPagination.append(prev, info, next);
}

function closeSearch() {
  el.searchOverlay.classList.add("hidden");
  el.searchResultsList.innerHTML = "";
  el.searchPagination.innerHTML = "";
  closeAutocomplete();
}

el.searchCloseBtn.addEventListener("click", () => {
  closeSearch();
  el.searchInput.value = "";
  filterChipsEl.innerHTML = "";
});

// ── Slack Markup Renderer ─────────────────────────────────────────────────────
function renderSlackMarkup(text) {
  if (!text) return "";

  // Escape HTML first
  let s = escapeHtml(text);

  // Code blocks (```...```) — must come before inline code
  s = s.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code}</code></pre>`);

  // Inline code
  s = s.replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`);

  // Blockquote lines
  s = s.replace(/(^|\n)&gt; ?([^\n]*)/g, (_, pre, content) => `${pre}<blockquote>${content}</blockquote>`);

  // Bold *text*
  s = s.replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>");

  // Italic _text_
  s = s.replace(/_([^_\n]+)_/g, "<em>$1</em>");

  // Strikethrough ~text~
  s = s.replace(/~([^~\n]+)~/g, "<s>$1</s>");

  // Slack user mentions <@UXXXXXXX> or <@UXXXXXXX|name>
  s = s.replace(/&lt;@([A-Z0-9]+)(?:\|([^&gt;]+))?&gt;/g, (_, uid, name) => {
    const resolved = name || resolveUserName(uid, uid);
    return `<strong>@${escapeHtml(resolved)}</strong>`;
  });

  // Slack channel mentions <#CXXXXXXX|name>
  s = s.replace(/&lt;#([A-Z0-9]+)(?:\|([^&gt;]+))?&gt;/g, (_, cid, name) => {
    const n = name || cid;
    return `<strong>#${escapeHtml(n)}</strong>`;
  });

  // URLs <https://example.com|label> or <https://example.com>
  // After escapeHtml, & becomes &amp; — use negative lookahead to stop at &gt; or |
  s = s.replace(
    /&lt;(https?:\/\/(?:(?!&gt;|\|).)*?)(?:\|((?:(?!&gt;).)*?))?&gt;/g,
    (_, rawUrl, label) => {
      // Unescape HTML entities in the href so the actual URL works
      const href = rawUrl
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"');
      // label and rawUrl are already HTML-escaped (safe for innerHTML)
      const display = label || rawUrl;

      // Slack archive message link → local navigation
      const archiveMatch = href.match(
        /https?:\/\/[a-zA-Z0-9\-]+\.slack\.com\/archives\/(C[A-Z0-9]+)\/p(\d{10})(\d{6})/
      );
      if (archiveMatch) {
        const [, cid, sec, usec] = archiveMatch;
        const msgTs = `${sec}.${usec}`;
        const threadTsParam = href.match(/[?&]thread_?ts=([\d.]+)/);
        const threadTs = threadTsParam ? threadTsParam[1] : msgTs;
        if (state.channels[cid]) {
          return `<a href="#" class="local-msg-link"` +
            ` data-channel-id="${escapeAttr(cid)}"` +
            ` data-thread-ts="${escapeAttr(threadTs)}"` +
            ` data-scroll-ts="${escapeAttr(msgTs)}"` +
            ` title="아카이브에서 보기 (Ctrl+클릭: 새 탭)">${display}</a>`;
        }
      }

      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${display}</a>`;
    }
  );

  // Newlines to <br>
  s = s.replace(/\n/g, "<br />");

  return s;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function resolveUserName(userId, fallback) {
  if (userId && state.users[userId]) {
    const u = state.users[userId];
    return u.display_name || u.real_name || u.name || userId;
  }
  return fallback || userId || "unknown";
}

function renderReactions(reactions) {
  if (!reactions || reactions.length === 0) return "";
  const badges = reactions
    .map((r) => `<span class="reaction-badge">:${escapeHtml(r.name)}: ${r.count}</span>`)
    .join("");
  return `<div class="msg-reactions">${badges}</div>`;
}

function renderFiles(files) {
  if (!files || files.length === 0) return "";
  const chips = files
    .map((f) => `<span class="file-chip">📎 ${escapeHtml(f.name || "파일")}</span>`)
    .join("");
  return `<div class="msg-files">${chips}</div>`;
}

function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(str) {
  return String(str || "").replace(/"/g, "&quot;");
}

// ── History / Navigation ──────────────────────────────────────────────────────
function parseNavHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  return {
    channelId:   params.get("channel") || null,
    threadTs:    params.get("thread")  || null,
    scrollTs:    params.get("scroll")  || null,
    searchQuery: params.get("search")  || null,
  };
}

function pushNavState(channelId, threadTs = null, scrollTs = null, searchQuery = null) {
  // 현재 위치 이후의 앞으로 항목 제거 (새 경로로 분기)
  navHistory.splice(navHistoryIdx + 1);
  navHistory.push({ channelId, threadTs, scrollTs, searchQuery });
  navHistoryIdx = navHistory.length - 1;

  const params = new URLSearchParams();
  if (channelId)   params.set("channel", channelId);
  if (threadTs)    params.set("thread",  threadTs);
  if (scrollTs)    params.set("scroll",  scrollTs);
  if (searchQuery) params.set("search",  searchQuery);
  history.pushState(
    { channelId, threadTs, scrollTs, searchQuery, _nidx: navHistoryIdx },
    "",
    "#" + params.toString()
  );
  updateNavButtons();
}

function updateNavButtons() {
  el.navBackBtn.disabled = navHistoryIdx <= 0;
  el.navFwdBtn.disabled  = navHistoryIdx >= navHistory.length - 1;
}

function restoreNavState(navState) {
  const { channelId, threadTs, scrollTs, searchQuery } = navState || parseNavHash();

  // 검색 상태 복원: 오버레이를 다시 열고 검색 재실행
  if (searchQuery) {
    el.searchInput.value = searchQuery;
    const parsed = parseSearchQuery(searchQuery);
    renderFilterChips(parsed);
    if (hasSearchCriteria(parsed)) doSearch(parsed, 1);
    closeThread({ pushHistory: false });
    return;
  }

  if (!channelId || !state.channels[channelId]) return;
  if (channelId !== state.activeChannelId) {
    selectChannel(channelId, { pushHistory: false });
  } else if (!threadTs) {
    closeThread({ pushHistory: false });
  }
  if (threadTs) {
    openThread(threadTs, scrollTs || null, { pushHistory: false });
  }
}

window.addEventListener("popstate", (e) => {
  const st = e.state;
  if (st && typeof st._nidx === "number") navHistoryIdx = st._nidx;
  restoreNavState(st?.channelId ? st : parseNavHash());
  updateNavButtons();
});

// ── Sort buttons ──────────────────────────────────────────────────────────────
document.querySelectorAll(".sort-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    searchState.sort = btn.dataset.sort;
    document.querySelectorAll(".sort-btn").forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
    if (searchState.parsed) doSearch(searchState.parsed, 1);
  });
});

// ── Nav button handlers ───────────────────────────────────────────────────────
el.navBackBtn.addEventListener("click", () => {
  if (navHistoryIdx > 0) history.back();
});
el.navFwdBtn.addEventListener("click", () => {
  if (navHistoryIdx < navHistory.length - 1) history.forward();
});

// Alt+← = 뒤로, Alt+→ = 앞으로
document.addEventListener("keydown", (e) => {
  if (e.altKey && e.key === "ArrowLeft"  && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    if (navHistoryIdx > 0) history.back();
  }
  if (e.altKey && e.key === "ArrowRight" && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    if (navHistoryIdx < navHistory.length - 1) history.forward();
  }
});

// ── Local Slack archive link handler ─────────────────────────────────────────
document.addEventListener("click", (e) => {
  const link = e.target.closest(".local-msg-link");
  if (!link) return;
  e.preventDefault();
  const threadTs = link.dataset.threadTs;
  const scrollTs = link.dataset.scrollTs;
  if (!threadTs) return;

  // Ctrl/Cmd+클릭 → 현재 URL에 해시 파라미터를 붙여 새 탭으로 열기
  if (e.ctrlKey || e.metaKey) {
    const params = new URLSearchParams();
    if (link.dataset.channelId) params.set("channel", link.dataset.channelId);
    if (threadTs)  params.set("thread", threadTs);
    if (scrollTs)  params.set("scroll", scrollTs);
    window.open(location.pathname + "#" + params.toString(), "_blank");
    return;
  }

  closeSearch();
  openThread(threadTs, scrollTs || threadTs);
});

// ── Thread panel channel header button ────────────────────────────────────────
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".thread-ch-btn");
  if (!btn) return;
  selectChannel(btn.dataset.channelId);
});

// ── Thread panel resize ───────────────────────────────────────────────────────
(function () {
  const handle = document.getElementById("thread-resize-handle");
  const panel  = document.getElementById("thread-panel");

  // 저장된 너비 복원
  const saved = localStorage.getItem("threadPanelWidth");
  if (saved) panel.style.width = saved + "px";

  let startX, startWidth;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    startX     = e.clientX;
    startWidth = panel.offsetWidth;
    handle.classList.add("dragging");
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
  });

  function onMove(e) {
    // 핸들이 왼쪽 경계 → 왼쪽으로 드래그할수록 너비 증가
    const newWidth = Math.max(280, Math.min(700, startWidth + (startX - e.clientX)));
    panel.style.width = newWidth + "px";
  }

  function onUp() {
    handle.classList.remove("dragging");
    localStorage.setItem("threadPanelWidth", panel.offsetWidth);
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup",   onUp);
  }
})();

// ── Start ─────────────────────────────────────────────────────────────────────
init();
