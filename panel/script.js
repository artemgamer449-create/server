
		const TURNSTILE_SITE_KEY = "0x4AAAAAAFi7N7hnSxXvj04S";
		const TOKEN_KEY = "visionpanel.token";

		const ICONS = {
			dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
			verified: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.6 14.4 5l3.4-.4 1 3.2 2.8 1.9-1.4 3.1 1.4 3.1-2.8 1.9-1 3.2-3.4-.4L12 23l-2.4-2.4-3.4.4-1-3.2-2.8-1.9 1.4-3.1-1.4-3.1 2.8-1.9 1-3.2 3.4.4Z"/><path d="m8.8 12.2 2.2 2.2 4.4-4.4"/></svg>',
			accounts: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M17 11v6"/><path d="M14 14h6"/></svg>',
			sessions: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="16" r="1.6"/></svg>',
			logout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>',
			menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/></svg>',
		};

		let token = null;
		let user = null;
		let currentTab = 'dashboard';
		let turnstileToken = '';

		const $ = (id) => document.getElementById(id);
		const appEl = $('app');

		function storeToken(value) {
			token = value;
			try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); } catch (e) {}
		}
		try { token = localStorage.getItem(TOKEN_KEY) || null; } catch (e) {}

		function toast(message, type = 'success') {
			const container = $('toasts');
			const item = document.createElement('div');
			item.className = 'fade-in pointer-events-auto flex items-start gap-3 rounded-xl border bg-[#121214] p-4 text-sm shadow-xl ' + (type === 'error' ? 'border-[#3f2024]' : 'border-[#2b2b30]');
			const dot = document.createElement('span');
			dot.className = 'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ' + (type === 'error' ? 'bg-[#f87171]/15 text-[#f87171]' : 'bg-[#fafafa]/10 text-[#e4e4e7]');
			dot.textContent = type === 'error' ? '!' : '✓';
			const text = document.createElement('span');
			text.className = 'leading-5 text-[#d4d4d8]';
			text.textContent = message;
			item.append(dot, text);
			container.append(item);
			setTimeout(() => item.remove(), 4200);
		}

		async function api(path, options = {}) {
			const headers = { Accept: 'application/json', ...(options.headers || {}) };
			if (token) headers['Authorization'] = 'Bearer ' + token;
			if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
			const response = await fetch(path, { ...options, headers });
			const text = await response.text();
			let data = {};
			if (text) { try { data = JSON.parse(text); } catch { data = { detail: text }; } }
			if (!response.ok) {
				const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ') : data.detail;
				if (response.status === 401 && token) { logoutLocal(); }
				throw new Error(detail || ('HTTP ' + response.status));
			}
			return data;
		}

		function el(tag, className, text) {
			const node = document.createElement(tag);
			if (className) node.className = className;
			if (text !== undefined) node.textContent = text;
			return node;
		}

		// ---------- Login ----------

		function renderLogin(errorMessage) {
			document.documentElement.classList.add('dark');
			appEl.innerHTML = `
				<div class="flex min-h-screen items-center justify-center px-4 py-10">
					<div class="fade-in w-full max-w-sm">
						<div class="mb-8 text-center">
							<div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-[#232327] bg-[#121214]">
								<span class="text-sm font-bold tracking-[0.2em] text-[#fafafa]">VP</span>
							</div>
							<h1 class="text-xl font-semibold tracking-tight text-[#fafafa]">VisionPanel</h1>
							<p class="mt-1.5 text-sm text-[#6b6b74]">Вход в панель управления</p>
						</div>
						<div class="card-2 rounded-2xl p-6">
							<form id="loginForm" class="grid gap-4">
								<div>
									<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Логин</label>
									<input id="loginUsername" class="field" autocomplete="username" required>
								</div>
								<div>
									<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Пароль</label>
									<input id="loginPassword" type="password" class="field" autocomplete="current-password" required>
								</div>
								<div id="turnstileSlot" class="flex justify-center"></div>
								<div id="loginError" class="hidden rounded-lg border border-[#3f2024] bg-[#1a0f11] px-3 py-2 text-[13px] text-[#f87171]"></div>
								<button id="loginBtn" type="submit" class="btn btn-primary mt-1 w-full">Войти</button>
							</form>
						</div>
					</div>
				</div>`;

			if (errorMessage) showLoginError(errorMessage);
			$('loginForm').addEventListener('submit', handleLogin);
			renderTurnstile();
		}

		function showLoginError(msg) {
			const box = $('loginError');
			if (box) { box.textContent = msg; box.classList.remove('hidden'); }
		}

		async function handleLogin(e) {
			e.preventDefault();
			if (!turnstileToken) { showLoginError('Пройдите проверку капчи'); return; }
			const username = $('loginUsername').value.trim();
			const password = $('loginPassword').value;
			const btn = $('loginBtn');
			btn.disabled = true; btn.textContent = 'Проверка…';
			try {
				const data = await api('/api/auth/login', {
					method: 'POST',
					body: JSON.stringify({ username, password, turnstile_token: turnstileToken }),
				});
				storeToken(data.access_token);
				user = data.user;
				turnstileToken = '';
				await bootApp();
			} catch (err) {
				showLoginError(err.message);
				resetTurnstile();
				btn.disabled = false; btn.textContent = 'Войти';
			}
		}

		function logoutLocal() {
			storeToken(null);
			user = null;
			currentTab = 'dashboard';
			renderLogin();
		}

		async function logout() {
			try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) {}
			logoutLocal();
		}

		// ---------- Turnstile ----------

		function renderTurnstile() {
			const slot = $('turnstileSlot');
			if (!slot) return;
			if (typeof window.turnstile === 'undefined') return;
			window.turnstile.render(slot, {
				sitekey: TURNSTILE_SITE_KEY,
				theme: 'dark',
				callback: (value) => { turnstileToken = value; },
				'expired-callback': () => { turnstileToken = ''; },
				'error-callback': () => { turnstileToken = ''; },
			});
		}

		function resetTurnstile() {
			try { if (window.turnstile) window.turnstile.reset(); } catch (e) {}
		}

		window.__turnstileReady = function () {
			if (!token) renderTurnstile();
		};

		// ---------- App shell ----------

		async function bootApp() {
			try { user = await api('/api/auth/me'); } catch (e) { logoutLocal(); return; }
			renderShell();
			switchTab(currentTab);
			setInterval(refreshSystem, 5000);
		}

		function navItems() {
			const items = [
				{ id: 'dashboard', label: 'Дашборд', icon: 'dashboard' },
				{ id: 'verified', label: 'Галочка', icon: 'verified' },
			];
			if (user && user.is_owner) items.push({ id: 'accounts', label: 'Аккаунты', icon: 'accounts' });
			items.push({ id: 'sessions', label: 'Сессии', icon: 'sessions' });
			return items;
		}

		function renderShell() {
			const items = navItems();
			appEl.innerHTML = `
				<div class="mx-auto flex min-h-screen w-full max-w-[1280px] flex-col lg:flex-row">
					<aside class="hidden w-[240px] shrink-0 border-r border-[#1e1e22] lg:flex lg:flex-col">
						<div class="flex h-16 items-center gap-3 border-b border-[#1e1e22] px-5">
							<div class="flex h-9 w-9 items-center justify-center rounded-lg border border-[#232327] bg-[#121214]">
								<span class="text-xs font-bold tracking-[0.18em] text-[#fafafa]">VP</span>
							</div>
							<div class="leading-tight">
								<div class="text-sm font-semibold text-[#fafafa]">VisionPanel</div>
							</div>
						</div>
						<nav class="flex-1 space-y-1 p-3">
							${items.map((n) => `<button class="nav-item" data-tab="${n.id}">${ICONS[n.icon]}<span>${n.label}</span></button>`).join('')}
						</nav>
						<div class="border-t border-[#1e1e22] p-3">
							<div class="mb-3 flex items-center gap-3 px-3">
								<div class="flex h-8 w-8 items-center justify-center rounded-full bg-[#232327] text-[12px] font-semibold text-[#fafafa]">${escapeHtml((user.username || '?').slice(0, 1).toUpperCase())}</div>
								<div class="leading-tight min-w-0">
									<div class="text-[13px] font-medium text-[#e4e4e7] truncate">${escapeHtml(user.username)}</div>
									<div class="text-[11px] text-[#6b6b74]">${user.is_owner ? 'Владелец' : 'Аккаунт'}</div>
								</div>
							</div>
							<button id="logoutBtn" class="nav-item" style="color:#f87171;">${ICONS.logout}<span>Выйти</span></button>
						</div>
					</aside>

					<div class="flex min-w-0 flex-1 flex-col">
						<header class="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-[#1e1e22] bg-[#060608]/80 px-5 backdrop-blur">
							<button id="mobileMenu" class="btn btn-ghost btn-icon lg:hidden">${ICONS.menu}</button>
							<div class="min-w-0">
								<h1 id="pageTitle" class="text-[15px] font-semibold text-[#fafafa]">Дашборд</h1>
							</div>
							<div class="ml-auto flex items-center gap-3">
								<span id="healthPill" class="inline-flex items-center gap-2 rounded-full border border-[#232327] bg-[#0f0f11] px-3 py-1.5 text-[12px] text-[#9b9ba3]">
									<span class="h-1.5 w-1.5 rounded-full bg-[#6b6b74]"></span>
									<span id="healthPillText">Проверка…</span>
								</span>
							</div>
						</header>

						<main class="flex-1 p-5 lg:p-8">
							<div id="mobileNav" class="mb-5 hidden grid-cols-2 gap-2 lg:hidden"></div>
							<div id="tabContent"></div>
						</main>
					</div>
				</div>`;

			$('logoutBtn').addEventListener('click', logout);
			$('mobileMenu').addEventListener('click', toggleMobileNav);
			document.querySelectorAll('aside [data-tab]').forEach((btn) => {
				btn.addEventListener('click', () => switchTab(btn.dataset.tab));
			});
			renderMobileNav();
		}

		function renderMobileNav() {
			const wrap = $('mobileNav');
			if (!wrap) return;
			wrap.innerHTML = navItems().map((n) => `<button class="nav-item ${n.id === currentTab ? 'active' : ''}" data-tab="${n.id}" style="border-color:#1e1e22;">${ICONS[n.icon]}<span>${n.label}</span></button>`).join('');
			wrap.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
		}

		function toggleMobileNav() {
			const wrap = $('mobileNav');
			if (wrap) wrap.classList.toggle('hidden');
		}

		function escapeHtml(value) {
			return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
		}

		const PAGE_TITLES = {
			dashboard: 'Дашборд',
			verified: 'Галочка верификации',
			accounts: 'Аккаунты',
			sessions: 'Активные сессии',
		};

		function switchTab(tab) {
			if (tab === 'accounts' && !(user && user.is_owner)) tab = 'dashboard';
			currentTab = tab;
			document.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
			renderMobileNav();
			const title = $('pageTitle');
			if (title) title.textContent = PAGE_TITLES[tab] || 'VisionPanel';
			const content = $('tabContent');
			if (!content) return;
			content.innerHTML = '<div class="flex items-center justify-center py-20"><span class="spin inline-block h-6 w-6 rounded-full border-2 border-[#232327] border-t-[#fafafa]"></span></div>';
			const loaders = {
				dashboard: renderDashboard,
				verified: renderVerified,
				accounts: renderAccounts,
				sessions: renderSessions,
			};
			(loaders[tab] || renderDashboard)();
		}

		// ---------- Dashboard ----------

		async function refreshSystem() {
			if (!token || currentTab !== 'dashboard') return;
			try {
				const data = await api('/api/system');
				paintSystem(data);
				setHealthPill(true);
			} catch (e) { setHealthPill(false); }
		}

		function setHealthPill(online) {
			const pill = $('healthPill'); const text = $('healthPillText');
			if (!pill) return;
			const dot = pill.querySelector('span');
			dot.className = 'h-1.5 w-1.5 rounded-full ' + (online ? 'bg-[#34d399]' : 'bg-[#f87171]');
			text.textContent = online ? 'Сервер online' : 'Сервер offline';
		}

		function fmtBytes(bytes) {
			if (bytes == null) return '—';
			const units = ['B', 'KB', 'MB', 'GB', 'TB'];
			let i = 0; let v = bytes;
			while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
			return v.toFixed(v >= 100 || i === 0 ? 0 : 1) + ' ' + units[i];
		}

		async function renderDashboard() {
			const content = $('tabContent');
			if (!content) return;
			content.innerHTML = `
				<div class="fade-in grid gap-5">
					<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
						${metricCard('ram', 'RAM', 'Оперативная память')}
						${metricCard('disk', 'Диск', 'Свободное место')}
						${metricCard('ping', 'Пинг БД', 'Задержка запроса')}
						${metricCard('uptime', 'Аптайм', 'Время работы')}
					</div>
					<div class="grid gap-5 lg:grid-cols-2">
						<div class="card rounded-2xl p-6">
							<h3 class="text-[15px] font-semibold text-[#fafafa]">Обзор</h3>
							<p class="mt-1 text-[13px] text-[#6b6b74]">Мониторинг ресурсов сервера в реальном времени.</p>
							<div class="mt-5 space-y-4" id="systemBars">
								<div class="animate-pulse h-3 rounded-full bg-[#17171a]"></div>
								<div class="animate-pulse h-3 rounded-full bg-[#17171a]"></div>
							</div>
							<div class="mt-5 grid grid-cols-3 gap-3" id="countsRow"></div>
						</div>
						<div class="card rounded-2xl p-6">
							<h3 class="text-[15px] font-semibold text-[#fafafa]">Аккаунт</h3>
							<p class="mt-1 text-[13px] text-[#6b6b74]">Текущая сессия панели.</p>
							<div class="mt-5 grid gap-3 text-[13px]">
								<div class="flex items-center justify-between rounded-lg bg-[#0b0b0d] border border-[#1e1e22] px-4 py-3">
									<span class="text-[#9b9ba3]">Логин</span>
									<span class="font-medium text-[#e4e4e7]">${escapeHtml(user.username)}</span>
								</div>
								<div class="flex items-center justify-between rounded-lg bg-[#0b0b0d] border border-[#1e1e22] px-4 py-3">
									<span class="text-[#9b9ba3]">Роль</span>
									<span class="font-medium text-[#e4e4e7]">${user.is_owner ? 'Владелец' : 'Аккаунт'}</span>
								</div>
								<div class="flex items-center justify-between rounded-lg bg-[#0b0b0d] border border-[#1e1e22] px-4 py-3">
									<span class="text-[#9b9ba3]">Создан</span>
									<span class="font-medium text-[#e4e4e7]">${formatDate(user.created_at)}</span>
								</div>
							</div>
						</div>
					</div>
				</div>`;
			try {
				const data = await api('/api/system');
				paintSystem(data);
				setHealthPill(true);
			} catch (e) { setHealthPill(false); }
		}

		function metricCard(id, label, hint) {
			return `
				<div class="card rounded-2xl p-5">
					<div class="flex items-center justify-between">
						<span class="text-[13px] font-medium text-[#9b9ba3]">${label}</span>
						<svg class="h-4 w-4 text-[#55555c]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0Z"/></svg>
					</div>
					<div id="metric-${id}" class="mt-3 text-2xl font-semibold tracking-tight text-[#fafafa]">—</div>
					<div class="mt-1 text-[12px] text-[#6b6b74]">${hint}</div>
				</div>`;
		}

		function paintSystem(data) {
			setMetric('ram', data.ram.percent.toFixed(0) + '%', `${fmtBytes(data.ram.used)} / ${fmtBytes(data.ram.total)}`);
			setMetric('disk', fmtBytes(data.disk.free), `${data.disk.percent}% занято`);
			setMetric('ping', data.ping.db_ms + ' мс', 'SQLite запрос');
			setMetric('uptime', fmtUptime(data.uptime), 'с момента запуска');

			const bars = $('systemBars');
			if (bars) {
				bars.innerHTML = `
					${progressBar('Использование RAM', data.ram.percent)}
					${progressBar('Использование диска', data.disk.percent)}`;
			}

			const counts = $('countsRow');
			if (counts && data.counts) {
				counts.innerHTML = `
					${countTile(data.counts.users, 'Аккаунтов')}
					${countTile(data.counts.badges, 'Галочек')}
					${countTile(data.counts.active_sessions, 'Сессий')}`;
			}
		}

		function countTile(value, label) {
			return `
				<div class="rounded-xl border border-[#1e1e22] bg-[#0b0b0d] px-3 py-3 text-center">
					<div class="text-xl font-semibold text-[#fafafa]">${value}</div>
					<div class="mt-0.5 text-[11px] text-[#6b6b74]">${label}</div>
				</div>`;
		}

		function setMetric(id, value, sub) {
			const node = $('metric-' + id);
			if (!node) return;
			node.textContent = value;
			node.parentElement.querySelector('div.text-\\[12px\\]').textContent = sub;
		}

		function progressBar(label, percent) {
			return `
				<div>
					<div class="mb-1.5 flex items-center justify-between text-[12px]">
						<span class="text-[#9b9ba3]">${label}</span>
						<span class="font-medium text-[#e4e4e7]">${percent.toFixed(1)}%</span>
					</div>
					<div class="h-2 overflow-hidden rounded-full bg-[#1a1a1e]">
						<div class="h-full rounded-full bg-[#55555c] transition-all duration-500" style="width:${Math.min(100, percent)}%"></div>
					</div>
				</div>`;
		}

		function fmtUptime(seconds) {
			const d = Math.floor(seconds / 86400);
			const h = Math.floor((seconds % 86400) / 3600);
			const m = Math.floor((seconds % 3600) / 60);
			if (d) return `${d}д ${h}ч`;
			if (h) return `${h}ч ${m}м`;
			return `${m}м`;
		}

		const VERIFIED_SVG = '<svg viewBox="0 0 24 24" fill="none"><path d="M12 1.7 14.7 4.4 18.5 4 19.6 7.6 22.8 9.7 21.2 13.2 22.8 16.7 19.6 18.8 18.5 22.4 14.7 22 12 23.5 9.3 22 5.5 22.4 4.4 18.8 1.2 16.7 2.8 13.2 1.2 9.7 4.4 7.6 5.5 4 9.3 4.4Z" fill="#3390ec"/><path d="m7.6 12.4 3 3 5.8-5.8" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

		function verifiedChip() {
			const chip = el('span', 'verified-chip');
			chip.innerHTML = VERIFIED_SVG;
			return chip;
		}

		// ---------- Verified ----------

		let verifiedList = [];

		async function renderVerified() {
			const content = $('tabContent');
			content.innerHTML = `
				<div class="fade-in grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
					<section class="card rounded-2xl p-6">
						<h3 class="text-[15px] font-semibold text-[#fafafa]">Выдать галочку</h3>
						<p class="mt-1 text-[13px] text-[#6b6b74]">Галочка видна всем пользователям VisionGram рядом с ником.</p>
						<form id="verifiedForm" class="mt-5 grid gap-4" autocomplete="off">
							<div class="grid gap-4 sm:grid-cols-2">
								<div>
									<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Telegram ID</label>
									<input id="verifiedTelegramId" class="field" inputmode="numeric" placeholder="123456789" required>
								</div>
								<div>
									<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Username</label>
									<input id="verifiedUsername" class="field" placeholder="username">
								</div>
							</div>
							<div>
								<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Имя</label>
								<input id="verifiedDisplayName" class="field" placeholder="Имя в Telegram">
							</div>
							<div class="flex items-center gap-3">
								<button id="verifiedSave" type="submit" class="btn btn-primary">Выдать галочку</button>
								<span class="text-[12px] text-[#6b6b74]">Повторная выдача обновляет данные.</span>
							</div>
						</form>
					</section>

					<aside class="card rounded-2xl p-6">
						<h3 class="text-[15px] font-semibold text-[#fafafa]">Как выглядит</h3>
						<p class="mt-1 text-[13px] text-[#6b6b74]">Наведение на галочку в клиенте показывает подпись.</p>
						<div class="mt-6 flex min-h-[120px] items-center justify-center rounded-xl border border-dashed border-[#232327] bg-[#0b0b0d] p-6">
							<span class="verified-chip" style="transform:scale(1.6);">${VERIFIED_SVG}</span>
						</div>
					</aside>
				</div>

				<section class="card mt-5 rounded-2xl overflow-hidden">
					<div class="flex flex-col gap-3 border-b border-[#1e1e22] p-5 sm:flex-row sm:items-center sm:justify-between">
						<div>
							<h3 class="text-[15px] font-semibold text-[#fafafa]">С верификацией</h3>
							<p class="mt-1 text-[13px] text-[#6b6b74]" id="verifiedCount">—</p>
						</div>
						<div class="relative">
							<input id="verifiedSearch" class="field sm:w-64" placeholder="Поиск по ID, username, имени">
						</div>
					</div>
					<div id="verifiedListWrap" class="p-5"></div>
				</section>`;

			$('verifiedForm').addEventListener('submit', grantVerified);
			let t; $('verifiedSearch').addEventListener('input', () => { clearTimeout(t); t = setTimeout(loadVerified, 300); });

			await loadVerified();
		}

		async function loadVerified() {
			const wrap = $('verifiedListWrap'); const count = $('verifiedCount');
			if (!wrap) return;
			wrap.innerHTML = '<div class="text-[13px] text-[#6b6b74]">Загрузка…</div>';
			try {
				const q = $('verifiedSearch').value.trim();
				const data = await api('/api/verified?limit=500' + (q ? '&q=' + encodeURIComponent(q) : ''));
				verifiedList = data.verified || [];
				count.textContent = 'Всего: ' + verifiedList.length;
				if (!verifiedList.length) {
					wrap.innerHTML = '<div class="py-8 text-center text-[13px] text-[#6b6b74]">Никого с галочкой пока нет</div>';
					return;
				}
				wrap.innerHTML = '';
				for (const item of verifiedList) {
					const row = el('div', 'flex items-center justify-between gap-3 rounded-xl border border-[#1e1e22] bg-[#0b0b0d] px-4 py-3 mb-2');
					const left = el('div', 'flex min-w-0 items-center gap-3');
					left.append(verifiedChip());
					const meta = el('div', 'min-w-0 leading-tight');
					const name = el('div', 'truncate text-[13px] font-medium text-[#e4e4e7]', item.display_name || '—');
					const id = el('div', 'truncate text-[12px] text-[#6b6b74]', (item.username ? '@' + item.username + ' · ' : '') + item.telegram_id);
					meta.append(name, id);
					left.append(meta);
					const actions = el('div', 'flex items-center gap-1');
					const revokeBtn = el('button', 'btn btn-danger', 'Забрать');
					revokeBtn.addEventListener('click', () => revokeVerified(item.telegram_id));
					actions.append(revokeBtn);
					row.append(left, actions);
					wrap.append(row);
				}
			} catch (e) {
				wrap.innerHTML = '<div class="py-8 text-center text-[13px] text-[#f87171]">' + escapeHtml(e.message) + '</div>';
			}
		}

		async function grantVerified(e) {
			e.preventDefault();
			const telegramId = Number($('verifiedTelegramId').value.trim());
			if (!Number.isInteger(telegramId) || telegramId <= 0) { toast('Укажите корректный Telegram ID', 'error'); return; }
			const btn = $('verifiedSave'); btn.disabled = true; btn.textContent = 'Сохранение…';
			try {
				await api('/api/verified/set', {
					method: 'POST',
					body: JSON.stringify({
						telegram_id: telegramId,
						username: $('verifiedUsername').value.trim() || null,
						display_name: $('verifiedDisplayName').value.trim() || null,
					}),
				});
				toast('Галочка выдана');
				await loadVerified();
			} catch (err) { toast(err.message, 'error'); }
			finally { btn.disabled = false; btn.textContent = 'Выдать галочку'; }
		}

		async function revokeVerified(id) {
			if (!confirm('Забрать галочку у ID ' + id + '?')) return;
			try { await api('/api/verified/' + id, { method: 'DELETE' }); await loadVerified(); toast('Галочка отозвана'); }
			catch (e) { toast(e.message, 'error'); }
		}

		// ---------- Accounts (owner only) ----------

		async function renderAccounts() {
			const content = $('tabContent');
			content.innerHTML = `
				<div class="fade-in grid gap-5">
					<div class="card rounded-2xl p-6">
						<h3 class="text-[15px] font-semibold text-[#fafafa]">Создать аккаунт</h3>
						<p class="mt-1 text-[13px] text-[#6b6b74]">Новый доступ к панели. Пароль передаётся один раз — сохраните его.</p>
						<form id="accountForm" class="mt-5 grid gap-4 sm:grid-cols-2" autocomplete="off">
							<div>
								<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Логин</label>
								<input id="accountUsername" class="field" placeholder="латиница, цифры, _ и -" required>
							</div>
							<div>
								<label class="mb-1.5 block text-[13px] font-medium text-[#d4d4d8]">Пароль</label>
								<div class="flex gap-2">
									<input id="accountPassword" class="field" placeholder="минимум 8 символов" required>
									<button id="accountGen" type="button" class="btn btn-ghost btn-icon" title="Сгенерировать">⌁</button>
								</div>
							</div>
							<div class="sm:col-span-2">
								<button id="accountSave" type="submit" class="btn btn-primary">Создать аккаунт</button>
							</div>
						</form>
					</div>

					<section class="card rounded-2xl overflow-hidden">
						<div class="border-b border-[#1e1e22] p-5">
							<h3 class="text-[15px] font-semibold text-[#fafafa]">Аккаунты</h3>
							<p class="mt-1 text-[13px] text-[#6b6b74]" id="accountCount">—</p>
						</div>
						<div id="accountListWrap" class="p-5"></div>
					</section>
				</div>`;

			$('accountForm').addEventListener('submit', createAccount);
			$('accountGen').addEventListener('click', () => {
				const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789';
				let out = '';
				const arr = new Uint32Array(14);
				crypto.getRandomValues(arr);
				for (const n of arr) out += chars[n % chars.length];
				$('accountPassword').value = out;
			});
			await loadAccounts();
		}

		async function loadAccounts() {
			const wrap = $('accountListWrap'); const count = $('accountCount');
			if (!wrap) return;
			wrap.innerHTML = '<div class="text-[13px] text-[#6b6b74]">Загрузка…</div>';
			try {
				const data = await api('/api/accounts');
				const accounts = data.accounts || [];
				count.textContent = 'Всего: ' + accounts.length;
				if (!accounts.length) { wrap.innerHTML = '<div class="py-8 text-center text-[13px] text-[#6b6b74]">Нет аккаунтов</div>'; return; }
				wrap.innerHTML = '';
				for (const a of accounts) {
					const row = el('div', 'flex items-center justify-between gap-3 rounded-xl border border-[#1e1e22] bg-[#0b0b0d] px-4 py-3 mb-2');
					const left = el('div', 'flex min-w-0 items-center gap-3');
					const avatar = el('div', 'flex h-9 w-9 flex-none items-center justify-center rounded-full bg-[#232327] text-[12px] font-semibold text-[#fafafa]', (a.username || '?').slice(0, 1).toUpperCase());
					left.append(avatar);
					const meta = el('div', 'min-w-0 leading-tight');
					const titleLine = el('div', 'flex items-center gap-2');
					titleLine.append(el('span', 'truncate text-[13px] font-medium text-[#e4e4e7]', a.username));
					if (a.is_owner) titleLine.append(el('span', 'rounded-full bg-[#fafafa]/10 px-2 py-0.5 text-[10px] font-medium text-[#e4e4e7]', 'Владелец'));
					meta.append(titleLine);
					meta.append(el('div', 'truncate text-[12px] text-[#6b6b74]', 'Создан ' + formatDate(a.created_at)));
					left.append(meta);
					row.append(left);
					if (!a.is_owner) {
						const btn = el('button', 'btn btn-danger', 'Удалить');
						btn.addEventListener('click', () => deleteAccount(a));
						row.append(btn);
					}
					wrap.append(row);
				}
			} catch (e) { wrap.innerHTML = '<div class="py-8 text-center text-[13px] text-[#f87171]">' + escapeHtml(e.message) + '</div>'; }
		}

		async function createAccount(e) {
			e.preventDefault();
			const username = $('accountUsername').value.trim();
			const password = $('accountPassword').value;
			if (username.length < 3) { toast('Логин: минимум 3 символа', 'error'); return; }
			if (password.length < 8) { toast('Пароль: минимум 8 символов', 'error'); return; }
			const btn = $('accountSave'); btn.disabled = true; btn.textContent = 'Создание…';
			try {
				await api('/api/accounts', { method: 'POST', body: JSON.stringify({ username, password }) });
				toast('Аккаунт создан');
				$('accountUsername').value = '';
				$('accountPassword').value = '';
				await loadAccounts();
			} catch (err) { toast(err.message, 'error'); }
			finally { btn.disabled = false; btn.textContent = 'Создать аккаунт'; }
		}

		async function deleteAccount(a) {
			if (!confirm('Удалить аккаунт «' + a.username + '»? Его сессии будут завершены.')) return;
			try { await api('/api/accounts/' + a.id, { method: 'DELETE' }); toast('Аккаунт удалён'); await loadAccounts(); }
			catch (e) { toast(e.message, 'error'); }
		}

		// ---------- Sessions ----------

		async function renderSessions() {
			const content = $('tabContent');
			content.innerHTML = `
				<div class="fade-in card rounded-2xl p-6">
					<div class="mb-5">
						<h3 class="text-[15px] font-semibold text-[#fafafa]">Активные сессии</h3>
						<p class="mt-1 text-[13px] text-[#6b6b74]">Входы в текущую учётную запись.</p>
					</div>
					<div id="sessionsWrap" class="space-y-2"></div>
				</div>`;
			await loadSessions();
		}

		async function loadSessions() {
			const wrap = $('sessionsWrap');
			if (!wrap) return;
			wrap.innerHTML = '<div class="text-[13px] text-[#6b6b74]">Загрузка…</div>';
			try {
				const data = await api('/api/sessions');
				const sessions = data.sessions || [];
				if (!sessions.length) { wrap.innerHTML = '<div class="py-8 text-center text-[13px] text-[#6b6b74]">Нет активных сессий</div>'; return; }
				wrap.innerHTML = '';
				for (const s of sessions) {
					const row = el('div', 'flex items-center justify-between gap-3 rounded-xl border border-[#1e1e22] bg-[#0b0b0d] px-4 py-3');
					if (s.current) row.style.borderColor = '#2e2e33';
					const left = el('div', 'flex min-w-0 items-center gap-3');
					const dot = el('div', 'flex h-9 w-9 flex-none items-center justify-center rounded-full bg-[#121214] border border-[#232327]');
					dot.innerHTML = '<span class="h-2 w-2 rounded-full ' + (s.current ? 'bg-[#34d399]' : 'bg-[#55555c]') + '"></span>';
					left.append(dot);
					const meta = el('div', 'min-w-0 leading-tight');
					const titleLine = el('div', 'flex items-center gap-2');
					titleLine.append(el('span', 'truncate text-[13px] font-medium text-[#e4e4e7]', s.device || 'Unknown'));
					if (s.current) {
						const tag = el('span', 'rounded-full bg-[#fafafa]/10 px-2 py-0.5 text-[10px] font-medium text-[#e4e4e7]', 'Текущая');
						titleLine.append(tag);
					}
					meta.append(titleLine);
					meta.append(el('div', 'truncate text-[12px] text-[#6b6b74]', 'IP ' + (s.ip || '—') + ' · вход ' + formatDate(s.created_at)));
					left.append(meta);
					row.append(left);
					if (!s.current) {
						const btn = el('button', 'btn btn-danger', 'Завершить');
						btn.addEventListener('click', () => terminateSession(s.id));
						row.append(btn);
					}
					wrap.append(row);
				}
			} catch (e) { wrap.innerHTML = '<div class="py-8 text-center text-[13px] text-[#f87171]">' + escapeHtml(e.message) + '</div>'; }
		}

		async function terminateSession(id) {
			if (!confirm('Завершить эту сессию?')) return;
			try { await api('/api/sessions/' + id, { method: 'DELETE' }); toast('Сессия завершена'); await loadSessions(); }
			catch (e) { toast(e.message, 'error'); }
		}

		function formatDate(iso) {
			if (!iso) return '—';
			try { return new Date(iso.replace(' ', 'T') + 'Z').toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }); }
			catch (e) { return iso; }
		}

		// ---------- Boot ----------

		if (token) {
			bootApp();
		} else {
			renderLogin();
		}
	