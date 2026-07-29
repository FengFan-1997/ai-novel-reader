(() => {
  const list = document.querySelector('#library-list');
  const summary = document.querySelector('#library-summary');
  const search = document.querySelector('#library-search');
  const dialog = document.querySelector('#work-dialog');
  const detail = document.querySelector('#work-detail');
  const player = document.querySelector('#player');
  const audio = document.querySelector('#audio');
  const title = document.querySelector('#player-title');
  const subtitle = document.querySelector('#player-subtitle');
  let activeArtifact = null;

  const sourceLabel = (book) => book.cachedChapters ? ['cached', '云端可听'] : book.availableChapters ? ['peer', '社区节点'] : ['wait', '等待上线'];
  const escape = (value) => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;' }[char]));
  const playIcon = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m8 5 11 7-11 7V5Z"/></svg>';
  async function json(url, options) { const response = await fetch(url, options); const body = await response.json().catch(() => ({})); if (!response.ok || body.success === false) throw new Error(body.error || `请求失败（${response.status}）`); return body; }
  function renderBooks(items) {
    list.setAttribute('aria-busy', 'false');
    if (!items.length) { list.innerHTML = '<div class="empty">这里还没有可公开播放的故事。<br>第一位贡献者完成生成后会自动出现在这里。</div>'; summary.textContent = '暂无作品'; return; }
    summary.textContent = `已发现 ${items.length} 部可听作品`;
    list.innerHTML = items.map(book => { const [kind, label] = sourceLabel(book); return `<button class="book-row" type="button" data-work="${escape(book.id)}"><span class="book-index"><span class="cover-letter">${escape(book.title.slice(0,1))}</span><span><h3>${escape(book.title)}</h3><p>${escape(book.author || '社区生成')} · ${book.availableChapters}/${book.chapterCount} 章可听</p></span></span><span class="book-stat">${Number(book.heat || 0).toLocaleString()} 次播放</span><span class="book-source"><b class="source-dot ${kind}"></b>${label}</span><span class="book-open">${playIcon}</span></button>`; }).join('');
    list.querySelectorAll('[data-work]').forEach(button => button.addEventListener('click', () => openWork(button.dataset.work)));
  }
  async function loadBooks(query = '') {
    list.setAttribute('aria-busy', 'true'); list.innerHTML = '<div class="loading">正在读取公共书库…</div>'; summary.textContent = '正在同步目录';
    try { const data = await json(`/v1/library?limit=30&q=${encodeURIComponent(query)}`); renderBooks(data.items || []); }
    catch (error) { list.setAttribute('aria-busy', 'false'); list.innerHTML = `<div class="error">${escape(error.message)}<br><button type="button" id="retry">重新连接</button></div>`; document.querySelector('#retry')?.addEventListener('click', () => loadBooks(query)); summary.textContent = '暂时无法连接'; }
  }
  function chapterLabel(chapter) { return chapter.availability === 'cached' ? '云端播放' : chapter.availability === 'peer' ? `${chapter.peerCount || 1} 个节点` : '等待节点'; }
  async function openWork(workId) {
    detail.innerHTML = '<div class="loading">正在读取章节…</div>'; dialog.showModal();
    try {
      const data = await json(`/v1/works/${encodeURIComponent(workId)}`); const work = data.work; const edition = work.editions[0];
      detail.innerHTML = `<div class="work-detail"><p class="eyebrow">公共有声书</p><h2 id="work-title">${escape(work.title)}</h2><p class="work-meta">${escape(work.author || '社区生成')} · ${edition.chapterCount} 章</p>${work.description ? `<p class="work-description">${escape(work.description)}</p>` : ''}<div class="chapter-list">${edition.chapters.map(chapter => `<div class="chapter-row"><span>${String(chapter.index + 1).padStart(2,'0')}</span><strong>${escape(chapter.title)}</strong><button class="chapter-play" type="button" data-artifact="${escape(chapter.artifactId || '')}" data-state="${escape(chapter.availability)}" ${chapter.artifactId ? '' : 'disabled'}>${chapterLabel(chapter)}</button></div>`).join('')}</div></div>`;
      detail.querySelectorAll('[data-artifact]').forEach(button => button.addEventListener('click', () => { if (button.dataset.artifact) playArtifact(button.dataset.artifact, work.title, button.closest('.chapter-row').querySelector('strong').textContent); }));
    } catch (error) { detail.innerHTML = `<div class="work-detail"><p class="error">${escape(error.message)}</p></div>`; }
  }
  async function playArtifact(artifactId, workTitle, chapterTitle) {
    try {
      const data = await json(`/v1/artifacts/${encodeURIComponent(artifactId)}/sources`);
      if (!data.audioUrl) { subtitle.textContent = data.peers?.length ? `发现 ${data.peers.length} 个社区节点；当前浏览器正在等待直连传输` : '暂时没有在线节点，贡献者上线后会自动可听'; player.hidden = false; title.textContent = `${workTitle} · ${chapterTitle}`; return; }
      activeArtifact = artifactId; title.textContent = `${workTitle} · ${chapterTitle}`; subtitle.textContent = '云端可听 · AI 合成有声内容'; audio.src = data.audioUrl; player.hidden = false; await audio.play();
    } catch (error) { subtitle.textContent = error.message; player.hidden = false; }
  }
  search.addEventListener('submit', event => { event.preventDefault(); loadBooks(document.querySelector('#library-query').value.trim()); });
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  document.querySelector('#close-player').addEventListener('click', () => { audio.pause(); audio.removeAttribute('src'); audio.load(); player.hidden = true; activeArtifact = null; });
  let lastReported = 0;
  audio.addEventListener('timeupdate', () => { if (activeArtifact && audio.currentTime - lastReported >= 30) { lastReported = audio.currentTime; fetch(`/v1/artifacts/${activeArtifact}/playback`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({secondsPlayed:30}) }).catch(() => {}); } });
  loadBooks();
})();
