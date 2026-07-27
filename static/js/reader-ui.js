(function () {
    'use strict';

    const TEXT_MAP = new Map(Object.entries({
        '🎭 TTS-Story': '声阅',
        'Multi-Voice Text-to-Speech for Stories and Audiobooks': 'AI 多角色小说阅读器 · 本地免费运行',
        'Generate': '阅读',
        'Job Queue': '制作进度',
        'Library': '我的有声书',
        'Available Voices': '声线',
        'Settings': '设置',
        'Help': '使用帮助',
        'Input Text': '小说正文',
        'Project': '作品',
        'Manage Projects': '管理作品',
        'Load Document': '导入小说',
        'Alt Word Registry': '读音纠正',
        'Use default prompt': '使用默认处理方式',
        'Prep Text': '智能分角色',
        'Pause': '暂停',
        'Resume': '继续',
        'Restart': '重新开始',
        'Abort': '取消',
        'Text Statistics': '小说分析',
        'Speakers': '角色',
        'Total Chunks': '片段',
        'Word Count': '字数',
        'Est. Duration': '预计时长',
        'Generate Voices': '批量创建声线',
        'Auto Assign': '智能配音',
        'Assign Voices': '角色声线',
        'Generation Options': '生成设置',
        'Engine': '朗读引擎',
        'Format': '音频格式',
        'MP3 Bitrate': 'MP3 音质',
        'Generate Audio': '生成并听',
        'Review detected sections': '查看章节',
        'Section headings to detect': '章节标题识别',
        'Add': '添加',
        'Latest Audio': '最新生成',
        'Job Details': '任务详情',
        'Close': '关闭',
        'Refresh': '刷新',
        'Clear Queue': '清空任务',
        'Audio Library': '我的有声书',
        'Refresh Library': '刷新',
        'Clear All': '全部清空',
        'Kokoro Voices': 'Kokoro 内置声线',
        'Custom Kokoro Voice Blends': '自定义混合声线',
        'New Custom Voice': '新建混合声线',
        'Voice Creation': '创建中文声线',
        'Voice Design Engine': '声线生成引擎',
        'Voice Name': '声线名称',
        'Gender': '性别',
        'Language': '语言',
        'Short Description': '声线简介',
        'Sample Text': '试听文本',
        'Voice Style Instruction': '音色与表演要求',
        'Generate Preview': '生成试听',
        'Save to Voice Prompts': '保存到声线库',
        'Voice Prompts': '我的声线样本',
        'Search voices...': '搜索声线…',
        'All Genders': '全部性别',
        'All Languages': '全部语言',
        'Load External Voices': '载入外部声线',
        'Export': '导出',
        'Archive': '归档',
        'Delete': '删除',
        'Unarchive': '恢复',
        'Archived Voices': '已归档声线',
        'Name': '名称',
        'Duration': '时长',
        'Source': '来源',
        'Actions': '操作',
        'Quick Settings': '常用设置',
        'Engine Settings': '高级引擎设置',
        'Audio Settings': '音频设置',
        'LLM Settings': '智能文本处理',
        'Save Settings': '保存设置',
        'Reset to Defaults': '恢复默认',
        'Male': '男声',
        'Female': '女声',
        'Auto': '自动',
        'Chinese': '中文',
        'Pitch': '音高',
        'Speed': '语速',
        'Quick Test': '试听',
        'Stop': '停止',
        'Play': '播放',
        'Cancel': '取消',
        'Apply': '应用',
        'Apply Assignments': '应用声线',
        'No assignment': '不分配',
        'Select Voice...': '选择声线…',
        'Language': '语言',
        'Custom Instruction (optional)': '情绪补充（可选）',
        'Natural': '自然',
        'Loading...': '加载中…',
        'Checking...': '检查中…',
        'Mode:': '当前模式：',
        'CUDA:': '显卡：',
        'Not Available': '不可用',
        'Available': '可用',
        'Edit Speaker': '编辑角色',
        'Profile:': '人物档案：',
        'Voice Type:': '声线类型：',
        'Generate Voice': '生成声线',
        'Mark as ready': '标记为已确认',
        'Advanced Settings': '高级设置',
        'Queue Size:': '等待制作：',
        'Current Job:': '当前任务：',
        'pending': '个等待中',
        'None': '无',
        'Status': '状态',
        'Job ID': '任务编号',
        'Progress': '进度',
        'Text Preview': '正文预览',
        'Created': '创建时间',
        'interrupted': '已中断',
        'Interrupted': '已中断',
        'completed': '已完成',
        'failed': '失败',
        'processing': '制作中',
        'queued': '等待中',
        'Estimating…': '正在估算…',
        'Calculating…': '正在计算…',
        'Single output file': '合并为一个音频',
        'Done': '完成',
        'N/A': '—',
        'Details': '查看',
        'Remove': '移除',
        'Download': '下载',
        'Generated Audio': '生成的有声书',
        'Alt Words': '读音纠正',
        'Metrics': '音频信息',
        'Time Codes': '时间轴',
        'Edit Metadata': '修改书名',
        'Rebuild': '重新合成',
        'Audio & Generation': '音频与生成',
        'LLM Pre-Processing': '智能分角色设置',
        'Explore all Kokoro voices. Click any voice to hear a preview sample.': '试听内置声线。',
        'Blend two Kokoro voices and manage your custom library.': '混合两条内置声线并保存。',
        'Manage prompt libraries for Chatterbox, VoxCPM, and Qwen3.': '管理已保存或导入的中文声线样本。',
        'All Sources': '全部来源',
        'Local Only': '仅本机',
        'External (GitHub)': '外部声线（GitHub）',
        'Audio File': '音频文件',
        'Save Voice': '保存声线',
        'Browse Files': '选择文件',
        'Bulk import via drag & drop': '批量拖入声线样本',
        'Drop multiple WAV/MP3 clips (5–10s). We\'ll keep any clips ≥5s and name them after the file.': '拖入多条 5～10 秒的 WAV/MP3 中文干声，文件名会作为声线名称。',
        'Select all voices': '全选声线',
        'Select all archived voices': '全选已归档声线',
        'No tags selected — select at least one above.': '还没有选择音色特征。',
        '— Not specified —': '— 不限 —',
        'TTS-Story pages': '声阅页面',
        'auto': '自动',
        'english': '英语',
        'chinese': '中文',
        'japanese': '日语',
        'korean': '韩语',
        'french': '法语',
        'german': '德语',
        'spanish': '西班牙语',
        'italian': '意大利语',
        'portuguese': '葡萄牙语',
        'russian': '俄语'
    }));

    const PLACEHOLDER_MAP = new Map(Object.entries({
        '[narrator]Once upon a time...[/narrator]\n[alice]Hello, I\'m Alice![/alice]\n[bob]And I\'m Bob![/bob]\n\nOr drag & drop documents here (Word, PDF, TXT, RTF, EPUB)':
            '把小说粘贴到这里，或点击“导入小说”。\n\n无需手动添加角色标签；点击“智能分角色”后，AI 会识别旁白和真正开口说话的人物。',
        'Add custom heading (e.g., Episode, Volume)': '添加自定义章节标题',
        'Search voices...': '搜索声线…',
        'e.g. Velvet Noir': '例如：清冷师尊',
        'Moody, intimate noir narrator': '例如：清冷、克制、亲密时会变柔',
        'Type a short script for the preview clip...': '输入一小段中文试听文本…',
        'e.g., Speak with controlled intensity and a smoky, cinematic tone.': '例如：语速自然，危险感来自克制，不拖长尾音。',
        'Preview text': '试听文本'
    }));

    const EMOTIONS = [
        ['', '自动判断'],
        ['情绪明亮兴奋，语速略快，有自然笑意。', '开心'],
        ['语气温柔亲近，音量略轻，保持自然语速。', '温柔'],
        ['保持原本声纹，只略微收声，用轻微犹豫和藏不住的笑意表现娇羞。', '娇羞'],
        ['语气清冷克制，重音干净，不故意拖慢。', '清冷'],
        ['威胁感来自从容确信，保持正常对话速度。', '危险'],
        ['呼吸和重音变强，节奏更紧，但不要持续吼叫。', '愤怒'],
        ['近距离压低声音，保持清晰吐字。', '低声']
    ];

    let presets = [];
    let lastTextValue = '';
    let roleRenderTimer = null;

    function translateValue(value) {
        const raw = String(value || '');
        const trimmed = raw.trim();
        if (!trimmed) return raw;
        let replacement = TEXT_MAP.get(trimmed);
        if (!replacement) {
            if (/^\d+ voices$/.test(trimmed)) replacement = trimmed.replace('voices', '条声线');
            else if (/^\d+ selected$/.test(trimmed)) replacement = trimmed.replace('selected', '条已选');
            else if (/^Loading\b/.test(trimmed)) replacement = trimmed.replace(/^Loading/, '正在加载');
            else if (/^No saved voices yet/.test(trimmed)) replacement = '还没有保存的声线。可以在上方创建一条。';
            else if (/^No archived voices/.test(trimmed)) replacement = '没有已归档的声线。';
            else if (/^No audio files/.test(trimmed)) replacement = '还没有生成有声书。先在“阅读”页生成一段吧。';
            else if (/^No detected speakers/.test(trimmed)) replacement = '还没有识别到角色。请先导入小说并点击“智能分角色”。';
            else if (/^Detected Speakers:/.test(trimmed)) replacement = trimmed.replace('Detected Speakers:', '识别到的角色：');
            else if (/^Click any speaker/.test(trimmed)) replacement = '点击角色可查看或修改声线。';
            else if (/^Sections not analyzed yet/.test(trimmed)) replacement = '导入小说后会自动识别章节。';
            else if (/^Most recently completed job/.test(trimmed)) replacement = '最近完成的音频。';
            else if (/^Monitor active/.test(trimmed)) replacement = '查看正在制作和等待中的有声书。';
            else if (/^Browse built-in/.test(trimmed)) replacement = '浏览、试听和创建中文角色声线。';
            else if (/^Configure defaults/.test(trimmed)) replacement = '常用选项在上方；模型与引擎参数默认折叠。';
            else if (/^Design a voice/.test(trimmed)) replacement = '选择角色人设，试听后保存到自己的声线库。';
            else if (/^Manage your generated/.test(trimmed)) replacement = '播放、下载或管理已经生成的有声书。';
            else if (/^Preparing LLM request/.test(trimmed)) replacement = '正在理解小说人物…';
            else if (/^Generating/.test(trimmed)) replacement = trimmed.replace(/^Generating/, '正在生成');
            else if (/^Saving/.test(trimmed)) replacement = trimmed.replace(/^Saving/, '正在保存');
            else if (/^Help:\s*/.test(trimmed)) {
                const helpName = trimmed.replace(/^Help:\s*/, '');
                replacement = `说明：${TEXT_MAP.get(helpName) || helpName}`;
            }
            else if (/^Toggle details$/.test(trimmed)) replacement = '展开详情';
            else if (/^(\d+) pending$/.test(trimmed)) replacement = trimmed.replace(/^(\d+) pending$/, '$1 个等待中');
            else if (/^Resume from chunk (\d+)/.test(trimmed)) replacement = trimmed.replace(/^Resume from chunk (\d+)/, '从第 $1 段继续');
            else if (/^Post-processing (\d+\s*\/\s*\d+)/.test(trimmed)) replacement = trimmed.replace(/^Post-processing/, '后期处理');
            else if (/^(\d+\s*\/\s*\d+) chunks$/.test(trimmed)) replacement = trimmed.replace(/chunks$/, '段');
            else if (/^Speaker\s*(\d+)$/i.test(trimmed)) replacement = trimmed.replace(/^Speaker\s*/i, '角色 ');
            else if (/^Default$/i.test(trimmed)) replacement = '默认';
            else if (/^Preparing\.\.\.$/.test(trimmed)) replacement = '正在准备…';
        }
        if (!replacement || replacement === trimmed) return raw;
        const start = raw.slice(0, raw.indexOf(trimmed));
        const end = raw.slice(raw.indexOf(trimmed) + trimmed.length);
        return start + replacement + end;
    }

    function localizeTree(root) {
        if (!root || root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(node => {
            if (node.parentElement?.closest('textarea, script, style')) return;
            const translated = translateValue(node.nodeValue);
            if (translated !== node.nodeValue) node.nodeValue = translated;
        });
        root.querySelectorAll?.('[placeholder], [title], [aria-label]').forEach(element => {
            ['placeholder', 'title', 'aria-label'].forEach(attribute => {
                const value = element.getAttribute(attribute);
                if (!value) return;
                const translated = PLACEHOLDER_MAP.get(value) || translateValue(value);
                if (translated !== value) element.setAttribute(attribute, translated);
            });
        });
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function buildAppNavigation() {
        const container = document.querySelector('body > .container');
        const legacyHeader = container?.querySelector(':scope > header');
        if (!container || !legacyHeader || document.getElementById('reader-appbar')) return;

        const appbar = createElement('nav', 'reader-appbar', '');
        appbar.id = 'reader-appbar';
        appbar.setAttribute('aria-label', '主导航');
        appbar.innerHTML = `
            <button type="button" class="reader-brand" data-reader-nav="generate" aria-label="声阅首页">
                <span class="reader-brand-mark" aria-hidden="true">声</span>
                <span class="reader-brand-copy"><strong>声阅</strong><small>AI 小说阅读器</small></span>
            </button>
            <div class="reader-appnav-primary" aria-label="主要页面">
                <button type="button" class="reader-appnav-link active" data-reader-nav="generate">阅读</button>
                <button type="button" class="reader-appnav-link" data-reader-nav="library">我的有声书</button>
            </div>
            <div class="reader-appnav-actions">
                <button type="button" class="reader-appnav-status" data-reader-nav="queue">
                    <span class="reader-status-dot" aria-hidden="true"></span><span>制作进度</span>
                </button>
                <button type="button" class="reader-more-button" id="reader-more-button"
                        aria-label="打开更多功能" aria-haspopup="menu" aria-expanded="false">•••</button>
                <div class="reader-more-menu" id="reader-more-menu" role="menu" hidden>
                    <p class="reader-menu-label">更多功能</p>
                    <button type="button" role="menuitem" data-reader-nav="voices">
                        <span>声线工作室</span><small>试听、导入和创建声音</small>
                    </button>
                    <button type="button" role="menuitem" data-reader-nav="settings">
                        <span>设置</span><small>引擎、音质与 API</small>
                    </button>
                    <p class="reader-menu-label reader-menu-label-spaced">当前作品</p>
                    <button type="button" role="menuitem" data-reader-action="advanced">
                        <span>本次生成选项</span><small>格式、章节拆分与更多参数</small>
                    </button>
                    <button type="button" role="menuitem" data-reader-action="projects">
                        <span>作品管理</span><small>保存或切换正在编辑的小说</small>
                    </button>
                    <button type="button" role="menuitem" data-reader-action="pronunciation">
                        <span>读音纠正</span><small>修正人名与特殊词语读音</small>
                    </button>
                    <button type="button" role="menuitem" data-reader-nav="help">
                        <span>使用帮助</span><small>三步完成第一本有声书</small>
                    </button>
                    <div class="reader-menu-system"><span id="reader-menu-mode">正在检查运行环境…</span></div>
                </div>
            </div>
        `;
        container.insertBefore(appbar, legacyHeader);

        const closeMenu = () => {
            const button = document.getElementById('reader-more-button');
            const menu = document.getElementById('reader-more-menu');
            if (!button || !menu) return;
            button.setAttribute('aria-expanded', 'false');
            menu.hidden = true;
        };
        const openTab = tabName => {
            document.querySelector(`.tab-button[data-tab="${tabName}"]`)?.click();
            document.querySelectorAll('[data-reader-nav]').forEach(button => {
                button.classList.toggle('active', button.dataset.readerNav === tabName);
            });
            closeMenu();
            window.scrollTo({top: 0, behavior: 'smooth'});
        };

        appbar.querySelectorAll('[data-reader-nav]').forEach(button => {
            button.addEventListener('click', () => openTab(button.dataset.readerNav));
        });
        appbar.querySelectorAll('[data-reader-action]').forEach(button => {
            button.addEventListener('click', () => {
                const action = button.dataset.readerAction;
                if (action === 'projects') document.getElementById('project-manage-btn')?.click();
                if (action === 'pronunciation') document.getElementById('alt-word-registry-btn')?.click();
                if (action === 'advanced') {
                    openTab('generate');
                    const generateTab = document.getElementById('generate-tab');
                    const visible = generateTab?.classList.toggle('reader-show-advanced');
                    if (visible) {
                        setTimeout(() => generateTab.querySelector('.reader-legacy-panel')?.scrollIntoView({behavior: 'smooth'}), 50);
                    }
                }
                closeMenu();
            });
        });
        document.querySelectorAll('.tab-button[data-tab]').forEach(button => {
            button.addEventListener('click', () => {
                document.querySelectorAll('[data-reader-nav]').forEach(navButton => {
                    navButton.classList.toggle('active', navButton.dataset.readerNav === button.dataset.tab);
                });
            });
        });
        document.getElementById('reader-more-button')?.addEventListener('click', event => {
            event.stopPropagation();
            const button = event.currentTarget;
            const menu = document.getElementById('reader-more-menu');
            const willOpen = menu.hidden;
            menu.hidden = !willOpen;
            button.setAttribute('aria-expanded', String(willOpen));
        });
        document.addEventListener('click', event => {
            if (!event.target.closest('.reader-appnav-actions')) closeMenu();
        });
        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape') return;
            closeMenu();
            document.getElementById('reader-shell')?.classList.remove('reader-show-chapters', 'reader-show-voices');
        });

        const syncMode = () => {
            const source = document.getElementById('current-mode');
            const target = document.getElementById('reader-menu-mode');
            if (source && target) target.textContent = `运行方式：${source.textContent || '正在检查…'}`;
        };
        syncMode();
        const mode = document.getElementById('current-mode');
        if (mode) new MutationObserver(syncMode).observe(mode, {childList: true, characterData: true, subtree: true});
    }

    function buildReaderShell() {
        const generateTab = document.getElementById('generate-tab');
        const textWrapper = document.getElementById('text-input-wrapper');
        if (!generateTab || !textWrapper || document.getElementById('reader-shell')) return;

        Array.from(generateTab.children).forEach(child => child.classList.add('reader-legacy-panel'));

        const shell = createElement('section', 'reader-shell reader-hide-voices', '');
        shell.id = 'reader-shell';
        shell.innerHTML = `
            <div class="reader-topbar">
                <div class="reader-book-meta">
                    <span class="reader-book-kicker">当前作品</span>
                    <h2 class="reader-book-title" id="reader-book-title">未命名小说</h2>
                    <p class="reader-book-subtitle" id="reader-book-subtitle">导入小说后自动识别章节与角色</p>
                </div>
                <div class="reader-top-actions">
                    <button type="button" class="reader-soft-button" id="reader-import-button">导入小说</button>
                    <button type="button" class="reader-icon-button" id="reader-theme-button" title="切换日间/夜间" aria-label="切换日间或夜间模式">◐</button>
                </div>
            </div>
            <div class="reader-workspace">
                <button type="button" class="reader-drawer-scrim" id="reader-drawer-scrim" aria-label="关闭侧边面板"></button>
                <aside class="reader-chapters" aria-label="小说目录">
                    <div class="reader-side-title"><h3>目录</h3><span id="reader-chapter-count">0 章</span></div>
                    <div class="reader-chapter-list" id="reader-chapter-list"></div>
                </aside>
                <main class="reader-page" id="reader-page">
                    <div class="reader-page-tools">
                        <div class="reader-page-tools-group">
                            <button type="button" class="reader-page-mode active" id="reader-edit-mode">编辑正文</button>
                            <button type="button" class="reader-page-mode" id="reader-preview-mode">阅读预览</button>
                        </div>
                        <div class="reader-page-tools-group">
                            <button type="button" class="reader-icon-button" id="reader-font-down" title="缩小字号">A−</button>
                            <button type="button" class="reader-icon-button" id="reader-font-up" title="放大字号">A＋</button>
                        </div>
                    </div>
                    <div class="reader-editor-slot" id="reader-editor-slot">
                        <div class="reader-empty-state" id="reader-empty-state">
                            <span class="reader-empty-mark" aria-hidden="true">文</span>
                            <h3>把小说变成有声书</h3>
                            <p>导入文件或粘贴正文。角色识别、配音和章节拆分都可以稍后自动完成。</p>
                            <div class="reader-empty-actions">
                                <button type="button" class="reader-empty-primary" id="reader-empty-import">选择小说文件</button>
                                <button type="button" class="reader-empty-secondary" id="reader-empty-paste">粘贴正文</button>
                            </div>
                            <small>支持 TXT、PDF、Word、EPUB 和 Markdown</small>
                        </div>
                    </div>
                    <div class="reader-preview" id="reader-preview"></div>
                    <span class="reader-page-status" id="reader-page-status">0 字</span>
                </main>
                <aside class="reader-voice-panel" id="reader-voice-panel" aria-label="角色与声线">
                    <div class="reader-side-title">
                        <h3>角色与声线</h3>
                        <span>可逐个调整</span>
                        <button type="button" class="reader-voice-close" id="reader-voice-close">完成</button>
                    </div>
                    <p class="reader-voice-intro">先“智能分角色”，再给每个人物选声线。展开“微调”可以改情绪、语速和音高。</p>
                    <div class="reader-cast-actions">
                        <button type="button" id="reader-smart-cast">智能分角色</button>
                        <button type="button" id="reader-auto-voice">智能配音</button>
                    </div>
                    <div class="reader-role-list" id="reader-role-list"></div>
                </aside>
            </div>
            <div class="reader-player-bar">
                <div class="reader-bottom-nav">
                    <button type="button" class="reader-nav-button" id="reader-directory-button">目录</button>
                    <button type="button" class="reader-nav-button" id="reader-voice-button">角色与声线</button>
                </div>
                <div class="reader-player-slot" id="reader-player-slot">
                    <div class="reader-player-empty" id="reader-player-empty">生成完成后，可在这里直接播放</div>
                </div>
                <div class="reader-generation-summary">
                    <strong id="reader-generation-label">准备生成</strong>
                    <span id="reader-action-note">自动识别角色与章节</span>
                </div>
                <button type="button" class="reader-primary-action" id="reader-generate-button">生成有声书</button>
            </div>
        `;
        generateTab.insertBefore(shell, generateTab.firstChild);
        document.getElementById('reader-editor-slot').appendChild(textWrapper);

        const latestAudio = document.getElementById('latest-audio-container');
        if (latestAudio) {
            latestAudio.classList.remove('reader-legacy-panel');
            document.getElementById('reader-player-slot').appendChild(latestAudio);
        }

        const textarea = document.getElementById('input-text');
        if (textarea) {
            textarea.placeholder = PLACEHOLDER_MAP.get(textarea.placeholder) || textarea.placeholder;
            textarea.addEventListener('input', updateReaderContent);
            textarea.addEventListener('change', updateReaderContent);
        }
        const clearButton = document.getElementById('clear-text-btn');
        if (clearButton) {
            clearButton.textContent = '清空';
            clearButton.title = '清空正文';
            clearButton.setAttribute('aria-label', '清空正文');
        }
        bindReaderActions();
        updateReaderContent();
        updateGenerationSummary();
    }

    function buildChineseHelp() {
        const helpTab = document.getElementById('help-tab');
        if (!helpTab) return;
        helpTab.innerHTML = `
            <section class="reader-guide">
                <div class="reader-guide-hero">
                    <span>第一次用，从这里开始</span>
                    <h2>三步把小说变成多人有声书</h2>
                    <p>不需要懂模型，也不用手写角色标签。所有内容和声音都留在这台电脑上。</p>
                    <button type="button" class="btn btn-primary" data-reader-go="generate">回到阅读页</button>
                </div>
                <div class="reader-guide-steps">
                    <article><b>1</b><h3>导入小说</h3><p>点击“导入小说”，选择 TXT、PDF、Word 或 EPUB；也可以直接粘贴正文。</p></article>
                    <article><b>2</b><h3>分角色、配声线</h3><p>先点“智能分角色”，再点“智能配音”。想换声音，就在人物右侧选择；点“微调”可改情绪、语速、音高。</p></article>
                    <article><b>3</b><h3>生成有声书</h3><p>点击底部“生成有声书”。制作时可以离开阅读页，完成后会出现在“我的有声书”。</p></article>
                </div>
                <div class="reader-guide-buttons">
                    <h3>这些按钮分别做什么？</h3>
                    <dl>
                        <div><dt>智能分角色</dt><dd>从正文里找出旁白和真正开口的人物。</dd></div>
                        <div><dt>智能配音</dt><dd>按人物年龄、性格和气质自动推荐声线。</dd></div>
                        <div><dt>阅读预览</dt><dd>隐藏角色标签，按正常小说排版阅读。</dd></div>
                        <div><dt>微调</dt><dd>单独修改某个人物的情绪、语速和音高。</dd></div>
                        <div><dt>日间 / 夜间</dt><dd>点击右上角半圆按钮，切换浅色或深色阅读背景。</dd></div>
                        <div><dt>声线</dt><dd>在手机窄屏上打开人物声线抽屉。</dd></div>
                    </dl>
                </div>
                <div class="reader-guide-note"><strong>建议：</strong>先用一章、两三个人物测试。满意后再生成整本，调声线会快很多。</div>
            </section>
        `;
        helpTab.querySelector('[data-reader-go="generate"]')?.addEventListener('click', () => {
            document.querySelector('.tab-button[data-tab="generate"]')?.click();
        });
    }

    function simplifyOtherPages() {
        document.querySelectorAll('.help-icon').forEach(button => button.setAttribute('hidden', ''));
        document.querySelectorAll('#voices-tab [data-voices-section], #custom-voices-section').forEach(section => {
            section.hidden = false;
            section.removeAttribute('aria-hidden');
            section.classList.add('collapsed');
        });
        const qwenSection = document.getElementById('qwen-voices-section');
        qwenSection?.classList.remove('collapsed');
        const qwenHeading = qwenSection?.querySelector('h2');
        if (qwenHeading) qwenHeading.textContent = '创建自己的中文声线';
        const qwenHelp = qwenSection?.querySelector('.help-text');
        if (qwenHelp) qwenHelp.textContent = '挑一个接近的人设，再修改描述和台词，生成一段试听。';
        const qwenToggle = qwenSection?.querySelector('.voices-section-toggle');
        if (qwenToggle) qwenToggle.textContent = '▼';
    }

    function bindReaderActions() {
        const shell = document.getElementById('reader-shell');
        const generateTab = document.getElementById('generate-tab');

        document.getElementById('reader-import-button')?.addEventListener('click', () => {
            document.getElementById('browse-document-btn')?.click();
        });
        document.getElementById('reader-empty-import')?.addEventListener('click', () => {
            document.getElementById('browse-document-btn')?.click();
        });
        document.getElementById('reader-empty-paste')?.addEventListener('click', () => {
            document.getElementById('reader-page')?.classList.remove('reader-is-empty');
            document.getElementById('input-text')?.focus();
        });
        document.getElementById('reader-smart-cast')?.addEventListener('click', () => {
            const button = document.getElementById('gemini-process-btn');
            if (!document.getElementById('input-text')?.value.trim()) {
                readerMessage('请先导入或粘贴小说正文。');
                return;
            }
            button?.click();
            readerMessage('正在识别旁白和真正开口说话的人物…');
        });
        document.getElementById('reader-auto-voice')?.addEventListener('click', autoAssignReaderVoices);
        document.getElementById('reader-theme-button')?.addEventListener('click', () => {
            document.body.classList.toggle('reader-dark');
            localStorage.setItem('reader-theme', document.body.classList.contains('reader-dark') ? 'dark' : 'light');
        });
        document.getElementById('reader-voice-button')?.addEventListener('click', () => {
            shell.classList.remove('reader-show-chapters');
            shell.classList.toggle('reader-show-voices');
        });
        document.getElementById('reader-voice-close')?.addEventListener('click', () => {
            shell.classList.remove('reader-show-voices');
        });
        document.getElementById('reader-directory-button')?.addEventListener('click', () => {
            shell.classList.remove('reader-show-voices');
            shell.classList.toggle('reader-show-chapters');
        });
        document.getElementById('reader-drawer-scrim')?.addEventListener('click', () => {
            shell.classList.remove('reader-show-chapters', 'reader-show-voices');
        });
        document.getElementById('reader-preview-mode')?.addEventListener('click', () => setReaderMode(true));
        document.getElementById('reader-edit-mode')?.addEventListener('click', () => setReaderMode(false));
        document.getElementById('reader-font-up')?.addEventListener('click', () => changeReaderFont(1));
        document.getElementById('reader-font-down')?.addEventListener('click', () => changeReaderFont(-1));
        document.getElementById('reader-previous-button')?.addEventListener('click', () => moveChapter(-1));
        document.getElementById('reader-next-button')?.addEventListener('click', () => moveChapter(1));
        document.getElementById('reader-generate-button')?.addEventListener('click', generateFromReader);
        document.getElementById('job-tts-engine')?.addEventListener('change', updateGenerationSummary);
        document.getElementById('job-output-format')?.addEventListener('change', updateGenerationSummary);

        document.getElementById('latest-audio-player')?.addEventListener('loadedmetadata', () => {
            document.getElementById('reader-player-empty')?.remove();
        });
        document.getElementById('latest-audio-player')?.addEventListener('play', () => {
            const button = document.getElementById('reader-generate-button');
            if (button) button.textContent = '正在播放';
        });
        document.getElementById('latest-audio-player')?.addEventListener('pause', () => {
            const button = document.getElementById('reader-generate-button');
            if (button && !button.disabled) button.textContent = '生成有声书';
        });
    }

    function updateGenerationSummary() {
        const engine = document.getElementById('job-tts-engine');
        const format = document.getElementById('job-output-format');
        const label = document.getElementById('reader-generation-label');
        const note = document.getElementById('reader-action-note');
        const engineLabel = engine?.selectedOptions?.[0]?.textContent?.trim() || '默认引擎';
        const formatLabel = format?.selectedOptions?.[0]?.textContent?.trim() || 'MP3';
        if (label) label.textContent = `${engineLabel} · ${formatLabel}`;
        if (note && !note.dataset.temporary) note.textContent = '自动识别角色与章节';
    }

    async function generateFromReader() {
        const textarea = document.getElementById('input-text');
        const button = document.getElementById('reader-generate-button');
        if (!textarea?.value.trim()) {
            readerMessage('请先导入或粘贴小说正文。');
            return;
        }
        button.disabled = true;
        button.textContent = '正在准备…';
        try {
            if (typeof window.analyzeText === 'function') {
                await window.analyzeText({auto: true});
                await new Promise(resolve => setTimeout(resolve, 120));
            }
            await ensureReaderAssignments();
            document.getElementById('generate-btn')?.click();
            readerMessage('已加入制作进度，完成后会出现在底部播放器。');
            button.textContent = '正在生成…';
            setTimeout(() => {
                button.disabled = false;
                button.textContent = '生成有声书';
            }, 1600);
        } catch (error) {
            button.disabled = false;
            button.textContent = '生成有声书';
            readerMessage(error.message || '暂时无法开始生成。');
        }
    }

    async function ensureReaderAssignments() {
        if (!presets.length) await loadPresets();
        if (typeof window.populateVoiceSelects === 'function') window.populateVoiceSelects();
        const rows = Array.from(document.querySelectorAll('#inline-voice-assignment-list .voice-assignment-row'));
        rows.forEach(row => {
            const select = row.querySelector('.voice-select');
            if (!select || select.value) return;
            const speaker = (row.dataset.speaker || '').toLowerCase();
            const fallback = /narrator|旁白/.test(speaker) ? 'ink_narrator' : 'qingxia';
            select.value = fallback;
            select.dispatchEvent(new Event('change', {bubbles: true}));
        });
        renderReaderRoles();
    }

    async function autoAssignReaderVoices() {
        const rows = Array.from(document.querySelectorAll('#inline-voice-assignment-list .voice-assignment-row'));
        if (!rows.length) {
            readerMessage('请先完成“智能分角色”。');
            return;
        }
        if (!presets.length) await loadPresets();
        if (typeof window.populateVoiceSelects === 'function') window.populateVoiceSelects();

        const availableIds = new Set(presets.map(preset => preset.id));
        const neutralRotation = [
            'qingxia',
            'yanshu',
            'frost_master',
            'moon_guard',
            'warm_narrator',
            'cloud_general'
        ].filter(id => availableIds.has(id));
        let neutralIndex = 0;
        let assigned = 0;

        rows.forEach(row => {
            const source = row.querySelector('.voice-select');
            if (!source) return;
            const speaker = String(row.dataset.speaker || '').toLowerCase();
            const normalizedSpeaker = speaker
                .replace(/[-_](male|female|neutral)$/i, '')
                .replace(/-/g, '_');
            let choice = '';
            if (/narrator|旁白/.test(speaker)) {
                choice = availableIds.has('ink_narrator') ? 'ink_narrator' : 'warm_narrator';
            } else if (availableIds.has(normalizedSpeaker)) {
                choice = normalizedSpeaker;
            } else if (/[-_]female$/.test(speaker)) {
                choice = availableIds.has('qingxia') ? 'qingxia' : neutralRotation[neutralIndex++ % neutralRotation.length];
            } else if (/[-_]male$/.test(speaker)) {
                choice = availableIds.has('yanshu') ? 'yanshu' : neutralRotation[neutralIndex++ % neutralRotation.length];
            } else if (neutralRotation.length) {
                choice = neutralRotation[neutralIndex++ % neutralRotation.length];
            }
            if (!choice || !availableIds.has(choice)) return;
            source.value = choice;
            source.dispatchEvent(new Event('change', {bubbles: true}));
            assigned += 1;
        });
        setTimeout(renderReaderRoles, 100);
        readerMessage(`已为 ${assigned} 个角色配好不同声线；不满意可以逐个更换。`);
    }

    function setReaderMode(previewing) {
        const page = document.getElementById('reader-page');
        page?.classList.toggle('reader-previewing', previewing);
        document.getElementById('reader-preview-mode')?.classList.toggle('active', previewing);
        document.getElementById('reader-edit-mode')?.classList.toggle('active', !previewing);
        if (previewing) renderPreview();
    }

    function changeReaderFont(direction) {
        const current = parseInt(localStorage.getItem('reader-font-size') || '19', 10);
        const next = Math.max(15, Math.min(28, current + direction));
        document.documentElement.style.setProperty('--reader-font-size', `${next}px`);
        localStorage.setItem('reader-font-size', String(next));
    }

    function updateReaderContent() {
        const textarea = document.getElementById('input-text');
        const text = textarea?.value || '';
        lastTextValue = text;
        document.getElementById('reader-page')?.classList.toggle('reader-is-empty', !text.trim());
        const compact = text.replace(/\[[^\]]+\]/g, '').replace(/\s+/g, '');
        const count = compact.length;
        const status = document.getElementById('reader-page-status');
        if (status) status.textContent = `${count.toLocaleString('zh-CN')} 字`;
        const subtitle = document.getElementById('reader-book-subtitle');
        if (subtitle) subtitle.textContent = text.trim() ? `${count.toLocaleString('zh-CN')} 字 · 正在自动分析章节与角色` : '导入小说后自动识别章节与角色';
        updateBookTitle(text);
        renderChapters(text);
        if (document.getElementById('reader-page')?.classList.contains('reader-previewing')) renderPreview();
    }

    function updateBookTitle(text) {
        const lines = String(text || '').split(/\r?\n/).map(line => line.replace(/\[[^\]]+\]/g, '').trim()).filter(Boolean);
        const first = lines[0] || '未命名小说';
        const title = /^(第.{1,12}[卷部篇章]|序章|楔子|前言|尾声|番外)/.test(first)
            ? '我的小说'
            : first.slice(0, 28);
        const titleElement = document.getElementById('reader-book-title');
        if (titleElement) titleElement.textContent = title;
    }

    function getChapterMatches(text) {
        const pattern = /^(?:\[[^\]]+\])?\s*((?:第[一二三四五六七八九十百千万零〇两0-9]+[卷部篇章节回]|卷[一二三四五六七八九十百千万零〇两0-9]+|序章|楔子|序言|前言|后记|尾声|番外)[^\n\[]*)/gm;
        return Array.from(String(text || '').matchAll(pattern)).map(match => ({
            title: match[1].replace(/\[\/?[^\]]+\]/g, '').trim(),
            index: match.index || 0
        }));
    }

    function renderChapters(text) {
        const list = document.getElementById('reader-chapter-list');
        if (!list) return;
        const matches = getChapterMatches(text);
        const count = document.getElementById('reader-chapter-count');
        if (count) count.textContent = `${matches.length} 章`;
        list.innerHTML = '';
        if (!matches.length) {
            const empty = createElement('div', 'reader-chapter-empty', text.trim()
                ? '暂未识别到章节标题，仍可按整本生成。'
                : '导入小说后，章节会显示在这里。');
            list.appendChild(empty);
            return;
        }
        matches.slice(0, 240).forEach((chapter, index) => {
            const button = createElement('button', 'reader-chapter-item', chapter.title);
            button.type = 'button';
            button.dataset.chapterIndex = String(index);
            button.addEventListener('click', () => goToChapter(chapter.index));
            list.appendChild(button);
        });
    }

    function goToChapter(index) {
        const textarea = document.getElementById('input-text');
        if (!textarea) return;
        setReaderMode(false);
        textarea.focus();
        textarea.setSelectionRange(index, index);
        const lineHeight = parseFloat(getComputedStyle(textarea).lineHeight) || 38;
        const linesBefore = textarea.value.slice(0, index).split('\n').length;
        textarea.scrollTop = Math.max(0, linesBefore * lineHeight - 90);
        document.getElementById('reader-shell')?.classList.remove('reader-show-chapters');
    }

    function moveChapter(direction) {
        const textarea = document.getElementById('input-text');
        const matches = getChapterMatches(textarea?.value || '');
        if (!textarea || !matches.length) {
            readerMessage('当前正文里还没有识别到章节标题。');
            return;
        }
        const current = textarea.selectionStart || 0;
        let target;
        if (direction > 0) target = matches.find(item => item.index > current + 1) || matches[matches.length - 1];
        else target = [...matches].reverse().find(item => item.index < current - 1) || matches[0];
        goToChapter(target.index);
    }

    function friendlySpeakerName(name) {
        const value = String(name || '').trim();
        if (/^(narrator|ink_narrator|旁白)$/i.test(value)) return '旁白';
        if (/^speaker\s*(\d+)$/i.test(value)) return value.replace(/^speaker\s*/i, '角色 ');
        if (/^character[-_](\d+)(?:[-_](?:male|female|neutral))?$/i.test(value)) {
            return value.replace(/^character[-_](\d+).*$/i, '角色 $1');
        }
        const unicodeName = Array.from(value.matchAll(/(?:^|-)u([0-9a-f]{4,6})(?=-|$)/gi))
            .map(match => String.fromCodePoint(parseInt(match[1], 16)))
            .join('');
        if (unicodeName) return unicodeName;
        const normalized = value.replace(/[-_](male|female|neutral)$/i, '').replace(/-/g, '_').toLowerCase();
        const matchingPreset = presets.find(preset => String(preset.id || '').toLowerCase() === normalized);
        if (matchingPreset?.label) return matchingPreset.label.split('·')[0].trim();
        return value.replace(/[-_](male|female)$/i, '').replace(/[_-]+/g, ' ');
    }

    function renderPreview() {
        const preview = document.getElementById('reader-preview');
        const text = document.getElementById('input-text')?.value || '';
        if (!preview) return;
        preview.innerHTML = '';
        if (!text.trim()) {
            preview.appendChild(createElement('p', '', '导入一本小说，开始沉浸阅读。'));
            return;
        }
        const blockPattern = /\[([^\]/]+)\]([\s\S]*?)\[\/\1\]/g;
        let cursor = 0;
        let match;
        const appendPlain = value => {
            value.split(/\n{2,}|\n/).map(part => part.trim()).filter(Boolean).forEach(part => {
                const paragraph = createElement('p', '', part);
                preview.appendChild(paragraph);
            });
        };
        while ((match = blockPattern.exec(text)) !== null) {
            if (match.index > cursor) appendPlain(text.slice(cursor, match.index).replace(/\[\/?[^\]]+\]/g, ''));
            const paragraph = createElement('p', 'reader-dialogue', '');
            const label = createElement('span', 'reader-speaker-label', friendlySpeakerName(match[1]));
            paragraph.appendChild(label);
            paragraph.appendChild(document.createTextNode(match[2].replace(/\[\/?[^\]]+\]/g, '').trim()));
            preview.appendChild(paragraph);
            cursor = match.index + match[0].length;
        }
        if (cursor < text.length) appendPlain(text.slice(cursor).replace(/\[\/?[^\]]+\]/g, ''));
    }

    async function loadPresets() {
        try {
            const response = await fetch('/api/qwen3/voice-design/presets');
            const data = await response.json();
            presets = data.success && Array.isArray(data.presets) ? data.presets : [];
        } catch (error) {
            presets = [];
        }
    }

    function createPresetSelect(selectedValue) {
        const select = createElement('select', 'reader-role-voice', '');
        const placeholder = createElement('option', '', '选择声线…');
        placeholder.value = '';
        select.appendChild(placeholder);
        const grouped = new Map();
        presets.forEach(preset => {
            const source = preset.source || '其他';
            if (!grouped.has(source)) grouped.set(source, []);
            grouped.get(source).push(preset);
        });
        grouped.forEach((items, source) => {
            const group = document.createElement('optgroup');
            group.label = source;
            items.forEach(preset => {
                const option = createElement('option', '', preset.label || preset.name);
                option.value = preset.id;
                option.title = (preset.reference_characters || []).length
                    ? `人设参考：${preset.reference_characters.join('、')}`
                    : preset.description || '';
                group.appendChild(option);
            });
            select.appendChild(group);
        });
        if (selectedValue) select.value = selectedValue;
        return select;
    }

    function proxyRange(card, row, role, label, min, max, step, fallback, suffix) {
        const wrapper = createElement('div', 'reader-control-row', '');
        wrapper.appendChild(createElement('span', '', label));
        const range = document.createElement('input');
        range.type = 'range';
        range.min = String(min);
        range.max = String(max);
        range.step = String(step);
        const hidden = row.querySelector(`[data-role="${role}"]`);
        range.value = hidden?.value || String(fallback);
        const value = createElement('span', 'reader-control-value', `${range.value}${suffix}`);
        range.addEventListener('input', () => {
            value.textContent = `${range.value}${suffix}`;
            const target = row.querySelector(`[data-role="${role}"]`);
            if (target) {
                target.value = range.value;
                target.dispatchEvent(new Event('input', {bubbles: true}));
            }
        });
        wrapper.append(range, value);
        card.appendChild(wrapper);
    }

    function renderReaderRoles() {
        const list = document.getElementById('reader-role-list');
        if (!list) return;
        const rows = Array.from(document.querySelectorAll('#inline-voice-assignment-list .voice-assignment-row'));
        list.innerHTML = '';
        if (!rows.length) {
            list.appendChild(createElement('div', 'reader-role-empty', '导入小说后点击“智能分角色”，这里会出现旁白和人物。'));
            return;
        }

        rows.forEach(row => {
            const speaker = row.dataset.speaker || '角色';
            const sourceSelect = row.querySelector('.voice-select');
            const card = createElement('article', 'reader-role-card', '');
            const summary = createElement('div', 'reader-role-summary', '');
            summary.appendChild(createElement('span', 'reader-role-name', friendlySpeakerName(speaker)));
            const voiceSelect = createPresetSelect(sourceSelect?.value || '');
            voiceSelect.addEventListener('change', () => {
                if (typeof window.populateVoiceSelects === 'function') window.populateVoiceSelects();
                const target = row.querySelector('.voice-select');
                if (target) {
                    target.value = voiceSelect.value;
                    target.dispatchEvent(new Event('change', {bubbles: true}));
                }
            });
            summary.appendChild(voiceSelect);
            const toggle = createElement('button', 'reader-role-toggle', '微调');
            toggle.type = 'button';
            toggle.addEventListener('click', () => {
                card.classList.toggle('expanded');
                toggle.textContent = card.classList.contains('expanded') ? '收起' : '微调';
            });
            summary.appendChild(toggle);
            card.appendChild(summary);

            const details = createElement('div', 'reader-role-details', '');
            const emotionRow = createElement('div', 'reader-control-row', '');
            emotionRow.appendChild(createElement('span', '', '情绪'));
            const emotionSelect = document.createElement('select');
            EMOTIONS.forEach(([value, label]) => {
                const option = createElement('option', '', label);
                option.value = value;
                emotionSelect.appendChild(option);
            });
            const existingInstruction = row.querySelector('.qwen3-instruct-input')?.value || '';
            const exactEmotion = EMOTIONS.find(([value]) => value === existingInstruction);
            if (exactEmotion) emotionSelect.value = exactEmotion[0];
            emotionSelect.addEventListener('change', () => {
                const target = row.querySelector('.qwen3-instruct-input');
                if (target) {
                    target.value = emotionSelect.value;
                    target.dispatchEvent(new Event('input', {bubbles: true}));
                }
            });
            emotionRow.appendChild(emotionSelect);
            emotionRow.appendChild(createElement('span', 'reader-control-value', ''));
            details.appendChild(emotionRow);
            proxyRange(details, row, 'fx-speed', '语速', 0.75, 1.35, 0.05, 1, '×');
            proxyRange(details, row, 'fx-pitch', '音高', -4, 4, 0.5, 0, '');
            const previewButton = createElement('button', 'reader-role-preview', '▶ 试听这条声线');
            previewButton.type = 'button';
            previewButton.addEventListener('click', () => {
                if (!voiceSelect.value) {
                    readerMessage('请先给这个角色选择一条声线。');
                    return;
                }
                row.querySelector('[data-role="fx-preview-btn"]')?.click();
            });
            details.appendChild(previewButton);
            card.appendChild(details);
            list.appendChild(card);
        });
    }

    function readerMessage(message) {
        const note = document.getElementById('reader-action-note');
        if (!note) return;
        note.dataset.temporary = 'true';
        note.textContent = message;
        clearTimeout(readerMessage.timer);
        readerMessage.timer = setTimeout(() => {
            delete note.dataset.temporary;
            updateGenerationSummary();
        }, 4200);
    }

    function observeDynamicUi() {
        const roleHost = document.getElementById('inline-voice-assignment-list');
        if (roleHost) {
            new MutationObserver(() => {
                clearTimeout(roleRenderTimer);
                roleRenderTimer = setTimeout(renderReaderRoles, 80);
            }).observe(roleHost, {childList: true, subtree: true});
        }
        new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === Node.ELEMENT_NODE) localizeTree(node);
                    else if (node.nodeType === Node.TEXT_NODE && node.parentElement) localizeTree(node.parentElement);
                });
                if (mutation.type === 'characterData' && mutation.target.parentElement) {
                    localizeTree(mutation.target.parentElement);
                }
            });
        }).observe(document.body, {childList: true, characterData: true, subtree: true});

        setInterval(() => {
            const value = document.getElementById('input-text')?.value || '';
            if (value !== lastTextValue) updateReaderContent();
            const latest = document.getElementById('latest-audio-container');
            if (latest && latest.style.display !== 'none') document.getElementById('reader-player-empty')?.remove();
        }, 900);
    }

    async function init() {
        document.body.classList.add('reader-ui');
        document.documentElement.lang = 'zh-CN';
        document.title = '声阅 - AI 多角色小说阅读器';
        if (localStorage.getItem('reader-theme') === 'dark') document.body.classList.add('reader-dark');
        const savedFont = parseInt(localStorage.getItem('reader-font-size') || '19', 10);
        document.documentElement.style.setProperty('--reader-font-size', `${Math.max(15, Math.min(28, savedFont))}px`);
        localizeTree(document);
        buildAppNavigation();
        buildReaderShell();
        buildChineseHelp();
        simplifyOtherPages();
        await loadPresets();
        renderReaderRoles();
        observeDynamicUi();
        localizeTree(document);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
