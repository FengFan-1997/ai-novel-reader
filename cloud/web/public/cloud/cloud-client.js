(function () {
    'use strict';

    const nativeAlert = window.alert.bind(window);
    window.alert = message => {
        if (document.documentElement.classList.contains('cloud-session-ready')) {
            nativeAlert(message);
            return;
        }
        console.warn('[声阅云端提示]', message);
    };

    let overlay;
    let statusTimer;

    function createOverlay() {
        if (document.getElementById('cloud-gate')) return document.getElementById('cloud-gate');
        const gate = document.createElement('div');
        gate.id = 'cloud-gate';
        gate.className = 'cloud-gate';
        gate.innerHTML = `
            <section class="cloud-gate-card" role="dialog" aria-modal="true" aria-labelledby="cloud-gate-title">
                <span class="cloud-gate-brand">声</span>
                <div class="cloud-gate-status"><i></i><span id="cloud-gate-kicker">正在连接</span></div>
                <h1 id="cloud-gate-title">正在连接你的本地声阅</h1>
                <p id="cloud-gate-message">云端界面已经就绪，正在确认本地模型是否在线。</p>
                <form id="cloud-login-form" hidden>
                    <label for="cloud-password">访问密码</label>
                    <input id="cloud-password" type="password" autocomplete="current-password" placeholder="输入声阅云端访问密码">
                    <button type="submit">进入声阅</button>
                    <span id="cloud-login-error" role="alert"></span>
                </form>
                <div class="cloud-maintenance-actions" id="cloud-maintenance-actions" hidden>
                    <button type="button" id="cloud-retry">重新连接</button>
                    <button type="button" class="secondary" id="cloud-readonly">进入只读界面</button>
                </div>
                <small id="cloud-gate-detail">只有这台电脑启动声阅后，云端才会调用本地模型。</small>
            </section>
        `;
        document.body.appendChild(gate);
        gate.querySelector('#cloud-login-form').addEventListener('submit', login);
        gate.querySelector('#cloud-retry').addEventListener('click', checkStatus);
        gate.querySelector('#cloud-readonly').addEventListener('click', () => {
            gate.classList.add('cloud-gate-dismissed');
            document.querySelector('.tab-button[data-tab="help"]')?.click();
        });
        return gate;
    }

    function showState(state, message) {
        overlay = overlay || createOverlay();
        overlay.classList.remove('cloud-online', 'cloud-auth', 'cloud-maintenance', 'cloud-gate-dismissed');
        overlay.classList.add(`cloud-${state}`);
        const loginForm = overlay.querySelector('#cloud-login-form');
        const actions = overlay.querySelector('#cloud-maintenance-actions');
        const title = overlay.querySelector('#cloud-gate-title');
        const kicker = overlay.querySelector('#cloud-gate-kicker');
        const detail = overlay.querySelector('#cloud-gate-detail');

        loginForm.hidden = state !== 'auth';
        actions.hidden = state !== 'maintenance';
        if (state === 'auth') {
            kicker.textContent = '私人测试阶段';
            title.textContent = '欢迎回到声阅';
            detail.textContent = '访问密码只用于保护你电脑上的模型、作品与 API 设置。';
            setTimeout(() => overlay.querySelector('#cloud-password')?.focus(), 50);
        } else if (state === 'maintenance') {
            kicker.textContent = '本地引擎未连接';
            title.textContent = '声阅正在维护';
            detail.textContent = '仍可浏览界面和使用帮助；生成、试听与作品管理暂不可用。';
        } else {
            kicker.textContent = '正在连接';
            title.textContent = '正在连接你的本地声阅';
            detail.textContent = '只有这台电脑启动声阅后，云端才会调用本地模型。';
        }
        overlay.querySelector('#cloud-gate-message').textContent = message;
    }

    async function login(event) {
        event.preventDefault();
        const password = overlay.querySelector('#cloud-password').value;
        const error = overlay.querySelector('#cloud-login-error');
        const button = event.currentTarget.querySelector('button');
        error.textContent = '';
        button.disabled = true;
        button.textContent = '正在验证…';
        try {
            const response = await fetch('/bridge/login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password})
            });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || '无法登录。');
            window.location.reload();
        } catch (loginError) {
            error.textContent = loginError.message || '无法登录，请稍后重试。';
            button.disabled = false;
            button.textContent = '进入声阅';
        }
    }

    async function checkStatus() {
        clearTimeout(statusTimer);
        showState('connecting', '云端界面已经就绪，正在确认本地模型是否在线。');
        try {
            const response = await fetch('/bridge/status', {cache: 'no-store', credentials: 'same-origin'});
            const data = await response.json();
            if (!data.authenticated) {
                showState('auth', '请输入访问密码。当前阶段只有受邀设备可以使用本地模型。');
                return;
            }
            if (!data.online) {
                showState('maintenance', '本地电脑可能尚未启动声阅，或正在更新模型。');
                statusTimer = setTimeout(checkStatus, 30_000);
                return;
            }
            overlay = overlay || createOverlay();
            document.documentElement.classList.add('cloud-session-ready');
            window.alert = nativeAlert;
            overlay.classList.add('cloud-online');
            setTimeout(() => overlay?.remove(), 260);
        } catch {
            showState('maintenance', '云端服务正在唤醒，请稍后重新连接。');
            statusTimer = setTimeout(checkStatus, 30_000);
        }
    }

    window.addEventListener('DOMContentLoaded', () => {
        overlay = createOverlay();
        checkStatus();
    });
})();
