// main.js
// Весь JS-код Alpine и Sortable
function app() {
    console.log('Alpine app loaded');
    return {
        hoveredBeatIdx: null,
        formatDate(ts) {
            if (!ts) return '';
            if (typeof ts === 'number') return new Date(ts*1000).toLocaleString();
            return ts;
        },
        getBeatTooltip(proxy, idx, h) {
            let status = h ? 'UP' : 'DOWN';
            let date = (proxy.history_ts && proxy.history_ts[idx]) ? proxy.history_ts[idx] : null;
            if (date) {
                if (typeof date === 'number') date = new Date(date*1000).toLocaleString();
                return status + ' ' + date;
            }
            return status;
        },
        getStatusTooltip(p) {
            let status = p.status ? 'UP' : 'DOWN';
            let date = (p.last_check || (p.history_ts && p.history_ts.length ? p.history_ts[p.history_ts.length-1] : null));
            if (date) {
                if (typeof date === 'number') date = new Date(date*1000).toLocaleString();
                return status + (date ? (' ' + date) : '');
            }
            return status;
        },
        auth: false, token: '', tokenInput: '', showLogin: false,
        darkMode: true, showSettings: false, sidebarOpen: false, showGroupManager: false, isRunning: false,
        proxies: [], groups: [], configurations: [], settings: {auto_run: true, interval: 60}, test_urls: [],
        newGroupName: '', newTestUrl: '',
        editModal: { show: false, isEdit: false, index: -1, name: '', link: '', group: 'General' },
        logModal: { show: false, title: '', content: '' }, statsModal: { show: false, data: {} },
        countdown: 0, timer: null, evt: null,
        init() {
            const th = localStorage.getItem('theme');
            if (th === 'light') this.darkMode = false;
            this.token = localStorage.getItem('uptime_token') || '';
            if(this.token) this.verifyToken();
            this.loadState();
            setTimeout(() => {
                console.log('groups:', this.groups);
                console.log('proxies:', this.proxies);
            }, 2000);
        },
        async verifyToken() {
            const res = await fetch('/api/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token: this.token}) });
            if(res.ok) { this.auth = true; this.$nextTick(() => this.initSortable()); } else { this.auth=false; localStorage.removeItem('uptime_token'); }
        },
        async login() {
            this.token = this.tokenInput;
            await this.verifyToken();
            if(this.auth) { localStorage.setItem('uptime_token', this.token); this.showLogin = false; window.location.reload(); } else alert("Invalid token");
        },
        logout() {
            this.auth = false; this.token = ''; localStorage.removeItem('uptime_token'); window.location.reload();
        },
        initSortable() {
            const groupList = document.getElementById('groups-list');
            if(groupList) {
                new Sortable(groupList, {
                    animation: 150,
                    handle: '.group-container > div:first-child', 
                    onEnd: (evt) => {
                        const newOrder = Array.from(groupList.children).map(el => el.getAttribute('data-group')).filter(x => x);
                        this.groups = newOrder;
                        this.saveState(true);
                    }
                });
            }
            this.$nextTick(() => {
                const lists = document.querySelectorAll('.monitors-list');
                lists.forEach(list => {
                    new Sortable(list, {
                        group: 'monitors',
                        animation: 150,
                        draggable: '.monitor-item',
                        onEnd: (evt) => {
                            const allMonitorEls = document.querySelectorAll('.monitor-item');
                            const newConfigOrder = [];
                            allMonitorEls.forEach(el => {
                                const name = el.getAttribute('data-name');
                                const parentGroup = el.closest('.monitors-list').getAttribute('data-group-name');
                                const orig = this.configurations.find(c => c.name === name);
                                if (orig) {
                                    newConfigOrder.push({ ...orig, group: parentGroup });
                                }
                            });
                            this.configurations = newConfigOrder;
                            this.proxies.forEach(p => {
                                const conf = this.configurations.find(c => c.name === p.name);
                                if (conf) p.group = conf.group || conf.group_name;
                            });
                            this.proxies = this.configurations.map(c => {
                                const p = this.proxies.find(p => p.name === c.name && p.group === (c.group || c.group_name));
                                if (p) return p;
                                return {
                                    name: c.name,
                                    group: c.group || c.group_name,
                                    status: false,
                                    uptime_1d: 0,
                                    uptime_30d: 0,
                                    uptime_1y: 0,
                                    latency: 0,
                                    msg: '',
                                    history: [],
                                    log: ''
                                };
                            });
                            this.groups.forEach(g => {
                                const proxiesInGroup = this.proxies.filter(p => p.group === g).map(p => p.name);
                                const confs = this.configurations.filter(c => (c.group || c.group_name) === g);
                                confs.sort((a, b) => proxiesInGroup.indexOf(a.name) - proxiesInGroup.indexOf(b.name));
                            });
                            this.saveState(true);
                        }
                    });
                });
            });
        },
        async api(url, method='POST', body={}) {
            if(!this.auth) { alert("Unauthorized"); return; }
            return fetch(url, {
                method: method,
                headers: {'Content-Type': 'application/json', 'X-Api-Token': this.token},
                body: JSON.stringify(body)
            });
        },
        loadState() {
            fetch('/get_state').then(r=>r.json()).then(data => {
                this.settings = data.settings;
                this.test_urls = data.test_urls;
                this.groups = data.groups;
                this.configurations = data.configurations;
                this.$nextTick(() => this.initSortable());
                this.runCheck();
            });
        },
        saveState(force=false) {
            if(!this.auth && !force) return;
            const payload = { settings: this.settings, test_urls: this.test_urls, groups: this.groups, configurations: this.configurations };
            this.api('/save_state', 'POST', payload).then(() => {
                this.$nextTick(() => this.initSortable());
            });
        },
        addTestUrl() { if(this.newTestUrl) { this.test_urls.push(this.newTestUrl); this.newTestUrl=''; this.$nextTick(() => this.initSortable()); } },
        removeTestUrl(idx) { this.test_urls.splice(idx, 1); this.$nextTick(() => this.initSortable()); },
        openAddModal() { this.editModal = { show: true, isEdit: false, index: -1, name: '', link: '', group: this.groups[0]||'General' }; },
        editMonitor(conf) {
            const idx = this.configurations.indexOf(conf);
            this.editModal = {
                show: true,
                isEdit: true,
                index: idx,
                name: conf.name,
                link: conf.link,
                group: conf.group_name || conf.group || 'General'
            };
        },
        saveMonitor() {
            if(!this.editModal.link) return alert("Link required");
            const item = {
                name: this.editModal.name,
                link: this.editModal.link,
                group: this.editModal.group,
                group_name: this.editModal.group // ensure both fields are set
            };
            if(this.editModal.isEdit) this.configurations[this.editModal.index] = item;
            else this.configurations.push(item);
            this.saveState(); this.editModal.show = false;
            this.$nextTick(() => this.initSortable());
        },
        deleteMonitor() { if(confirm("Delete?")) { this.configurations.splice(this.editModal.index, 1); this.saveState(); this.editModal.show = false; this.proxies = this.proxies.filter(p => !(p.name.startsWith(this.editModal.name) && p.group === this.editModal.group)); this.$nextTick(() => this.initSortable()); } },
        addGroup() { if(this.newGroupName && !this.groups.includes(this.newGroupName)) { this.groups.push(this.newGroupName); this.newGroupName=''; this.saveState(); this.api('/groups/add', 'POST', {name:this.newGroupName}); this.$nextTick(() => this.initSortable()); } },
        deleteGroup(name) {
            if(name==='General') return;
            if(confirm("Delete group?")) {
                this.groups = this.groups.filter(g => g !== name);
                this.configurations.forEach(c => {
                    if(c.group === name) c.group = 'General';
                    if(c.group_name === name) c.group_name = 'General';
                });
                this.saveState();
                this.api('/groups/delete', 'POST', {name:name});
                this.$nextTick(() => this.initSortable());
            }
        },
        clearHistory() { if(confirm("Clear ALL?")) this.api('/clear_history'); },
        runCheck() {
            if(this.timer) clearInterval(this.timer); this.countdown = 0;
            if(this.evt) this.evt.close();
            this.isRunning = true;
            this.evt = new EventSource('/stream_check');
            this.evt.onmessage = (e) => { const d = JSON.parse(e.data); if(d.type==='result') this.updateProxy(d); else if(d.type==='done') this.finishCheck(); };
            this.evt.onerror = () => this.finishCheck();
        },
        updateProxy(d) {
            const idx = this.proxies.findIndex(p => p.group === d.group && p.name === d.name);
            if(idx > -1) this.proxies[idx] = {...d}; else this.proxies.push({...d});
        },
        finishCheck() {
            if(this.evt) this.evt.close();
            this.isRunning = false;
            this.countdown = this.settings.interval;
            this.timer = setInterval(() => { this.countdown--; if(this.countdown<=0) { clearInterval(this.timer); this.runCheck(); } }, 1000);
        },
        toggleTheme() { this.darkMode = !this.darkMode; localStorage.setItem('theme', this.darkMode?'dark':'light'); },
        formatTime(s) { return new Date(s*1000).toISOString().substr(14,5); },
        getAggregateStatus(name) { return this.proxies.some(p => p.name.startsWith(name) && p.status); },
        getColor(val) { return val >= 95 ? 'text-[var(--success)]' : (val >= 70 ? 'text-[var(--warning)]' : 'text-[var(--danger)]'); },
        showLog(p) { this.logModal={show:true, title:p.name, content:p.log}; },
        showStatsModal(p) { this.statsModal={show:true, data:p}; },
        getConfigsByGroup(gName) {
            return this.configurations.filter(c => c.group === gName || c.group_name === gName);
        },
        getProxiesByGroup(gName) { return this.proxies.filter(p => p.group === gName); },
        get stats() { const t=this.proxies.length; const on=this.proxies.filter(p=>p.status).length; return {total:t, online:on, offline:t-on}; }
    }
}
