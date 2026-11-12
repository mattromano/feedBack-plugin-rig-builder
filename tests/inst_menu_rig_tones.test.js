// The "Rig tones" section Rig Builder adds to the core's guitar dropdown
// (v3Badges.registerMenuSection): saved Studio tones as one-click loads through
// the same saved-tone loader as the tone override. Loads screen.js in a bare vm
// window (no DOM) and drives the section with a fake slot.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load({ songLoading = false } = {}) {
    const fetches = [];
    const locked = [];
    const registered = [];
    const noopEl = { classList: { add() {}, remove() {} }, addEventListener() {},
        querySelector: () => null, prepend() {}, remove() {}, innerHTML: '' };
    const window = {
        console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
        RB_API: '/api/plugins/rig_builder',
        localStorage: { getItem: () => null, setItem() {} },
        document: {
            getElementById: () => null,
            createElement: () => Object.assign({}, noopEl),
            addEventListener() {},
            querySelectorAll: () => [],
            head: { appendChild() {} },
            body: { appendChild() {} },
        },
        addEventListener() {},
        setTimeout: () => 0,
        clearTimeout() {},
        setInterval: () => 0,
        clearInterval() {},
        requestAnimationFrame: () => 0,
        fetch: (url) => { fetches.push(String(url)); return Promise.resolve({ ok: false, json: () => Promise.resolve({}), text: () => Promise.resolve('') }); },
        slopsmith: { on() {} },
        feedBackDesktop: { audio: { loadPreset: async () => true } },
        _aeWithToneChainLock: (job) => { locked.push(true); return job(); },
        _aeSongTransitionUntil: songLoading ? Date.now() + 60000 : 0,
        v3Badges: { registerMenuSection: (id, render, opts) => { registered.push({ id, render, opts }); return true; } },
    };
    window.window = window;
    window.globalThis = window;
    const ctx = vm.createContext(window);
    ctx.document = window.document;
    ctx.localStorage = window.localStorage;
    const src = fs.readFileSync(path.join(__dirname, '..', 'screen.js'), 'utf8');
    vm.runInContext(src, ctx, { filename: 'rig-builder/screen.js' });
    return { window, t: window.__rbTest, fetches, locked, registered };
}

function fakeSlot() {
    const buttons = [];
    return {
        innerHTML: '',
        buttons,
        querySelectorAll(sel) {
            if (sel !== '[data-rb-tone]') return [];
            const names = [...this.innerHTML.matchAll(/data-rb-tone="([^"]+)"/g)].map((m) => m[1]);
            names.forEach((n) => buttons.push({ n, h: null, getAttribute: () => n, addEventListener(type, f) { this.h = f; } }));
            return buttons;
        },
    };
}

const flush = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };

test('registers a Rig tones section after the script has run, below the other sections', () => {
    const { t, registered } = load();
    assert.equal(registered.length, 0, 'not during script evaluation');
    t.rbRegisterInstMenuRigTones();
    assert.equal(registered[0].id, 'rig-builder-tones');
    assert.equal(registered[0].opts.order, 30);
});

test('lists saved tones as buttons; empty when there are none', () => {
    const { t } = load();
    const st = t.state();
    st._savedTonesLoaded = true;
    st.savedTones = [];
    const empty = fakeSlot();
    t.rbRenderInstMenuRigTones(empty, { refresh() {} });
    assert.equal(empty.innerHTML, '');
    st.savedTones = [{ id: 8249, name: 'Cherub Rock Solo', pieces: [] }, { id: 8250, name: 'Gently Weeps Prince Solo', pieces: [] }];
    const slot = fakeSlot();
    t.rbRenderInstMenuRigTones(slot, { refresh() {} });
    assert.match(slot.innerHTML, /Rig tones/);
    assert.match(slot.innerHTML, /data-rb-tone="Cherub Rock Solo"/);
    assert.match(slot.innerHTML, /data-rb-tone="Gently Weeps Prince Solo"/);
});

test('a click loads that saved tone through the chain lock', async () => {
    const { t, fetches, locked } = load();
    const st = t.state();
    st._savedTonesLoaded = true;
    st.savedTones = [{ id: 8249, name: 'Cherub Rock Solo', pieces: [] }];
    const slot = fakeSlot();
    let refreshes = 0;
    t.rbRenderInstMenuRigTones(slot, { refresh: () => { refreshes++; } });
    await slot.buttons[0].h();
    await flush();
    assert.equal(locked.length, 1, 'ran under the desktop tone chain lock');
    assert.ok(fetches.includes('/api/plugins/rig_builder/native_preset_full/8249'), 'fetched that tone\'s full preset');
    assert.equal(refreshes, 2, 'menu redrawn for loading and done');
});

test('no load while a song is loading', async () => {
    const { t, fetches, locked } = load({ songLoading: true });
    const st = t.state();
    st._savedTonesLoaded = true;
    st.savedTones = [{ id: 8249, name: 'Cherub Rock Solo', pieces: [] }];
    const slot = fakeSlot();
    t.rbRenderInstMenuRigTones(slot, { refresh() {} });
    await slot.buttons[0].h();
    assert.equal(locked.length, 0);
    assert.ok(!fetches.some((u) => u.includes('native_preset_full')));
});

test('the override path and the dropdown share one saved-tone loader', () => {
    const src = fs.readFileSync(path.join(__dirname, '..', 'screen.js'), 'utf8');
    assert.match(src, /async function rbLoadOverrideTone\(\)[\s\S]*?return rbLoadSavedTone\(api, t, 'tone override'\);/);
    assert.equal((src.match(/async function rbLoadSavedTone\(/g) || []).length, 1, 'one saved-tone loader');
    assert.match(src, /async function rbLoadSavedTone\(api, t, what\)[\s\S]*?native_preset_full\/\$\{t\.id\}[\s\S]*?rbLoadNativePresetPayload\(/);
    assert.match(src, /lock\(\(\) => rbLoadSavedTone\(rbAudioApi\(\), t, 'dropdown tone'\)\)/);
});
